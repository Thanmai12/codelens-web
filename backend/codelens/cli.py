"""
CodeLens CLI.

Usage:
    codelens scan <path> [--format text|json] [--fail-on warning|error|critical]
                         [--only quality|security] [--complexity-threshold N]
                         [--long-function-threshold N] [--min-duplicate-lines N]
"""

from __future__ import annotations

import argparse
import sys

from .checkers.complexity import ComplexityChecker, DEFAULT_THRESHOLD as COMPLEXITY_DEFAULT
from .checkers.duplicate_code import DuplicateCodeChecker, DEFAULT_MIN_LINES
from .checkers.long_function import LongFunctionChecker, DEFAULT_THRESHOLD as LONG_FN_DEFAULT
from .checkers.secrets import SecretsChecker
from .checkers.unused_imports import UnusedImportsChecker
from .checkers.base import Category, Severity
from .engine import Engine
from .report import to_json, to_text

SEVERITY_ORDER = [Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codelens", description="Static analysis for Python: quality + secrets.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a file or directory")
    scan.add_argument("path", help="File or directory to scan")
    scan.add_argument("--format", choices=["text", "json"], default="text")
    scan.add_argument("--no-color", action="store_true", help="Disable ANSI colors in text output")
    scan.add_argument("--only", choices=["quality", "security"], default=None, help="Restrict to one category")
    scan.add_argument("--fail-on", choices=[s.value for s in SEVERITY_ORDER], default=None,
                       help="Exit non-zero if any issue at or above this severity is found (for CI use)")
    scan.add_argument("--complexity-threshold", type=int, default=COMPLEXITY_DEFAULT)
    scan.add_argument("--long-function-threshold", type=int, default=LONG_FN_DEFAULT)
    scan.add_argument("--min-duplicate-lines", type=int, default=DEFAULT_MIN_LINES)
    scan.add_argument("--exclude", action="append", default=[], help="Directory name to exclude (repeatable)")

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        return _run_scan(args)

    parser.print_help()
    return 1


def _run_scan(args) -> int:
    checkers = [
        ComplexityChecker(threshold=args.complexity_threshold),
        LongFunctionChecker(threshold=args.long_function_threshold),
        DuplicateCodeChecker(min_lines=args.min_duplicate_lines),
        UnusedImportsChecker(),
        SecretsChecker(),
    ]

    if args.only:
        want = Category.QUALITY if args.only == "quality" else Category.SECURITY
        checkers = [c for c in checkers if c.category == want]

    engine = Engine(checkers, excludes=set(args.exclude) or None)
    issues, errors = engine.scan(args.path)

    if args.format == "json":
        print(to_json(issues, errors))
    else:
        print(to_text(issues, errors, use_color=not args.no_color))

    if args.fail_on:
        threshold_index = SEVERITY_ORDER.index(Severity(args.fail_on))
        for issue in issues:
            if SEVERITY_ORDER.index(issue.severity) >= threshold_index:
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
