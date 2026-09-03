"""First-layer research QA checklist.

v5 stored each check as a single string such as ``"FAIL: ..."`` and then
recovered the status with ``str.startswith("FAIL")``. Any change to the wording
silently broke the roll-up. v6 stores an explicit status column and a separate
message column per check, so the roll-up is computed from data rather than from
prose.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from aicf_config import ACTION_TERMS
from aicf_framework import (
    build_row_evidence,
    contains_any,
    has_decisive_claim,
    number_supported,
    quoted_numbers,
)

PASS, FAIL, REVIEW, NA = "PASS", "FAIL", "REVIEW", "N/A"

CHECKS: List[tuple[str, str]] = [
    ("numbers_quoted_correct", "Numbers quoted are traceable to the evidence"),
    ("bases_correct", "Base sizes are stated"),
    ("sample_filters_correct", "Sample filters and audience wording are supported"),
    ("charts_support_statement", "Charts or tables support the statement"),
    ("crosstabs_support_claim", "Cross-tabs support the claim"),
    ("no_selective_reporting", "No selective or directional reporting"),
    ("no_ignored_contradiction", "No contradictory data ignored within the datapoint"),
    ("no_conflicting_kpis", "No conflicting KPIs"),
    ("terminology_consistent", "Terminology is consistent"),
    ("recommendations_align", "Recommendations align with findings"),
    ("no_cross_report_contradiction", "No contradiction elsewhere in the report"),
]

CHECK_KEYS = [key for key, _ in CHECKS]

FILTER_TERMS = [
    "among", "filtered", "filter", "only", "segment", "male", "female",
    "top box", "non-top box", "wave", "users", "non-users", "aware",
]


def _result(status: str, message: str) -> Dict[str, str]:
    return {"status": status, "message": message}


def row_qa_checks(row: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    evidence = build_row_evidence(row)
    insight = str(row.get("insight_text", "") or "")
    support = evidence.combined
    decisive = has_decisive_claim(insight)
    contradicted = evidence.contradicted
    unmatched = evidence.unmatched
    verified = evidence.verified

    out: Dict[str, Dict[str, str]] = {}

    numbers = quoted_numbers(insight)
    unsupported = [n for n in numbers if not number_supported(n, support)]
    if not numbers:
        out["numbers_quoted_correct"] = _result(NA, "The insight quotes no figures.")
    elif unsupported:
        out["numbers_quoted_correct"] = _result(
            FAIL, "Figures not found in the matched evidence: " + ", ".join(unsupported[:5])
        )
    else:
        out["numbers_quoted_correct"] = _result(PASS, "Every quoted figure appears in the matched evidence.")

    if contains_any(support, ["n=", "base=", "base:", "respondents", "sample size"]):
        out["bases_correct"] = _result(PASS, "A base or sample reference is visible for this row.")
    else:
        out["bases_correct"] = _result(REVIEW, "No base or sample reference is visible for this row.")

    used_filters = [term for term in FILTER_TERMS if term in insight.lower()]
    if not used_filters:
        out["sample_filters_correct"] = _result(NA, "The insight names no sub-audience.")
    elif all(term in support.lower() for term in used_filters[:3]):
        out["sample_filters_correct"] = _result(PASS, "Audience wording is reflected in the evidence.")
    else:
        out["sample_filters_correct"] = _result(
            FAIL, "Audience or filter wording is used but not confirmed in the evidence: " + ", ".join(used_filters[:3])
        )

    if contradicted:
        out["charts_support_statement"] = _result(
            FAIL, evidence.chart_reason or evidence.cross_source or "Source data contradicts the statement."
        )
    elif verified:
        out["charts_support_statement"] = _result(PASS, evidence.chart_reason or evidence.cross_source)
    elif decisive:
        out["charts_support_statement"] = _result(
            FAIL, "A ranked or superlative claim was not matched to any chart or table."
        )
    else:
        out["charts_support_statement"] = _result(REVIEW, "No chart or table was matched; verify manually.")

    if not decisive:
        out["crosstabs_support_claim"] = _result(NA, "No comparative claim requiring a cross-tab.")
    elif unmatched:
        out["crosstabs_support_claim"] = _result(FAIL, "No matching cross-tab metric was found for this comparative claim.")
    elif verified:
        out["crosstabs_support_claim"] = _result(PASS, "A comparative table metric was matched.")
    else:
        out["crosstabs_support_claim"] = _result(REVIEW, "Comparative support is partial; confirm against source tables.")

    if contradicted:
        out["no_selective_reporting"] = _result(
            FAIL, "The claim points one way while the matched metric points another."
        )
    elif decisive and not verified:
        out["no_selective_reporting"] = _result(REVIEW, "A directional claim has not been checked against all options.")
    else:
        out["no_selective_reporting"] = _result(PASS, "No selective reporting detected.")

    out["no_ignored_contradiction"] = (
        _result(FAIL, "Contradictory values exist inside the matched datapoint.")
        if contradicted
        else _result(PASS, "No ignored contradiction inside the matched datapoint.")
    )

    if contradicted:
        out["no_conflicting_kpis"] = _result(FAIL, "Conflicting KPI evidence detected.")
    elif decisive and unmatched:
        out["no_conflicting_kpis"] = _result(REVIEW, "The decisive claim has no validated KPI to compare against.")
    else:
        out["no_conflicting_kpis"] = _result(PASS, "No conflicting KPI evidence detected.")

    if "no exact claimed option" in evidence.cross_source.lower():
        out["terminology_consistent"] = _result(
            FAIL, "The option named in the insight does not match any label in the source tables."
        )
    else:
        out["terminology_consistent"] = _result(PASS, "Naming is consistent enough for matching.")

    recommends = contains_any(insight, ACTION_TERMS)
    if not recommends:
        out["recommendations_align"] = _result(NA, "The insight makes no recommendation.")
    elif contradicted:
        out["recommendations_align"] = _result(FAIL, "The recommendation rests on a contradicted finding.")
    elif not verified:
        out["recommendations_align"] = _result(REVIEW, "The recommendation rests on unverified evidence.")
    else:
        out["recommendations_align"] = _result(PASS, "The recommendation follows the verified finding.")

    out["no_cross_report_contradiction"] = _result(PASS, "No cross-report contradiction detected.")
    return out


def add_qa_columns(report: pd.DataFrame) -> pd.DataFrame:
    """Attach per-check status/message columns and an overall roll-up."""
    if report.empty:
        return report

    enriched = report.reset_index(drop=True).copy()
    all_checks = [row_qa_checks(row.to_dict()) for _, row in enriched.iterrows()]

    # Cross-report pass: a theme contradicted anywhere flags its siblings.
    contradicted_themes = {
        str(enriched.at[idx, "theme"]).strip().lower()
        for idx, checks in enumerate(all_checks)
        if checks["no_ignored_contradiction"]["status"] == FAIL
    }
    contradicted_themes.discard("")
    contradicted_themes.discard("not specified")

    for idx, checks in enumerate(all_checks):
        theme = str(enriched.at[idx, "theme"]).strip().lower()
        if checks["no_ignored_contradiction"]["status"] == FAIL:
            checks["no_cross_report_contradiction"] = _result(
                FAIL, "This row carries a contradiction that affects the wider report story."
            )
        elif theme in contradicted_themes:
            checks["no_cross_report_contradiction"] = _result(
                REVIEW, "Another row on the same theme is contradicted; check the report for consistency."
            )

    for key, label in CHECKS:
        enriched[f"qa_{key}_status"] = [checks[key]["status"] for checks in all_checks]
        enriched[f"qa_{key}_note"] = [f"{label}: {checks[key]['message']}" for checks in all_checks]

    statuses, summaries = [], []
    for checks in all_checks:
        values = [checks[key]["status"] for key in CHECK_KEYS]
        fails = values.count(FAIL)
        reviews = values.count(REVIEW)
        if fails:
            statuses.append(FAIL)
            summaries.append(f"{fails} check(s) failed. Resolve these before relying on the ICI score.")
        elif reviews:
            statuses.append(REVIEW)
            summaries.append(f"{reviews} check(s) need analyst confirmation.")
        else:
            statuses.append(PASS)
            summaries.append("All applicable first-layer checks passed.")
    enriched["qa_overall_status"] = statuses
    enriched["qa_overall_note"] = summaries
    return enriched
