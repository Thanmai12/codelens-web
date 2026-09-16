"""
Hardcoded secrets checker.

Two detection strategies, combined (like GitLeaks/TruffleHog):

1. Regex signatures for known secret formats (AWS keys, GitHub tokens,
   Slack tokens, generic API-key/password assignments, private key
   headers, JWTs, etc).
2. Shannon entropy scan over string literals assigned to
   suspicious-looking variable names (key, token, secret, password, ...)
   to catch secrets that don't match a known vendor pattern.

False-positive guards:
- Skips obvious placeholders (all-same-char, "xxxx", "<...>", "changeme",
  "example", "your_api_key_here", etc.)
- Skips strings shorter than a minimum length.
- Honors `# noqa` / `# codelens: ignore` on the offending line.
"""

from __future__ import annotations

import ast
import math
import re
from typing import List

from .base import BaseChecker, Category, FileContext, Issue, Severity

# (name, compiled regex, severity) -- regex should capture the secret in group 1 where possible
SIGNATURES = [
    ("AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), Severity.CRITICAL),
    ("AWS Secret Access Key", re.compile(r"(?i)aws_secret_access_key\s*=\s*['\"]([A-Za-z0-9/+=]{40})['\"]"), Severity.CRITICAL),
    ("GitHub Token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b"), Severity.CRITICAL),
    ("Slack Token", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,72})\b"), Severity.CRITICAL),
    ("Generic Private Key", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), Severity.CRITICAL),
    ("Slack Webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"), Severity.CRITICAL),
    ("JWT", re.compile(r"\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), Severity.WARNING),
    (
        "Hardcoded credential assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|passwd|password|token|access[_-]?key)\b\s*[:=]\s*"
            r"['\"]([^'\"]{6,})['\"]"
        ),
        Severity.ERROR,
    ),
]

SUSPICIOUS_NAME = re.compile(r"(?i)(key|token|secret|password|passwd|credential|api[_-]?key)")
PLACEHOLDER = re.compile(
    r"(?i)^(x+|0+|1+|changeme|example|your[_-]?(api[_-]?)?key([_-]?here)?|"
    r"placeholder|dummy|fake|test|<.*>|\.\.\.|redacted)$"
)
MIN_ENTROPY_LEN = 16
ENTROPY_THRESHOLD = 3.5


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


class SecretsChecker(BaseChecker):
    name = "hardcoded-secret"
    category = Category.SECURITY
    requires_ast = False  # regex pass works even on files that fail to parse

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        seen_spans = set()  # avoid double-reporting same line+text from regex + entropy

        # --- Pass 1: regex signatures, line by line ---
        for lineno, line in enumerate(ctx.lines, start=1):
            if self._is_ignored(line):
                continue
            for sig_name, pattern, severity in SIGNATURES:
                m = pattern.search(line)
                if not m:
                    continue
                # use the LAST capture group (the actual secret value) when a
                # pattern has multiple groups, e.g. credential assignment
                # captures both the key name and the value
                secret_text = m.groups()[-1] if m.groups() else m.group(0)
                if PLACEHOLDER.match(secret_text.strip()):
                    continue
                issues.append(
                    Issue(
                        checker=self.name,
                        category=self.category,
                        severity=severity,
                        file=ctx.path,
                        line=lineno,
                        message=f"Possible {sig_name} found: {self._mask(secret_text)}",
                    )
                )
                seen_spans.add((lineno, secret_text))

        # --- Pass 2: entropy scan on suspicious assignments (AST-based) ---
        if ctx.tree is not None:
            for node in ast.walk(ctx.tree):
                if isinstance(node, ast.Assign):
                    target_name = self._target_name(node)
                    if not target_name or not SUSPICIOUS_NAME.search(target_name):
                        continue
                    value = node.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        text = value.value
                        if (lineno := node.lineno) and any(t == text for _, t in seen_spans):
                            continue
                        if self._is_ignored(ctx.lines[node.lineno - 1]) if 0 < node.lineno <= len(ctx.lines) else False:
                            continue
                        if len(text) < MIN_ENTROPY_LEN or PLACEHOLDER.match(text.strip()):
                            continue
                        entropy = shannon_entropy(text)
                        if entropy >= ENTROPY_THRESHOLD:
                            issues.append(
                                Issue(
                                    checker=self.name,
                                    category=self.category,
                                    severity=Severity.WARNING,
                                    file=ctx.path,
                                    line=node.lineno,
                                    message=(
                                        f"High-entropy string assigned to '{target_name}' "
                                        f"(entropy={entropy:.2f}): {self._mask(text)}"
                                    ),
                                )
                            )
        return issues

    @staticmethod
    def _target_name(node: ast.Assign) -> str | None:
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
        return None

    @staticmethod
    def _is_ignored(line: str) -> bool:
        return "noqa" in line or "codelens: ignore" in line

    @staticmethod
    def _mask(secret: str) -> str:
        if len(secret) <= 8:
            return "*" * len(secret)
        return secret[:4] + "*" * (len(secret) - 8) + secret[-4:]
