"""
Quality scoring.

Turns a list of Issues into three 0-100 sub-scores (security, quality,
complexity) plus an overall score. The formula is deliberately simple and
explainable: each dimension starts at 100 and loses points per issue found
in it, weighted by severity. This is not a statistically validated model —
it's a transparent, defensible heuristic, which is the right trade-off for
a tool whose whole point is explainability.

Scoring formula (documented here so it can be explained in an interview):

    score(dimension) = max(0, 100 - sum(penalty[severity] for each issue in dimension))

    penalty = {critical: 20, error: 10, warning: 5, info: 2}

Dimensions:
    - security:   all issues from the 'hardcoded-secret' checker
    - complexity: all issues from the 'complexity' checker specifically
                  (kept separate from other quality issues because
                  cyclomatic complexity is a distinct, well-known metric)
    - quality:    all other quality-category issues (long-function,
                  duplicate-code, unused-imports)

Overall score is the unweighted average of the three sub-scores.
"""

from __future__ import annotations

from typing import Iterable

PENALTY = {
    "critical": 20,
    "error": 10,
    "warning": 5,
    "info": 2,
}


def _score_for(issues: list) -> int:
    penalty_total = sum(PENALTY.get(i["severity"], 0) for i in issues)
    return max(0, 100 - penalty_total)


def compute_scores(issues: Iterable[dict]) -> dict:
    """
    `issues` is the list of issue dicts already produced by the API
    (each with "checker", "category", "severity"). Returns:
        {"overall": int, "security": int, "quality": int, "complexity": int}
    """
    issues = list(issues)

    security_issues = [i for i in issues if i["category"] == "security"]
    complexity_issues = [i for i in issues if i["checker"] == "complexity"]
    quality_issues = [
        i for i in issues
        if i["category"] == "quality" and i["checker"] != "complexity"
    ]

    security = _score_for(security_issues)
    complexity = _score_for(complexity_issues)
    quality = _score_for(quality_issues)
    overall = round((security + complexity + quality) / 3)

    return {
        "overall": overall,
        "security": security,
        "quality": quality,
        "complexity": complexity,
    }
