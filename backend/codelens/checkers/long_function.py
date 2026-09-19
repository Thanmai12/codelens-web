from __future__ import annotations

import ast
from typing import List

from .base import BaseChecker, Category, FileContext, Issue, Severity

DEFAULT_THRESHOLD = 50


class LongFunctionChecker(BaseChecker):
    name = "long-function"
    category = Category.QUALITY

    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", None)
                if end is None:
                    continue
                length = end - node.lineno + 1
                if length > self.threshold:
                    severity = Severity.WARNING if length <= self.threshold * 2 else Severity.ERROR
                    issues.append(
                        Issue(
                            checker=self.name,
                            category=self.category,
                            severity=severity,
                            file=ctx.path,
                            line=node.lineno,
                            message=(
                                f"Function '{node.name}' is {length} lines long "
                                f"(threshold: {self.threshold})"
                            ),
                        )
                    )
        return issues
