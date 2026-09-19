from __future__ import annotations

import ast
from typing import List, Set

from .base import BaseChecker, Category, FileContext, Issue, Severity


class _UsageCollector(ast.NodeVisitor):
    def __init__(self):
        self.used: Set[str] = set()

    def visit_Name(self, node):
        self.used.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # for `module.attr`, the root name is what matters for import usage
        self.generic_visit(node)


class UnusedImportsChecker(BaseChecker):
    name = "unused-imports"
    category = Category.QUALITY

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []

        # Skip files that re-export via __all__; too easy to false-positive.
        exported = self._collect_dunder_all(ctx.tree)

        bindings = {}  # local_name -> (lineno, display_name)
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    bindings[local] = (node.lineno, alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    bindings[local] = (node.lineno, alias.asname or alias.name)

        collector = _UsageCollector()
        collector.visit(ctx.tree)

        for local, (lineno, display) in bindings.items():
            if local in exported:
                continue
            if local not in collector.used:
                # a name only "used" by being imported still counts as bound
                # once here, so absence from `used` (which walked the whole
                # tree including the import line itself via Name nodes in
                # `as` aliases is not applicable) means genuinely unused.
                if self._is_ignored(ctx, lineno):
                    continue
                issues.append(
                    Issue(
                        checker=self.name,
                        category=self.category,
                        severity=Severity.INFO,
                        file=ctx.path,
                        line=lineno,
                        message=f"Unused import '{display}'",
                    )
                )
        return issues

    @staticmethod
    def _collect_dunder_all(tree: ast.AST) -> Set[str]:
        names: Set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "__all__" in targets and isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            names.add(elt.value)
        return names

    @staticmethod
    def _is_ignored(ctx: FileContext, lineno: int) -> bool:
        if 0 < lineno <= len(ctx.lines):
            line = ctx.lines[lineno - 1]
            return "noqa" in line or "codelens: ignore" in line
        return False
