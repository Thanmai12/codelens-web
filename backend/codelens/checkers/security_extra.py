from __future__ import annotations

import ast
from typing import List

from .base import BaseChecker, Category, FileContext, Issue, Severity


class DangerousExecChecker(BaseChecker):
    name = "dangerous-exec"
    category = Category.SECURITY

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=Severity.ERROR,
                    file=ctx.path, line=node.lineno,
                    message=f"Use of {node.func.id}() can execute arbitrary code if the input is not fully trusted",
                ))
        return issues


class UnsafeSubprocessChecker(BaseChecker):
    name = "unsafe-subprocess"
    category = Category.SECURITY
    SUBPROCESS_FUNCS = {"run", "call", "check_call", "check_output", "Popen"}

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_subprocess_call = (
                isinstance(func, ast.Attribute) and func.attr in self.SUBPROCESS_FUNCS
            ) or (
                isinstance(func, ast.Name) and func.id in self.SUBPROCESS_FUNCS
            )
            if not is_subprocess_call:
                continue
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    issues.append(Issue(
                        checker=self.name, category=self.category, severity=Severity.ERROR,
                        file=ctx.path, line=node.lineno,
                        message="subprocess call with shell=True can allow shell injection if any part of the command comes from untrusted input",
                    ))
        return issues


def _from_import_sources(tree: ast.AST) -> dict:
    """Map local_name -> module for every `from module import name [as local]`
    in the file, so bare-name calls (e.g. `md5(x)` after `from hashlib import
    md5`) can be verified against their real source instead of guessed at by
    name alone -- `load`/`loads` in particular are used by json, yaml, and
    pickle alike, so guessing by name would false-positive constantly.
    """
    sources = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                sources[local] = node.module
    return sources


class WeakCryptoChecker(BaseChecker):
    name = "weak-crypto"
    category = Category.SECURITY
    WEAK_HASHES = {"md5", "sha1"}

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        import_sources = _from_import_sources(ctx.tree)
        for node in ast.walk(ctx.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = None
            if isinstance(func, ast.Attribute) and func.attr in self.WEAK_HASHES:
                # module.md5(...) -- flag regardless of module name, since
                # e.g. hashlib.md5 is the overwhelmingly common shape and a
                # module actually named otherwise but exposing .md5()/.sha1()
                # is a vanishingly rare false-positive source
                name = func.attr
            elif (isinstance(func, ast.Name) and func.id in self.WEAK_HASHES
                  and import_sources.get(func.id) == "hashlib"):
                # bare md5(...)/sha1(...) -- only flag if it was actually
                # imported from hashlib, not some unrelated same-named function
                name = func.id
            if name:
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=Severity.WARNING,
                    file=ctx.path, line=node.lineno,
                    message=f"{name.upper()} is cryptographically broken — fine for non-security checksums, but not for passwords, signatures, or integrity checks",
                ))
        return issues


class UnsafeDeserializationChecker(BaseChecker):
    name = "unsafe-deserialization"
    category = Category.SECURITY

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        import_sources = _from_import_sources(ctx.tree)
        for node in ast.walk(ctx.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            is_pickle_load = (
                isinstance(func, ast.Attribute) and func.attr in ("load", "loads")
                and isinstance(func.value, ast.Name) and func.value.id == "pickle"
            ) or (
                isinstance(func, ast.Name) and func.id in ("load", "loads")
                and import_sources.get(func.id) == "pickle"
            )
            if is_pickle_load:
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=Severity.ERROR,
                    file=ctx.path, line=node.lineno,
                    message="pickle can execute arbitrary code during deserialization — never unpickle data from an untrusted source",
                ))
        return issues


class SqlInjectionChecker(BaseChecker):
    name = "sql-injection-risk"
    category = Category.SECURITY
    EXECUTE_METHODS = {"execute", "executemany"}

    def check(self, ctx: FileContext) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(ctx.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.EXECUTE_METHODS):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            # String concatenation (BinOp with Add) or an f-string (JoinedStr)
            # passed straight into .execute(...) is the classic injection
            # shape. This is a heuristic, not proof -- worded as a risk.
            if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=Severity.WARNING,
                    file=ctx.path, line=node.lineno,
                    message="Potential SQL injection risk: query string is built with concatenation instead of parameters",
                ))
            elif isinstance(arg, ast.JoinedStr):
                issues.append(Issue(
                    checker=self.name, category=self.category, severity=Severity.WARNING,
                    file=ctx.path, line=node.lineno,
                    message="Potential SQL injection risk: query string is an f-string instead of using parameterized placeholders",
                ))
        return issues
