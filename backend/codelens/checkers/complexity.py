from __future__ import annotations

import ast
from typing import List

from .base import BaseChecker, Category, FileContext, Issue, Severity

DEFAULT_THRESHOLD = 10


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.complexity = 1

    def visit_If(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node):
        self.generic_visit(node)  # not a decision point, just bookkeeping

    def visit_BoolOp(self, node):
        # each extra operand after the first adds a branch
        self.complexity += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.complexity += len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node):
        self.complexity += len(node.cases)
        self.generic_visit(node)


class ComplexityChecker(BaseChecker):
    name = "complexity"
    category = Category.QUALITY

    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visitor = ComplexityVisitor()
                visitor.visit(node)
                score = visitor.complexity
                if score > self.threshold:
                    severity = Severity.ERROR if score > self.threshold * 2 else Severity.WARNING
                    issues.append(
                        Issue(
                            checker=self.name,
                            category=self.category,
                            severity=severity,
                            file=ctx.path,
                            line=node.lineno,
                            message=(
                                f"Function '{node.name}' has cyclomatic complexity "
                                f"{score} (threshold: {self.threshold})"
                            ),
                        )
                    )
        return issues
