"""
The shared scanning engine. Owns file discovery + parsing; knows nothing
about what any individual checker looks for. Checkers register themselves
and the engine calls `check()` on each for every file, then `finalize()`
once at the end for checkers that need a whole-codebase view.
"""

from __future__ import annotations

import ast
import os
from typing import Iterable, List

from .checkers.base import BaseChecker, FileContext, Issue

DEFAULT_EXCLUDES = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache", "build", "dist",
    ".eggs",
}


class Engine:
    def __init__(self, checkers: List[BaseChecker], excludes: Iterable[str] | None = None):
        self.checkers = checkers
        self.excludes = set(excludes) if excludes else set(DEFAULT_EXCLUDES)

    def discover_files(self, root: str) -> List[str]:
        matches = []
        if os.path.isfile(root):
            if root.endswith(".py"):
                matches.append(root)
            return matches

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.excludes and not d.startswith(".")]
            for fname in filenames:
                if fname.endswith(".py"):
                    matches.append(os.path.join(dirpath, fname))
        return sorted(matches)

    def scan_file(self, path: str) -> tuple[List[Issue], str | None]:
        """Returns (issues, parse_error). parse_error is None on success."""
        issues: List[Issue] = []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError as e:
            return [], f"Could not read file: {e}"

        lines = source.splitlines()
        tree = None
        parse_error = None
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as e:
            parse_error = f"Syntax error: {e.msg} (line {e.lineno})"

        ctx = FileContext(path=path, source=source, lines=lines, tree=tree)

        for checker in self.checkers:
            if checker.requires_ast and tree is None:
                continue
            try:
                issues.extend(checker.check(ctx))
            except Exception as e:  # a buggy checker shouldn't crash the whole scan
                issues.append(
                    Issue(
                        checker=checker.name,
                        category=checker.category,
                        severity="warning",  # type: ignore[arg-type]
                        file=path,
                        line=0,
                        message=f"Checker '{checker.name}' crashed on this file: {e}",
                    )
                )
        return issues, parse_error

    def scan(self, root: str) -> tuple[List[Issue], List[str]]:
        """Returns (all_issues, parse_errors_as_strings)."""
        all_issues: List[Issue] = []
        errors: List[str] = []

        for path in self.discover_files(root):
            issues, parse_error = self.scan_file(path)
            all_issues.extend(issues)
            if parse_error:
                errors.append(f"{path}: {parse_error}")

        for checker in self.checkers:
            all_issues.extend(checker.finalize())

        return all_issues, errors
