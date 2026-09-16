"""Formats a list of Issues for human (text) or machine (JSON) consumption."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import List

from .checkers.base import Category, Issue, Severity

SEVERITY_COLOR = {
    Severity.INFO: "\033[36m",      # cyan
    Severity.WARNING: "\033[33m",   # yellow
    Severity.ERROR: "\033[31m",     # red
    Severity.CRITICAL: "\033[41m",  # red background
}
RESET = "\033[0m"
BOLD = "\033[1m"


def to_json(issues: List[Issue], errors: List[str]) -> str:
    payload = {
        "summary": _summary(issues),
        "issues": [
            {**asdict(i), "category": i.category.value, "severity": i.severity.value}
            for i in issues
        ],
        "parse_errors": errors,
    }
    return json.dumps(payload, indent=2)


def to_text(issues: List[Issue], errors: List[str], use_color: bool = True) -> str:
    lines: List[str] = []

    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if use_color else text

    quality = [i for i in issues if i.category == Category.QUALITY]
    security = [i for i in issues if i.category == Category.SECURITY]

    if security:
        lines.append(c(BOLD, "SECURITY"))
        for issue in sorted(security, key=lambda i: (i.file, i.line)):
            color = SEVERITY_COLOR.get(issue.severity, "")
            lines.append(
                f"  {issue.file}:{issue.line}  {c(color, f'[{issue.severity.value.upper()}]')} "
                f"({issue.checker}) {issue.message}"
            )
        lines.append("")

    if quality:
        lines.append(c(BOLD, "CODE QUALITY"))
        for issue in sorted(quality, key=lambda i: (i.file, i.line)):
            color = SEVERITY_COLOR.get(issue.severity, "")
            lines.append(
                f"  {issue.file}:{issue.line}  {c(color, f'[{issue.severity.value.upper()}]')} "
                f"({issue.checker}) {issue.message}"
            )
        lines.append("")

    if errors:
        lines.append(c(BOLD, "PARSE ERRORS"))
        for err in errors:
            lines.append(f"  {err}")
        lines.append("")

    summary = _summary(issues)
    lines.append(c(BOLD, "SUMMARY"))
    lines.append(
        f"  {summary['total']} issues  "
        f"({summary['security']} security, {summary['quality']} quality)  "
        f"in files scanned; {len(errors)} file(s) failed to parse."
    )
    if summary["critical"]:
        lines.append(c(SEVERITY_COLOR[Severity.CRITICAL], f"  {summary['critical']} CRITICAL findings — review immediately."))

    return "\n".join(lines)


def _summary(issues: List[Issue]) -> dict:
    return {
        "total": len(issues),
        "quality": sum(1 for i in issues if i.category == Category.QUALITY),
        "security": sum(1 for i in issues if i.category == Category.SECURITY),
        "critical": sum(1 for i in issues if i.severity == Severity.CRITICAL),
        "error": sum(1 for i in issues if i.severity == Severity.ERROR),
        "warning": sum(1 for i in issues if i.severity == Severity.WARNING),
        "info": sum(1 for i in issues if i.severity == Severity.INFO),
    }
