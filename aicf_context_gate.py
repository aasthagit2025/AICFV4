"""Study-context checks, split into blockers and advisories.

v5 treated every heuristic keyword mismatch as a fatal error and called
``st.stop()``. A study whose vocabulary did not match the built-in lexicons was
refused outright with no override, which is why some valid studies could not be
scored at all. One example: the check ``objective_overlap < 3`` demanded that at
least three words from the typed objective reappear in the uploaded files, so the
app's own default objective text blocked scoring on most real studies.

v6 splits the checks in two:

* **Blockers** are mechanical and always correct: a missing file, a missing
  required column, no readable insight rows, no evidence source. These still stop
  the run.
* **Advisories** are heuristic. They are shown to the researcher, who can confirm
  the files belong to the same study and continue. If they are not confirmed,
  scoring proceeds with context alignment reduced, which lowers confidence
  instead of refusing to produce a result.

This keeps the governance intent of the framework (nothing passes silently) while
removing the false refusals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from aicf_config import (
    INDUSTRY_KEYWORDS,
    STOPWORDS,
    STUDY_TYPE_KEYWORDS,
    TECHNIQUE_KEYWORDS,
    canonical,
    canonical_list,
)
from aicf_evidence import tokenize


@dataclass
class GateResult:
    blockers: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return bool(self.blockers)


def objective_terms(objective: str) -> set[str]:
    return {token for token in tokenize(objective) if len(token) >= 4 and token not in STOPWORDS}


def count_hits(text: str, keywords: list[str]) -> int:
    lowered = str(text or "").lower()
    return sum(1 for keyword in keywords if keyword and keyword.lower() in lowered)


def context_keywords(study_type: str, industry: str, techniques: list[str]) -> list[str]:
    keywords: list[str] = []
    keywords += STUDY_TYPE_KEYWORDS.get(canonical(study_type), [])
    keywords += INDUSTRY_KEYWORDS.get(industry, [])
    for technique in canonical_list(techniques):
        keywords += TECHNIQUE_KEYWORDS.get(technique, [])
    return sorted({keyword for keyword in keywords if keyword})


def dataframe_text(df: pd.DataFrame, max_rows: int = 30) -> str:
    if df is None or df.empty:
        return ""
    columns = " ".join(map(str, df.columns))
    body = " ".join(" ".join(map(str, row.values)) for _, row in df.head(max_rows).iterrows())
    return f"{columns} {body}"[:12000]


def run_gate(
    *,
    objective: str,
    industry: str,
    technology: str,
    study_type: str,
    techniques: list[str],
    qre_text: str,
    data_df: pd.DataFrame,
    insight_df: pd.DataFrame,
    evidence_present: bool,
    additional_context: str = "",
) -> GateResult:
    result = GateResult()

    # ---- Blockers: mechanical, never heuristic ----------------------------
    if not str(objective).strip():
        result.blockers.append("Enter the research objective for this study.")
    if not industry:
        result.blockers.append("Select one industry / sector.")
    if not technology:
        result.blockers.append("Select one technology / data environment.")
    if not study_type:
        result.blockers.append("Select one study type.")
    if not techniques:
        result.blockers.append("Select at least one analytical technique.")
    if not evidence_present:
        result.blockers.append(
            "Upload at least one evidence source: primary data, or an analysis / table output. "
            "AICF does not validate insights from the report alone."
        )
    if insight_df is None or insight_df.empty:
        result.blockers.append(
            "No readable insight statements were found in the uploaded report. "
            "For PowerPoint, check that text is in real text boxes rather than images; "
            "for Excel or CSV, check that the file has insight_id and insight_text columns."
        )
        return result

    # ---- Advisories: heuristic, overridable -------------------------------
    insight_text = dataframe_text(insight_df)
    data_text = dataframe_text(data_df, max_rows=8)
    uploaded_text = f"{qre_text} {data_text} {additional_context} {insight_text}"
    keywords = context_keywords(study_type, industry, techniques)
    terms = objective_terms(objective)

    if len(terms) < 3:
        result.advisories.append(
            "The research objective is very short or generic. A study-specific objective improves context "
            "alignment scoring and makes the audit trail more useful."
        )

    if qre_text.strip():
        if count_hits(qre_text, STUDY_TYPE_KEYWORDS.get(canonical(study_type), [])) == 0 and len(terms & tokenize(qre_text)) < 2:
            result.advisories.append(
                f"The questionnaire does not obviously match the selected study type ({study_type}). "
                "Confirm the QRE belongs to this study."
            )
    else:
        result.advisories.append("No text could be read from the questionnaire file.")

    if count_hits(insight_text, keywords) < 2 and len(terms & tokenize(insight_text)) < 2:
        result.advisories.append(
            "The insight report shares little vocabulary with the selected objective, industry, study type "
            "or technique. Confirm the report belongs to this study."
        )

    if data_df is not None and not data_df.empty:
        if count_hits(data_text, keywords) == 0:
            result.advisories.append(
                "The primary data columns do not strongly reflect the selected study context. "
                "Scoring will be more cautious."
            )
    else:
        result.notes.append(
            "No primary data was uploaded. AICF will validate against the questionnaire, the insight report "
            "and the analysis / table output."
        )

    hits_by_type = {name: count_hits(uploaded_text, words) for name, words in STUDY_TYPE_KEYWORDS.items()}
    dominant, dominant_hits = max(hits_by_type.items(), key=lambda item: item[1])
    selected_hits = hits_by_type.get(canonical(study_type), 0)
    if dominant != canonical(study_type) and dominant_hits >= 5 and selected_hits <= 1:
        result.advisories.append(
            f"You selected {study_type}, but the uploaded files read more like {dominant}. "
            "Check the study type before relying on the scores."
        )

    for technique in canonical_list(techniques):
        if technique in {"Conjoint", "MaxDiff / TURF", "KDA / Driver Analysis", "Correspondence Analysis"}:
            if count_hits(uploaded_text, TECHNIQUE_KEYWORDS.get(technique, [])) == 0:
                result.advisories.append(
                    f"{technique} is selected, but no matching method output (utilities, importances, "
                    "coefficients or coordinates) was found in the uploaded files. Add that output to "
                    "strengthen validation."
                )

    return result


def alignment_penalty(gate: GateResult, confirmed: bool) -> int:
    """How much to reduce context alignment when advisories are not confirmed."""
    if confirmed or not gate.advisories:
        return 0
    return min(2, len(gate.advisories))
