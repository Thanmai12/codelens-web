"""
Additional code-quality checkers: deep nesting, too many parameters, long
files, large classes, mutable default arguments, and overly broad exception
handling. Grouped in one file (rather than one file per checker) since each
is small and they share the "quality" category — splitting further would
add navigation overhead without real benefit.
"""

from __future__ import annotations

import ast
from typing import List

from .base import BaseChecker, Category, FileContext, Issue, Severity


class DeepNestingChecker(BaseChecker):
    name = "deep-nesting"
    category = Category.QUALITY

    def __init__(self, threshold: int = 4):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        NESTING_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)

        def walk(node, depth, reported_funcs):
            for child in ast.iter_child_nodes(node):
                child_depth = depth + 1 if isinstance(child, NESTING_NODES) else depth
                if isinstance(child, NESTING_NODES) and child_depth > self.threshold:
                    func_key = id(func_node)
                    if func_key not in reported_funcs:
                        reported_funcs.add(func_key)
                        issues.append(Issue(
                            checker=self.name, category=self.category, severity=Severity.WARNING,
                            file=ctx.path, line=child.lineno,
                            message=f"Nesting depth {child_depth} exceeds threshold {self.threshold} in '{func_node.name}'",
                        ))
                walk(child, child_depth, reported_funcs)

        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_node = node
                walk(node, 0, set())
        return issues


class TooManyParametersChecker(BaseChecker):
    name = "too-many-parameters"
    category = Category.QUALITY

    def __init__(self, threshold: int = 6):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
                # self/cls don't count as "real" parameters a caller supplies
                names = [n for n in names if n not in ("self", "cls")]
                if len(names) > self.threshold:
                    issues.append(Issue(
                        checker=self.name, category=self.category, severity=Severity.WARNING,
                        file=ctx.path, line=node.lineno,
                        message=f"Function '{node.name}' has {len(names)} parameters (threshold: {self.threshold})",
                    ))
        return issues


class LongFileChecker(BaseChecker):
    name = "long-file"
    category = Category.QUALITY
    requires_ast = False  # a file-level line count needs no AST at all

    def __init__(self, threshold: int = 500):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        length = len(ctx.lines)
        if length > self.threshold:
            return [Issue(
                checker=self.name, category=self.category, severity=Severity.WARNING,
                file=ctx.path, line=1,
                message=f"File is {length} lines long (threshold: {self.threshold})",
            )]
        return []


class LargeClassChecker(BaseChecker):
    name = "large-class"
    category = Category.QUALITY

    def __init__(self, threshold: int = 300):
        self.threshold = threshold

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.ClassDef):
                end = getattr(node, "end_lineno", None)
                if end is None:
                    continue
                length = end - node.lineno + 1
                if length > self.threshold:
                    issues.append(Issue(
                        checker=self.name, category=self.category, severity=Severity.WARNING,
                        file=ctx.path, line=node.lineno,
                        message=f"Class '{node.name}' is {length} lines long (threshold: {self.threshold})",
                    ))
        return issues


class MutableDefaultArgChecker(BaseChecker):
    name = "mutable-default-arg"
    category = Category.QUALITY

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in list(node.args.defaults) + list(node.args.kw_defaults):
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        issues.append(Issue(
                            checker=self.name, category=self.category, severity=Severity.ERROR,
                            file=ctx.path, line=node.lineno,
                            message=f"Function '{node.name}' uses a mutable default argument — it's shared across all calls, not recreated each time",
                        ))
                        break  # one issue per function is enough
        return issues


class BroadExceptionChecker(BaseChecker):
    name = "broad-exception"
    category = Category.QUALITY

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.ExceptHandler):
                is_bare = node.type is None
                is_broad = isinstance(node.type, ast.Name) and node.type.id == "Exception"
                if not (is_bare or is_broad):
                    continue
                swallowed = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                kind = "bare except:" if is_bare else "except Exception:"
                if swallowed:
                    msg = f"{kind} silently swallows the error with only 'pass' — failures disappear with no trace"
                    severity = Severity.ERROR
                else:
                    msg = f"{kind} catches every exception type, including ones the code likely isn't prepared to handle"
                    severity = Severity.WARNING
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=severity,
                    file=ctx.path, line=node.lineno, message=msg,
                ))
        return issues
