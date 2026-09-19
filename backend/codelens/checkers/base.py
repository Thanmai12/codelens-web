from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"  # reserved for secrets


class Category(str, Enum):
    QUALITY = "quality"
    SECURITY = "security"


@dataclass
class Issue:
    checker: str            # e.g. "complexity", "hardcoded-secret"
    category: Category
    severity: Severity
    file: str
    line: int
    message: str
    snippet: str = ""       # optional short code excerpt
    column: int = 0


@dataclass
class FileContext:
    """Everything a checker needs about one source file."""
    path: str
    source: str
    lines: List[str] = field(default_factory=list)
    tree: ast.AST | None = None  # None if the file failed to parse


class BaseChecker:
    """Subclass this and implement `check` to add a new rule."""

    name: str = "base"
    category: Category = Category.QUALITY
    #: whether this checker needs a valid AST (skip on parse errors)
    requires_ast: bool = True

    def check(self, ctx: FileContext) -> List[Issue]:
        raise NotImplementedError

    def finalize(self) -> List[Issue]:
        """
        Optional second pass, called once after every file has been through
        `check()`. Used by checkers that need a whole-codebase view (e.g.
        duplicate-code detection, which compares blocks across files).
        Default: no additional issues.
        """
        return []
