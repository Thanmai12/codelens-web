"""
Cross-file duplicate code detection.

Strategy: for every function/method body (min N lines, configurable),
normalize the source (strip comments/whitespace, collapse variable-like
identifiers are NOT renamed -- this is a straightforward textual/structural
match, not a full clone-detection algorithm) and hash it. Bodies sharing a
hash across two or more locations are reported as duplicates.

This is a `finalize`-style checker: `check()` just collects candidate
blocks per file, and `finalize()` (called once after all files are scanned)
does the cross-file comparison and emits Issues.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from typing import Dict, List, Tuple

from .base import BaseChecker, Category, FileContext, Issue, Severity

DEFAULT_MIN_LINES = 5


class DuplicateCodeChecker(BaseChecker):
    name = "duplicate-code"
    category = Category.QUALITY

    def __init__(self, min_lines: int = DEFAULT_MIN_LINES):
        self.min_lines = min_lines
        # hash -> list of (file, lineno)
        self._seen: Dict[str, List[Tuple[str, int]]] = defaultdict(list)

    def check(self, ctx: FileContext) -> List[Issue]:
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", None)
                if end is None:
                    continue
                length = end - node.lineno + 1
                if length < self.min_lines:
                    continue
                normalized = self._normalize_body(node)
                if not normalized:
                    continue
                digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                self._seen[digest].append((ctx.path, node.lineno))
        return []  # duplicates only make sense once every file has been seen

    def finalize(self) -> List[Issue]:
        issues: List[Issue] = []
        for digest, locations in self._seen.items():
            if len(locations) < 2:
                continue
            first_file, first_line = locations[0]
            others = ", ".join(f"{f}:{l}" for f, l in locations[1:])
            issues.append(
                Issue(
                    checker=self.name,
                    category=self.category,
                    severity=Severity.WARNING,
                    file=first_file,
                    line=first_line,
                    message=(
                        f"Duplicate function body also found at: {others} "
                        f"({len(locations)} occurrences)"
                    ),
                )
            )
        return issues

    @staticmethod
    def _normalize_body(node: ast.AST) -> str:
        """
        Structural normalization: dump the AST body (skipping the function
        signature/docstring/decorators) so formatting, comments and variable
        renames of the *same* structure still don't collide with genuinely
        different logic. We deliberately keep identifier names as-is; this
        catches copy-paste duplication, not semantic equivalence.
        """
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(
            getattr(body[0], "value", None), ast.Constant
        ) and isinstance(body[0].value.value, str):
            body = body[1:]  # drop docstring
        if not body:
            return ""
        try:
            return "\n".join(ast.dump(stmt) for stmt in body)
        except Exception:
            return ""
