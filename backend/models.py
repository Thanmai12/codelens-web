from __future__ import annotations
 
from typing import Optional
 
from pydantic import BaseModel, Field
 
 
class IssueModel(BaseModel):
    rule_id: str
    checker: str
    category: str  # "quality" | "security"
    severity: str  # "info" | "warning" | "error" | "critical"
    file: str
    line: int
    message: str
    snippet: str = ""
    column: int = 0
    why: str = ""
    fix: str = ""
 
 
class ScoreBreakdown(BaseModel):
    overall: int
    security: int
    quality: int
    complexity: int
 
 
class ScanSummary(BaseModel):
    total: int
    quality: int
    security: int
    critical: int
    error: int
    warning: int
    info: int
 
 
class ScanResult(BaseModel):
    summary: ScanSummary
    score: ScoreBreakdown
    issues: list[IssueModel] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    files_scanned: int
    files_analyzed: int
    files_with_errors: int
    files_list: list[str] = Field(default_factory=list)
    checkers_run: list[str] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
    debug: Optional[str] = None
 
 
class ScanError(BaseModel):
    error: str
    files_scanned: int = 0
    files_list: list[str] = Field(default_factory=list)
 
 
def empty_scan_result(debug: str) -> ScanResult:
    """The response when a zip was valid but contained no .py files."""
    return ScanResult(
        summary=ScanSummary(total=0, quality=0, security=0, critical=0, error=0, warning=0, info=0),
        score=ScoreBreakdown(overall=100, security=100, quality=100, complexity=100),
        issues=[],
        parse_errors=[],
        files_scanned=0,
        files_analyzed=0,
        files_with_errors=0,
        files_list=[],
        checkers_run=[],
        sources={},
        debug=debug,
    )
