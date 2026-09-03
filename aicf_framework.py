"""AICF scoring engine (v6, rebuilt).

What changed versus v5 and why
------------------------------
v5 scored an insight using a single concatenated blob that mixed the insight,
its own evidence note, the study-level file summary, and every sidebar
selection. Three consequences followed:

1. Selecting a study type in the sidebar raised the score of every insight,
   because context detectors such as ``satisfaction_report_context`` matched the
   dropdown value itself and then applied ``max(score, 4)`` floors.
2. app.py appended one global file-summary string to every row's evidence note,
   so every insight inherited identical "evidence" and scores stopped
   discriminating between well- and poorly-supported claims.
3. Study-specific vocabulary was hardcoded into generic explanation text, so
   unrelated studies received explanations naming a previous project's brand.

v6 keeps the seven dimensions, the weights and the ICI arithmetic exactly as
published, and changes only how the inputs are derived:

* Evidence is read from the row's own fields only (``evidence_note``,
  ``quantitative_metrics_validated``, ``cross_source_validation`` and the
  chart/analysis validator outputs for that row).
* Study context selects which lexicon to apply. It never adds points.
* Evidence Strength is bounded by a documented evidence tier.
* Every adjustment is recorded in ``score_trace`` so a reviewer can audit the
  number rather than trust it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from aicf_config import (
    ACTION_TERMS,
    CAUSAL_METHOD_TERMS,
    CAUSAL_TERMS,
    COMPARATIVE_EVIDENCE_TERMS,
    CONTRADICTORY_EVIDENCE_TERMS,
    DECISIVE_CLAIM_TERMS,
    DIMENSION_MAX_POINTS,
    DIMENSIONS,
    EVIDENCE_TIERS,
    HEDGE_TERMS,
    ICI_HIGH_THRESHOLD,
    ICI_MEDIUM_THRESHOLD,
    MANUAL_SCORE_COLUMNS,
    OVERCLAIM_TERMS,
    REQUIRED_COLUMNS,
    STUDY_TYPE_KEYWORDS,
    TIER_TO_EVIDENCE_SCORE,
    canonical,
)

__all__ = [
    "DIMENSIONS",
    "REQUIRED_COLUMNS",
    "MANUAL_SCORE_COLUMNS",
    "AICFResult",
    "score_insight",
    "validate_columns",
    "ici_score",
    "ici_classification",
]


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

def is_missing(value: object) -> bool:
    text = str(value or "").strip()
    return text == "" or text.lower() in {"nan", "none", "null", "not specified"}


def clean_context(value: object, fallback: str = "Not specified") -> str:
    text = str(value or "").strip()
    return fallback if is_missing(text) else text


def contains_any(text: str, words: List[str]) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in words)


def clamp_score(score: int) -> int:
    return max(1, min(5, int(score)))


NUMBER_PATTERN = re.compile(
    r"(\b\d+(?:\.\d+)?\s*%"
    r"|\b\d+(?:\.\d+)?\s*/\s*(?:5|7|10|100)"
    r"|\b(?:n|base)\s*=\s*\d+"
    r"|\b\d+(?:\.\d+)?\s*(?:points?|pts|index|mean|score))",
    re.I,
)


def has_numeric_evidence(text: str) -> bool:
    return bool(NUMBER_PATTERN.search(str(text or "")))


def quoted_numbers(text: object) -> List[str]:
    """Return normalised numeric tokens quoted in the text."""
    return [re.sub(r"\s+", "", match.group(0)).lower() for match in NUMBER_PATTERN.finditer(str(text or ""))]


def number_supported(number_text: str, support_text: str) -> bool:
    """Check whether a quoted number appears in the supporting evidence.

    v5 used a plain substring test, so "12%" matched inside "112%" and produced
    false PASS results. v6 anchors the match on a digit boundary.
    """
    numeric = re.sub(r"[^0-9.]", "", number_text)
    if not numeric:
        return False
    haystack = re.sub(r"\s+", "", str(support_text or "").lower())
    try:
        value = float(numeric)
    except ValueError:
        return False

    candidates = {numeric, f"{value:g}", f"{value:.0f}", f"{value:.1f}"}
    if value > 1:
        candidates |= {f"{value / 100:.3f}".rstrip("0"), f"{value / 100:.2f}"}
    for candidate in candidates:
        if not candidate:
            continue
        pattern = r"(?<![0-9.])" + re.escape(candidate) + r"(?![0-9])"
        if re.search(pattern, haystack):
            return True
    return False


# ---------------------------------------------------------------------------
# Row-level evidence extraction - the key behavioural change
# ---------------------------------------------------------------------------

@dataclass
class RowEvidence:
    """Everything known about THIS insight's support, and nothing else."""

    note: str = ""
    matched_metrics: str = ""
    cross_source: str = ""
    chart_status: str = ""
    chart_reason: str = ""
    analysis_status: str = ""
    analysis_reason: str = ""
    context_alignment: int = 0
    trace: List[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        return " ".join(
            part
            for part in [self.note, self.matched_metrics, self.cross_source, self.chart_reason, self.analysis_reason]
            if part
        ).strip()

    @property
    def verified(self) -> bool:
        """True when an independent source confirmed a number for this row."""
        statuses = {self.chart_status.upper(), self.analysis_status.upper()}
        if "PASS" in statuses:
            return True
        return self.cross_source.lower().startswith("supported:")

    @property
    def contradicted(self) -> bool:
        statuses = {self.chart_status.upper(), self.analysis_status.upper()}
        if "FAIL" in statuses:
            return True
        return contains_any(
            f"{self.cross_source} {self.chart_reason} {self.analysis_reason}",
            ["contradiction:", "opposite-condition", "contradicts"],
        )

    @property
    def unmatched(self) -> bool:
        return contains_any(
            self.cross_source,
            [
                "no direct cross-source validation",
                "no directly matching quantitative metric",
                "no quantitative comparison table",
                "no cross-source quantitative validation",
                "no exact claimed option",
            ],
        )


# Fields written by the study-level context builder rather than by evidence
# matching. They describe the study, so they must never count as support for an
# individual claim.
STUDY_LEVEL_MARKERS = [
    "questionnaire uploaded:",
    "primary data uploaded:",
    "additional analysis uploaded:",
    "full insight report context:",
]


def strip_study_level_context(note: str) -> tuple[str, bool]:
    """Remove study-level file summaries from a row's evidence note.

    v5 glued the same summary onto every row, which is what let a vacuous
    insight reach High Confidence. If a note is *only* study-level context, this
    returns an empty string, and the row is correctly treated as unevidenced.
    """
    text = str(note or "").strip()
    if not text:
        return "", False
    lowered = text.lower()
    first_marker = min(
        (lowered.find(marker) for marker in STUDY_LEVEL_MARKERS if marker in lowered),
        default=-1,
    )
    if first_marker < 0:
        return text, False
    return text[:first_marker].strip(), True


def build_row_evidence(row: Dict[str, Any]) -> RowEvidence:
    note, stripped = strip_study_level_context(row.get("evidence_note", ""))
    if is_missing(note):
        note = ""

    try:
        alignment = int(float(row.get("context_alignment_score", 0) or 0))
    except (TypeError, ValueError):
        alignment = 0

    evidence = RowEvidence(
        note=note,
        matched_metrics=clean_context(row.get("quantitative_metrics_validated", ""), ""),
        cross_source=clean_context(row.get("cross_source_validation", ""), ""),
        chart_status=clean_context(row.get("chart_validation_status", ""), ""),
        chart_reason=clean_context(row.get("chart_validation_reason", ""), ""),
        analysis_status=clean_context(row.get("analysis_validation_status", ""), ""),
        analysis_reason=clean_context(row.get("analysis_validation_reason", ""), ""),
        context_alignment=alignment,
    )
    if stripped:
        evidence.trace.append(
            "Study-level file summary removed from this row's evidence; it describes the study, not this claim."
        )
    return evidence


def evidence_tier(insight_text: str, evidence: RowEvidence) -> int:
    """Classify how well this specific claim is supported (0-4)."""
    own = evidence.combined
    if evidence.verified:
        comparative = has_numeric_evidence(own) and (
            contains_any(own, COMPARATIVE_EVIDENCE_TERMS) or contains_any(own, ["n=", "base=", "base:"])
        )
        return 4 if comparative else 3
    if has_numeric_evidence(f"{insight_text} {own}"):
        return 2
    if own.strip():
        return 1
    return 0


# ---------------------------------------------------------------------------
# Quality challenge flags
# ---------------------------------------------------------------------------

def has_decisive_claim(text: str) -> bool:
    return contains_any(text, DECISIVE_CLAIM_TERMS)


def quality_challenge_flags(row: Dict[str, Any], evidence: RowEvidence | None = None) -> List[str]:
    insight = str(row.get("insight_text", "") or "")
    evidence = evidence or build_row_evidence(row)
    own = evidence.combined
    flags: List[str] = []

    decisive = has_decisive_claim(insight)

    if evidence.contradicted:
        detail = evidence.cross_source or evidence.chart_reason or evidence.analysis_reason
        flags.append(f"Evidence contradiction: {detail}".strip())

    if decisive and evidence.unmatched:
        flags.append(
            "Cross-source gap: this ranked or superlative claim could not be matched to a comparative table, "
            "chart or analysis output, so it cannot reach High Confidence."
        )

    if decisive and not has_numeric_evidence(own):
        flags.append(
            "Unsupported decisive claim: winner / best / highest wording needs comparative numbers and a "
            "stated reference point."
        )

    if decisive and contains_any(evidence.note, CONTRADICTORY_EVIDENCE_TERMS) and not evidence.verified:
        flags.append(
            "Directional conflict: the claim asserts a leading option while the evidence note carries weaker, "
            "lower, parity or non-significant signals."
        )

    if evidence.context_alignment and evidence.context_alignment <= 2:
        flags.append(
            "Context mismatch: this insight aligns weakly with the selected objective, study type, technique "
            "or uploaded study evidence."
        )

    if contains_any(insight, OVERCLAIM_TERMS):
        flags.append("Overclaim risk: the wording is too absolute for survey evidence.")

    study_context = study_context_text(row)
    if contains_any(insight, CAUSAL_TERMS) and not contains_any(study_context, CAUSAL_METHOD_TERMS):
        flags.append("Causality risk: causal wording is used without a driver model or causal analysis output.")

    # Unsupported numbers quoted in the claim itself.
    unsupported = [n for n in quoted_numbers(insight) if not number_supported(n, own)]
    if unsupported and evidence.combined:
        flags.append("Unverified figures quoted in the insight: " + ", ".join(unsupported[:4]))

    return flags


def study_context_text(row: Dict[str, Any]) -> str:
    return " ".join(
        str(row.get(key, "") or "")
        for key in ["study_objective", "industry", "technology", "study_type", "analytical_technique"]
    ).lower()


def quality_challenge_text(row: Dict[str, Any], evidence: RowEvidence | None = None) -> str:
    flags = quality_challenge_flags(row, evidence)
    return " | ".join(flags) if flags else "No major quality challenge detected"


# ---------------------------------------------------------------------------
# Dimension scoring
# ---------------------------------------------------------------------------

def auto_dimension_scores(row: Dict[str, Any], evidence: RowEvidence | None = None) -> Dict[str, int]:
    evidence = evidence or build_row_evidence(row)
    insight = str(row.get("insight_text", "") or "")
    own = evidence.combined
    claim_and_evidence = f"{insight} {own}".strip()
    word_count = len(re.findall(r"\w+", insight))
    trace = evidence.trace

    study_type = canonical(row.get("study_type", ""))
    method_lexicon = STUDY_TYPE_KEYWORDS.get(study_type, [])

    flags = quality_challenge_flags(row, evidence)
    contradicted = evidence.contradicted
    decisive_unsupported = any("decisive claim" in f.lower() or "cross-source gap" in f.lower() for f in flags)
    overclaim = contains_any(insight, OVERCLAIM_TERMS)

    # --- Evidence Strength: bounded by tier, never by context ----------------
    tier = evidence_tier(insight, evidence)
    scores: Dict[str, int] = {"evidence_strength": TIER_TO_EVIDENCE_SCORE[tier]}
    trace.append(f"Evidence tier {tier} ({EVIDENCE_TIERS[tier][0]}) -> Evidence Strength {scores['evidence_strength']}/5.")

    if contains_any(own, ["n=", "base=", "base:", "respondents"]):
        trace.append("Base size visible in this row's evidence.")
    else:
        scores["evidence_strength"] = min(scores["evidence_strength"], 4)
        trace.append("No base size visible for this claim: Evidence Strength capped at 4.")

    # --- Methodological Fit --------------------------------------------------
    # The claim must speak the language of the method that produced it. The
    # sidebar selection chooses the lexicon; it does not award points.
    fit = 3
    if method_lexicon and contains_any(claim_and_evidence, method_lexicon):
        fit += 1
        trace.append(f"Claim uses {study_type or 'selected method'} vocabulary -> Methodological Fit +1.")
    else:
        trace.append("Claim does not use the selected method's vocabulary -> no Methodological Fit bonus.")
    if evidence.verified:
        fit += 1
        trace.append("Claim was matched to an actual method output -> Methodological Fit +1.")
    if contains_any(insight, CAUSAL_TERMS) and not contains_any(study_context_text(row), CAUSAL_METHOD_TERMS):
        fit -= 2
        trace.append("Causal wording without a driver/causal method -> Methodological Fit -2.")
    scores["methodological_fit"] = fit

    # --- Triangulation -------------------------------------------------------
    tri = 2
    if evidence.verified:
        tri += 2
        trace.append("Independently verified against an uploaded source -> Triangulation +2.")
    elif tier >= 2:
        tri += 1
        trace.append("Numbers stated but not matched to a source -> Triangulation +1 only.")
    if contains_any(own, COMPARATIVE_EVIDENCE_TERMS):
        tri += 1
        trace.append("Comparison or significance marker present -> Triangulation +1.")
    if evidence.unmatched:
        tri -= 1
        trace.append("No matching source metric found -> Triangulation -1.")
    scores["triangulation"] = tri

    # --- Interpretability ----------------------------------------------------
    interp = 3
    if 10 <= word_count <= 45:
        interp += 1
        trace.append("Sentence length is readable -> Interpretability +1.")
    elif word_count > 70:
        interp -= 1
        trace.append("Sentence is long and layered -> Interpretability -1.")
    elif word_count < 6:
        interp -= 1
        trace.append("Sentence is too short to carry a finding -> Interpretability -1.")
    if has_numeric_evidence(insight):
        interp += 1
        trace.append("Claim is quantified in its own wording -> Interpretability +1.")
    if contains_any(insight, ["unclear", "vague", "somehow", "sort of", "kind of"]):
        interp -= 1
    scores["interpretability"] = interp

    # --- Business Relevance --------------------------------------------------
    relevance = 3
    if contains_any(insight, ACTION_TERMS) or contains_any(insight, ["decision", "strategy", "segment", "customer", "brand"]):
        relevance += 1
        trace.append("Claim connects to a decision or commercial subject -> Business Relevance +1.")
    if evidence.context_alignment >= 4:
        relevance += 1
        trace.append("Strong alignment with the stated objective -> Business Relevance +1.")
    elif evidence.context_alignment and evidence.context_alignment <= 2:
        relevance -= 1
        trace.append("Weak alignment with the stated objective -> Business Relevance -1.")
    scores["business_relevance"] = relevance

    # --- Actionability -------------------------------------------------------
    action = 2
    if contains_any(insight, ACTION_TERMS):
        action += 2
        trace.append("Claim states an action, priority or direction -> Actionability +2.")
    elif contains_any(own, ACTION_TERMS):
        action += 1
        trace.append("Action implied in the evidence note rather than the claim -> Actionability +1.")
    if tier >= 3:
        action += 1
        trace.append("Action rests on verified numbers -> Actionability +1.")
    scores["actionability"] = action

    # --- Bias / Risk Control -------------------------------------------------
    bias = 4
    if overclaim:
        bias -= 2
        trace.append("Absolute wording detected -> Bias / Risk Control -2.")
    if contains_any(insight, CAUSAL_TERMS) and not contains_any(study_context_text(row), CAUSAL_METHOD_TERMS):
        bias -= 1
        trace.append("Unsupported causal wording -> Bias / Risk Control -1.")
    if contains_any(insight, HEDGE_TERMS):
        bias += 1
        trace.append("Claim is appropriately hedged -> Bias / Risk Control +1.")
    if has_decisive_claim(insight) and not evidence.verified:
        bias -= 1
        trace.append("Superlative wording without verification -> Bias / Risk Control -1.")
    scores["bias_risk"] = bias

    # --- Caps applied after all bonuses --------------------------------------
    if contradicted:
        caps = {"evidence_strength": 2, "methodological_fit": 3, "triangulation": 1,
                "business_relevance": 3, "actionability": 2, "bias_risk": 1}
        for key, cap in caps.items():
            scores[key] = min(scores[key], cap)
        trace.append("Contradiction confirmed against source data: hard caps applied to all evidence dimensions.")
    elif decisive_unsupported:
        caps = {"evidence_strength": 3, "triangulation": 2, "actionability": 3, "bias_risk": 2}
        for key, cap in caps.items():
            scores[key] = min(scores[key], cap)
        trace.append("Decisive claim without comparative proof: caps applied.")
    elif flags:
        for key in ["evidence_strength", "triangulation", "bias_risk"]:
            scores[key] = min(scores[key], 3)
        trace.append("Quality challenge raised: evidence, triangulation and bias capped at 3.")

    return {key: clamp_score(scores.get(key, 3)) for key in DIMENSIONS}


# ---------------------------------------------------------------------------
# ICI arithmetic (unchanged)
# ---------------------------------------------------------------------------

def ici_score(weighted_score: float) -> float:
    return round(weighted_score * 20, 1)


def ici_classification(score_100: float) -> str:
    if score_100 >= ICI_HIGH_THRESHOLD:
        return "High Confidence"
    if score_100 >= ICI_MEDIUM_THRESHOLD:
        return "Medium Confidence"
    return "Low Confidence"


def reliance_level(classification: str) -> str:
    return {
        "Not Scorable": "The uploaded study materials cannot be mapped to this claim. Do not use this result.",
        "High Confidence": "Verified against source evidence. Human researcher sign-off is still required.",
        "Medium Confidence": "Partly supported or not fully verified. Researcher review and sign-off required.",
    }.get(classification, "Weak, incomplete or conflicting support. Re-investigate before sign-off.")


def verification_status(evidence: RowEvidence, tier: int) -> str:
    if evidence.contradicted:
        return "Contradicted by source"
    if tier >= 4:
        return "Verified and comparative"
    if tier == 3:
        return "Verified against source"
    if tier == 2:
        return "Stated, not verified"
    if tier == 1:
        return "Narrative only"
    return "No evidence attached"


def parse_score(value: object, column: str) -> int:
    try:
        score = int(float(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be a whole number from 1 to 5 (received {value!r}).") from exc
    if not 1 <= score <= 5:
        raise ValueError(f"{column} score {score} is outside the valid range of 1 to 5.")
    return score


def dimension_points(dimension_scores: Dict[str, int]) -> Dict[str, float]:
    return {key: round((dimension_scores[key] / 5) * DIMENSION_MAX_POINTS[key], 1) for key in DIMENSIONS}


def scorability_issue(row: Dict[str, Any], evidence: RowEvidence) -> str:
    explicit = clean_context(row.get("scorability_status", ""), "").lower()
    if explicit in {"not scorable", "not_scorable"}:
        return "Marked Not Scorable by the study-level validation gate."
    if str(row.get("insight_candidate_status", "")).upper() == "NOT_INSIGHT":
        return clean_context(row.get("insight_candidate_reason", ""), "This text is slide furniture, not a research claim.")
    if evidence.context_alignment and evidence.context_alignment <= 1:
        return "This insight cannot be mapped to the selected study context, questionnaire or evidence."
    return ""


def dimension_diagnostics(dimension_scores: Dict[str, int], flags: List[str]) -> tuple[str, str]:
    if flags:
        return (
            "Quality challenge flagged",
            "Do not use this wording in a client report until the claim is checked against source data. " + " ".join(flags[:2]),
        )
    weak = [(key, score) for key, score in sorted(dimension_scores.items(), key=lambda item: item[1]) if score <= 3]
    if not weak:
        return ("No major weak dimension identified", "Proceed, documenting the evidence trail and reviewer note.")
    labels = [f"{DIMENSIONS[key]['label']} ({score}/5)" for key, score in weak[:2]]
    actions = [str(DIMENSIONS[key]["low_score_action"]) for key, _ in weak[:2]]
    return "; ".join(labels), " ".join(actions)


def root_cause_summary(dimension_scores: Dict[str, int], flags: List[str], evidence: RowEvidence) -> str:
    if flags:
        return " ".join(flags[:2])
    weak = [key for key, score in dimension_scores.items() if score <= 3]
    if not weak:
        return "No major weakness identified; the claim and its evidence are aligned."
    causes = {
        "evidence_strength": "the visible evidence or base detail for this claim is thin",
        "methodological_fit": "the claim needs a clearer link to the method that produced it",
        "triangulation": "the pattern has not been checked against a second cut, wave or source",
        "interpretability": "the wording needs to be clearer or quantified",
        "business_relevance": "the business implication is not yet explicit",
        "actionability": "the next step or decision implication is not clear",
        "bias_risk": "the wording may overstate certainty, causality or representativeness",
    }
    return "; ".join(causes[key] for key in weak[:3]) + "."


def governance_note(row: Dict[str, Any], classification: str) -> str:
    owner = clean_context(row.get("researcher_owner", ""))
    checker = clean_context(row.get("independent_ai_checker", ""))
    benchmark = clean_context(row.get("benchmark_reference", ""))
    if owner == "Not specified":
        return "A named researcher owner is required before this insight is governed for client use."
    if classification == "Not Scorable":
        return f"{owner} must resolve the study/file mapping failure before this insight can be scored."
    if classification == "High Confidence":
        return f"{owner} signs off the evidence trail. Benchmark: {benchmark}. Independent checker: {checker}."
    if classification == "Medium Confidence":
        return f"{owner} must review the flagged dimensions and sign off before client use. Independent checker: {checker}."
    return f"{owner} must re-investigate the evidence, method fit or bias risk before sign-off."


def normalize_theme(value: object) -> str:
    theme = str(value or "").strip()
    if is_missing(theme):
        return "Not specified"
    prefix = "human review required:"
    if theme.lower().startswith(prefix):
        cleaned = theme[len(prefix):].strip()
        return (cleaned[:1].upper() + cleaned[1:]) if cleaned else "Human review issue"
    return theme


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class AICFResult:
    insight_id: str
    theme: str
    insight_text: str
    evidence_note: str
    evidence_tier: int
    evidence_tier_label: str
    verification_status: str
    evidence_strength: int
    methodological_fit: int
    triangulation: int
    interpretability: int
    business_relevance: int
    actionability: int
    bias_risk: int
    evidence_strength_points: float
    methodological_fit_points: float
    triangulation_points: float
    interpretability_points: float
    business_relevance_points: float
    actionability_points: float
    bias_risk_points: float
    weighted_score: float
    ici_score: float
    ici_classification: str
    confidence_level: str
    review_status: str
    reliance_level: str
    weakest_dimensions: str
    root_cause: str
    data_reference: str
    how_to_increase_score: str
    recommendation: str
    quality_challenge_flags: str
    score_trace: str
    context_alignment_score: int
    context_alignment_note: str
    quantitative_metrics_validated: str
    cross_source_validation: str
    study_objective: str
    industry: str
    technology: str
    study_type: str
    analytical_technique: str
    insight_source: str
    researcher_owner: str
    independent_ai_checker: str
    benchmark_reference: str
    governance_note: str
    scoring_mode: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def data_reference(row: Dict[str, Any], evidence: RowEvidence) -> str:
    parts = [evidence.cross_source, evidence.matched_metrics, evidence.note]
    parts = [part for part in parts if part]
    if parts:
        return " | ".join(parts)
    source_bits = [
        clean_context(row.get("source_file", ""), ""),
        clean_context(row.get("slide_number", ""), ""),
        clean_context(row.get("insight_id", ""), ""),
    ]
    source_bits = [bit for bit in source_bits if bit]
    if source_bits:
        return "Source context: " + " | ".join(source_bits)
    return "No evidence source is attached to this insight."


def score_insight(row: Dict[str, Any], use_manual_scores: bool = False) -> AICFResult:
    evidence = build_row_evidence(row)

    has_manual = use_manual_scores and all(not is_missing(row.get(key)) for key in MANUAL_SCORE_COLUMNS)
    if has_manual:
        dimension_scores = {key: parse_score(row.get(key), key) for key in DIMENSIONS}
        scoring_mode = "Manual evaluator scores"
        evidence.trace.append("Manual evaluator scores were supplied and used in place of automatic scoring.")
    else:
        dimension_scores = auto_dimension_scores(row, evidence)
        scoring_mode = "AICF auto-estimated scores"

    weighted = sum(dimension_scores[key] * float(DIMENSIONS[key]["weight"]) for key in DIMENSIONS)
    score_100 = ici_score(weighted)
    classification = ici_classification(score_100)

    flags = quality_challenge_flags(row, evidence)
    tier = evidence_tier(str(row.get("insight_text", "")), evidence)

    not_scorable_reason = scorability_issue(row, evidence)
    if not_scorable_reason:
        classification = "Not Scorable"
        weighted, score_100 = 0.0, 0.0
        evidence.trace.append(f"Not Scorable: {not_scorable_reason}")
    elif classification == "High Confidence" and tier < 3:
        classification = "Medium Confidence"
        evidence.trace.append(
            "High Confidence withheld: no number in this claim was matched to an uploaded source (evidence tier "
            f"{tier}). Capped at Medium Confidence."
        )

    weakest, recommendation = dimension_diagnostics(dimension_scores, flags)
    points = dimension_points(dimension_scores)

    return AICFResult(
        insight_id=str(row.get("insight_id", "")).strip(),
        theme=normalize_theme(row.get("theme", "")),
        insight_text=str(row.get("insight_text", "")).strip(),
        evidence_note=evidence.note or "No row-level evidence note supplied.",
        evidence_tier=tier,
        evidence_tier_label=EVIDENCE_TIERS[tier][0],
        verification_status=verification_status(evidence, tier),
        evidence_strength=dimension_scores["evidence_strength"],
        methodological_fit=dimension_scores["methodological_fit"],
        triangulation=dimension_scores["triangulation"],
        interpretability=dimension_scores["interpretability"],
        business_relevance=dimension_scores["business_relevance"],
        actionability=dimension_scores["actionability"],
        bias_risk=dimension_scores["bias_risk"],
        evidence_strength_points=points["evidence_strength"],
        methodological_fit_points=points["methodological_fit"],
        triangulation_points=points["triangulation"],
        interpretability_points=points["interpretability"],
        business_relevance_points=points["business_relevance"],
        actionability_points=points["actionability"],
        bias_risk_points=points["bias_risk"],
        weighted_score=round(weighted, 2),
        ici_score=score_100,
        ici_classification=classification,
        confidence_level=classification,
        review_status=classification,
        reliance_level=reliance_level(classification),
        weakest_dimensions=weakest,
        root_cause=not_scorable_reason or root_cause_summary(dimension_scores, flags, evidence),
        data_reference=data_reference(row, evidence),
        how_to_increase_score=recommendation,
        recommendation=recommendation,
        quality_challenge_flags=quality_challenge_text(row, evidence),
        score_trace=" ".join(evidence.trace),
        context_alignment_score=evidence.context_alignment,
        context_alignment_note=clean_context(row.get("context_alignment_note", "")),
        quantitative_metrics_validated=clean_context(row.get("quantitative_metrics_validated", "")),
        cross_source_validation=clean_context(row.get("cross_source_validation", "")),
        study_objective=clean_context(row.get("study_objective", "")),
        industry=clean_context(row.get("industry", "")),
        technology=clean_context(row.get("technology", "")),
        study_type=clean_context(row.get("study_type", "")),
        analytical_technique=clean_context(row.get("analytical_technique", "")),
        insight_source=clean_context(row.get("insight_source", "")),
        researcher_owner=clean_context(row.get("researcher_owner", "")),
        independent_ai_checker=clean_context(row.get("independent_ai_checker", "")),
        benchmark_reference=clean_context(row.get("benchmark_reference", "")),
        governance_note=governance_note(row, classification),
        scoring_mode=scoring_mode,
    )


def validate_columns(columns: List[str]) -> List[str]:
    lowered = {str(column).strip().lower() for column in columns}
    return [column for column in REQUIRED_COLUMNS if column not in lowered]
