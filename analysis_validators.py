from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd


ANALYSIS_VALIDATION_COLUMNS = [
    "insight_candidate_status",
    "insight_candidate_reason",
    "analysis_validator_used",
    "analysis_validation_status",
    "analysis_metrics_validated",
    "analysis_validation_reason",
    "analysis_claimed_item",
    "analysis_true_top_item",
    "analysis_contradiction_flag",
    "report_contradiction_status",
    "report_contradiction_reason",
]

DECISIVE_POSITIVE_CUES = [
    "most", "highest", "strongest", "best", "winner", "winning", "key driver",
    "main driver", "primary driver", "top driver", "leads", "outperforms",
    "most preferred", "highest preference", "highest share", "maximum reach",
]

DECISIVE_NEGATIVE_CUES = [
    "least", "lowest", "weakest", "worst", "least preferred", "lowest share",
]

INSIGHT_CUES = [
    "because", "therefore", "indicates", "suggests", "shows", "driven by",
    "driver", "opportunity", "priority", "should", "recommend", "needs",
    "stronger", "weaker", "higher", "lower", "gap", "risk", "strength",
    "preference", "consideration", "satisfaction", "appeal", "intent",
]

NON_INSIGHT_CUES = [
    "perceptual map", "affinity perceptual map", "functional perceptual map",
    "methodology", "sample profile", "base:", "n=", "questionnaire",
    "table of contents", "appendix", "thank you", "screener",
]


def compact_text(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split()).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def normalize_text(value: object) -> str:
    text = str(value or "").lower().replace("&", " and ")
    text = text.replace("�", " ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def value_as_number(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    text = str(value).strip().replace(",", "")
    pct = "%" in text
    text = text.replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number / 100 if pct else number


def format_value(value: float | None) -> str:
    if value is None:
        return ""
    if -1 <= value <= 1:
        return f"{value * 100:.1f}%"
    if float(value).is_integer():
        return f"{value:.0f}"
    return f"{value:.3f}"


def file_bytes(uploaded_file) -> bytes:
    if uploaded_file is None:
        return b""
    if hasattr(uploaded_file, "getvalue"):
        return uploaded_file.getvalue()
    pos = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    data = uploaded_file.read()
    if pos is not None and hasattr(uploaded_file, "seek"):
        uploaded_file.seek(pos)
    return data


def read_workbook_sheets(uploaded_file, max_sheets: int = 18) -> list[tuple[str, pd.DataFrame]]:
    source_name = str(getattr(uploaded_file, "name", "") or "").lower()
    data = file_bytes(uploaded_file)
    if not data:
        return []
    try:
        if source_name.endswith(".csv"):
            try:
                return [(getattr(uploaded_file, "name", "csv"), pd.read_csv(io.BytesIO(data), header=None, encoding="utf-8-sig"))]
            except UnicodeDecodeError:
                return [(getattr(uploaded_file, "name", "csv"), pd.read_csv(io.BytesIO(data), header=None, encoding="latin1"))]
        if source_name.endswith((".xlsx", ".xls", ".xlsm")):
            excel = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
            relevant_keywords = [
                "kda", "driver", "importance", "importances", "turf output",
                "individual reach", "front page", "product coding", "saved concepts",
                "correspondence", "perceptual", "factor", "segment",
            ]
            selected_sheets = [
                sheet_name for sheet_name in excel.sheet_names
                if any(keyword in normalize_text(sheet_name) for keyword in relevant_keywords)
            ]
            if not selected_sheets:
                selected_sheets = excel.sheet_names[:max_sheets]
            return [
                (sheet_name, pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object))
                for sheet_name in selected_sheets[:max_sheets]
            ]
    except Exception:
        return []
    return []


def row_text(row: pd.Series) -> str:
    return " ".join(str(value) for value in row.tolist() if pd.notna(value) and str(value).strip())


def detect_insight_candidate(row: dict[str, Any]) -> tuple[str, str]:
    text = compact_text(f"{row.get('theme', '')} {row.get('insight_text', '')}", 800)
    normalized = normalize_text(text)
    word_count = len(normalized.split())
    if word_count < 5:
        return "NOT_INSIGHT", "Too short to be treated as a research insight."
    if any(cue in normalized for cue in NON_INSIGHT_CUES) and not any(cue in normalized for cue in INSIGHT_CUES):
        return "NOT_INSIGHT", "Looks like a slide title, method label, table heading, or admin note rather than an insight claim."
    if re.fullmatch(r"(q|s|c|d)[a-z0-9_ -]{1,18}", normalized):
        return "NOT_INSIGHT", "Looks like a question/code label rather than an insight claim."
    if not any(cue in normalized for cue in INSIGHT_CUES + DECISIVE_POSITIVE_CUES + DECISIVE_NEGATIVE_CUES):
        return "REVIEW_CANDIDATE", "Possible insight, but it has weak claim language; researcher should confirm it is a real insight."
    return "INSIGHT", "Contains claim/evidence/action wording suitable for AICF validation."


def is_positive_decisive(text: object) -> bool:
    normalized = normalize_text(text)
    return any(cue in normalized for cue in DECISIVE_POSITIVE_CUES) and not any(
        cue in normalized for cue in DECISIVE_NEGATIVE_CUES
    )


def is_negative_decisive(text: object) -> bool:
    normalized = normalize_text(text)
    return any(cue in normalized for cue in DECISIVE_NEGATIVE_CUES)


def find_header_row(table: pd.DataFrame, required_terms: list[str]) -> int | None:
    for idx, row in table.iterrows():
        normalized = normalize_text(row_text(row))
        if all(term in normalized for term in required_terms):
            return int(idx)
    return None


def column_by_terms(row: pd.Series, terms: list[str]) -> int | None:
    for idx, value in row.items():
        normalized = normalize_text(value)
        if all(term in normalized for term in terms):
            return int(idx)
    return None


def exact_or_terms_column(
    row: pd.Series,
    exact: str,
    terms: list[str],
    exclude_terms: list[str] | None = None,
    prefer_last: bool = False,
) -> int | None:
    exclude_terms = exclude_terms or []
    exact_matches = []
    for idx, value in row.items():
        normalized = normalize_text(value)
        if normalized == exact:
            exact_matches.append(int(idx))
    if exact_matches:
        return exact_matches[-1] if prefer_last else exact_matches[0]
    term_matches = []
    for idx, value in row.items():
        normalized = normalize_text(value)
        if all(term in normalized for term in terms) and not any(term in normalized for term in exclude_terms):
            term_matches.append(int(idx))
    if term_matches:
        return term_matches[-1] if prefer_last else term_matches[0]
    return None


def extract_kda_records(source_name: str, sheet_name: str, table: pd.DataFrame) -> list[dict[str, Any]]:
    header_idx = find_header_row(table, ["attributes", "p value"])
    if header_idx is None:
        return []
    header = table.iloc[header_idx]
    label_col = column_by_terms(header, ["attributes"])
    effect_col = column_by_terms(header, ["effect"])
    t_col = column_by_terms(header, ["t", "value"])
    p_col = column_by_terms(header, ["p", "value"])
    importance_col = column_by_terms(header, ["relative", "importance"])
    code_col = label_col
    text_label_col = label_col
    if label_col is not None and label_col + 1 < table.shape[1]:
        sample_values = [
            compact_text(table.iat[ridx, label_col + 1], 120)
            for ridx in range(header_idx + 1, min(header_idx + 6, len(table)))
        ]
        if sum(1 for value in sample_values if len(normalize_text(value).split()) >= 3) >= 2:
            text_label_col = label_col + 1
    if label_col is None or importance_col is None:
        return []
    records = []
    for ridx in range(header_idx + 1, len(table)):
        label = compact_text(table.iat[ridx, text_label_col], 240)
        importance = value_as_number(table.iat[ridx, importance_col])
        if not label or importance is None:
            continue
        records.append(
            {
                "analysis_type": "KDA / Driver Analysis",
                "source_file": source_name,
                "sheet": sheet_name,
                "metric": "Relative Importance",
                "label": label,
                "code": compact_text(table.iat[ridx, code_col], 80) if code_col is not None else "",
                "value": importance,
                "effect_size": value_as_number(table.iat[ridx, effect_col]) if effect_col is not None else None,
                "t_value": value_as_number(table.iat[ridx, t_col]) if t_col is not None else None,
                "p_value": value_as_number(table.iat[ridx, p_col]) if p_col is not None else None,
            }
        )
    ranked = sorted(records, key=lambda item: item["value"], reverse=True)
    for rank, record in enumerate(ranked, start=1):
        record["rank"] = rank
    return ranked


def extract_maxdiff_turf_records(source_name: str, sheet_name: str, table: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    header_idx = find_header_row(table, ["statement", "relative", "importance"])
    if header_idx is not None:
        header = table.iloc[header_idx]
        label_col = column_by_terms(header, ["statement"])
        value_col = column_by_terms(header, ["relative", "importance"])
        rank_col = column_by_terms(header, ["rank"])
        if label_col is not None and value_col is not None:
            for ridx in range(header_idx + 1, len(table)):
                label = compact_text(table.iat[ridx, label_col], 220)
                value = value_as_number(table.iat[ridx, value_col])
                if label and value is not None:
                    records.append(
                        {
                            "analysis_type": "MaxDiff / Preference",
                            "source_file": source_name,
                            "sheet": sheet_name,
                            "metric": "Relative Importance",
                            "label": label,
                            "value": value,
                            "rank": int(value_as_number(table.iat[ridx, rank_col]) or 0) if rank_col is not None else None,
                        }
                    )
    header_idx = find_header_row(table, ["attribute", "reach"])
    if header_idx is not None:
        header = table.iloc[header_idx]
        label_col = exact_or_terms_column(header, "attribute", ["attribute"], ["no"])
        if label_col is not None:
            metric_candidates = [
                ("Cumulative Reach %", exact_or_terms_column(header, "cumulative reach", ["cumulative", "reach"], prefer_last=True)),
                ("Individual Reach %", exact_or_terms_column(header, "individual reach", ["individual", "reach"], prefer_last=True)),
                ("Unduplicated Reach", column_by_terms(header, ["duplicated", "reach"])),
            ]
            for metric, value_col in metric_candidates:
                if value_col is None:
                    continue
                for ridx in range(header_idx + 1, len(table)):
                    label = compact_text(table.iat[ridx, label_col], 220)
                    value = value_as_number(table.iat[ridx, value_col])
                    if label and value is not None:
                        records.append(
                            {
                                "analysis_type": "TURF / Reach",
                                "source_file": source_name,
                                "sheet": sheet_name,
                                "metric": metric,
                                "label": label,
                                "value": value,
                            }
                        )
                break
    ranked_by_metric(records)
    return records


def extract_conjoint_records(source_name: str, sheet_name: str, table: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    normalized_sheet = normalize_text(sheet_name)
    if "front page" in normalized_sheet:
        product_row = None
        share_row = None
        for idx, row in table.iterrows():
            normalized = normalize_text(row_text(row))
            if "product 1" in normalized and product_row is None:
                product_row = int(idx)
            if "shares of preference" in normalized or "share of preference" in normalized:
                share_row = int(idx)
        if product_row is not None and share_row is not None:
            for col_idx in range(table.shape[1]):
                product = compact_text(table.iat[product_row, col_idx], 80)
                share = value_as_number(table.iat[share_row, col_idx])
                if product and normalize_text(product).startswith("product") and share is not None:
                    records.append(
                        {
                            "analysis_type": "Conjoint / CBC Simulator",
                            "source_file": source_name,
                            "sheet": sheet_name,
                            "metric": "Share of Preference",
                            "label": product,
                            "value": share,
                        }
                    )
    header_idx = find_header_row(table, ["attributes", "importances"])
    if header_idx is not None:
        header = table.iloc[header_idx]
        attr_col = column_by_terms(header, ["attributes"])
        attr_imp_col = column_by_terms(header, ["attribute", "importances"])
        level_col = column_by_terms(header, ["levels"])
        level_imp_col = column_by_terms(header, ["level", "importances"])
        current_attribute = ""
        for ridx in range(header_idx + 1, len(table)):
            attr = compact_text(table.iat[ridx, attr_col], 220) if attr_col is not None else ""
            if attr:
                current_attribute = attr
            attr_imp = value_as_number(table.iat[ridx, attr_imp_col]) if attr_imp_col is not None else None
            if current_attribute and attr_imp is not None:
                records.append(
                    {
                        "analysis_type": "Conjoint / CBC Simulator",
                        "source_file": source_name,
                        "sheet": sheet_name,
                        "metric": "Attribute Importance",
                        "label": current_attribute,
                        "value": attr_imp,
                    }
                )
            level = compact_text(table.iat[ridx, level_col], 220) if level_col is not None else ""
            level_imp = value_as_number(table.iat[ridx, level_imp_col]) if level_imp_col is not None else None
            if level and level_imp is not None:
                records.append(
                    {
                        "analysis_type": "Conjoint / CBC Simulator",
                        "source_file": source_name,
                        "sheet": sheet_name,
                        "metric": "Level Importance",
                        "label": level,
                        "parent": current_attribute,
                        "value": level_imp,
                    }
                )
    ranked_by_metric(records)
    return records


def extract_generic_advanced_records(source_name: str, sheet_name: str, table: pd.DataFrame) -> list[dict[str, Any]]:
    text = normalize_text(" ".join(row_text(row) for _, row in table.head(20).iterrows()))
    records = []
    if "correspondence" in text or "perceptual map" in text:
        records.append(
            {
                "analysis_type": "Correspondence Analysis",
                "source_file": source_name,
                "sheet": sheet_name,
                "metric": "Map validation",
                "label": "Correspondence/perceptual map",
                "value": None,
                "note": "Upload map coordinates, inertia/explained variance, and brand/attribute coordinates for full validation.",
            }
        )
    if "factor loading" in text or "eigenvalue" in text or "variance explained" in text:
        records.append(
            {
                "analysis_type": "Factor Analysis",
                "source_file": source_name,
                "sheet": sheet_name,
                "metric": "Factor validation",
                "label": "Factor analysis output",
                "value": None,
                "note": "Validate factor claims against loadings, cross-loadings, eigenvalue, variance explained, KMO/Bartlett and reliability.",
            }
        )
    if "segment" in text and ("segment size" in text or "profile" in text):
        records.append(
            {
                "analysis_type": "Segmentation",
                "source_file": source_name,
                "sheet": sheet_name,
                "metric": "Segment validation",
                "label": "Segmentation output",
                "value": None,
                "note": "Validate segment claims against size, differentiators, profile, attractiveness and recommended action.",
            }
        )
    return records


def ranked_by_metric(records: list[dict[str, Any]]) -> None:
    keys = sorted({(r.get("analysis_type"), r.get("metric"), r.get("parent", "")) for r in records})
    for key in keys:
        subset = [r for r in records if (r.get("analysis_type"), r.get("metric"), r.get("parent", "")) == key and r.get("value") is not None]
        ranked = sorted(subset, key=lambda item: item.get("value", 0), reverse=True)
        for rank, record in enumerate(ranked, start=1):
            record["rank"] = rank


def extract_analysis_evidence(uploaded_files) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for uploaded_file in uploaded_files or []:
        source_name = getattr(uploaded_file, "name", "uploaded analysis")
        for sheet_name, table in read_workbook_sheets(uploaded_file):
            sheet_norm = normalize_text(sheet_name)
            sheet_records: list[dict[str, Any]] = []
            if "kda" in sheet_norm or "driver" in sheet_norm or find_header_row(table, ["p value", "relative", "importance"]) is not None:
                sheet_records.extend(extract_kda_records(source_name, sheet_name, table))
            if any(term in sheet_norm for term in ["turf", "individual reach", "importance", "maxdiff", "utilities"]):
                sheet_records.extend(extract_maxdiff_turf_records(source_name, sheet_name, table))
            if any(term in sheet_norm for term in ["front page", "importances", "share calculation", "product coding", "saved concepts", "conjoint", "cbcc"]):
                sheet_records.extend(extract_conjoint_records(source_name, sheet_name, table))
            sheet_records.extend(extract_generic_advanced_records(source_name, sheet_name, table))
            records.extend(sheet_records)
    return records


def matching_records(text: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    matches = []
    for record in records:
        label = normalize_text(record.get("label", ""))
        if len(label) >= 4 and label in normalized:
            matches.append(record)
    return matches


def record_relevance(record: dict[str, Any], text: str) -> float:
    normalized = normalize_text(text)
    analysis_type = normalize_text(record.get("analysis_type", ""))
    metric = normalize_text(record.get("metric", ""))
    label = normalize_text(record.get("label", ""))
    sheet = normalize_text(record.get("sheet", ""))
    score = 0.0
    if record.get("value") is not None:
        score += 1
    score += min(len(label.split()), 6) * 4
    if any(term in normalized for term in ["reach", "turf", "unduplicated", "cumulative"]):
        if "turf" in analysis_type or "reach" in metric:
            score += 20
        if "individual reach" in metric or "individual reach" in sheet:
            score += 30
        if "cumulative" in metric and not any(term in normalized for term in ["cumulative", "bundle"]):
            score -= 12
        if "relative importance" in metric:
            score -= 6
    if any(term in normalized for term in ["driver", "kda", "dependent", "consideration", "satisfaction"]):
        if "kda" in analysis_type or "driver" in analysis_type:
            score += 20
    if any(term in normalized for term in ["conjoint", "cbc", "share of preference", "preference share", "product"]):
        if "conjoint" in analysis_type or "share of preference" in metric:
            score += 20
    if any(term in normalized for term in ["maxdiff", "most preferred", "least preferred", "preference score"]):
        if "maxdiff" in analysis_type:
            score += 20
    return score


def top_record_for(record: dict[str, Any], records: list[dict[str, Any]], lowest: bool = False) -> dict[str, Any] | None:
    comparable = [
        item for item in records
        if item.get("analysis_type") == record.get("analysis_type")
        and item.get("metric") == record.get("metric")
        and item.get("parent", "") == record.get("parent", "")
        and item.get("value") is not None
    ]
    if not comparable:
        return None
    return sorted(comparable, key=lambda item: item.get("value", 0), reverse=not lowest)[0]


def validate_insight_with_analysis_evidence(row: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, str]:
    candidate_status, candidate_reason = detect_insight_candidate(row)
    result = {column: "" for column in ANALYSIS_VALIDATION_COLUMNS}
    result["insight_candidate_status"] = candidate_status
    result["insight_candidate_reason"] = candidate_reason
    if candidate_status == "NOT_INSIGHT":
        result["analysis_validator_used"] = "Not scored"
        result["analysis_validation_status"] = "NOT_SCORED"
        result["analysis_validation_reason"] = "Content is not a research insight claim."
        return result
    if not records:
        result["analysis_validator_used"] = "General report validator"
        result["analysis_validation_status"] = "REVIEW"
        result["analysis_validation_reason"] = "No method-specific KDA/MaxDiff/TURF/conjoint/segmentation/correspondence/factor evidence was found."
        return result

    text = f"{row.get('theme', '')} {row.get('insight_text', '')}"
    matches = matching_records(text, records)
    available_types = ", ".join(sorted({str(record.get("analysis_type")) for record in records if record.get("analysis_type")}))
    if not matches:
        result["analysis_validator_used"] = available_types or "Advanced-analysis validator"
        result["analysis_validation_status"] = "REVIEW"
        result["analysis_validation_reason"] = "Advanced-analysis output is present, but no exact driver/item/concept/segment label could be matched to this insight."
        return result

    positive = is_positive_decisive(text)
    negative = is_negative_decisive(text)
    selected = sorted(matches, key=lambda item: record_relevance(item, text), reverse=True)[0]
    top = top_record_for(selected, records, lowest=negative)
    result["analysis_validator_used"] = str(selected.get("analysis_type", "Advanced-analysis validator"))
    result["analysis_claimed_item"] = str(selected.get("label", ""))
    result["analysis_metrics_validated"] = (
        f"{selected.get('analysis_type')} / {selected.get('metric')}: "
        f"{selected.get('label')}={format_value(selected.get('value'))}; "
        f"rank={selected.get('rank', '')}; p={format_value(selected.get('p_value'))}; "
        f"source={selected.get('source_file')}, sheet={selected.get('sheet')}."
    )
    if top:
        result["analysis_true_top_item"] = f"{top.get('label')}={format_value(top.get('value'))}"

    if (positive or negative) and top and normalize_text(selected.get("label")) != normalize_text(top.get("label")):
        target = "lowest" if negative else "highest"
        result["analysis_validation_status"] = "FAIL"
        result["analysis_contradiction_flag"] = "YES"
        result["analysis_validation_reason"] = (
            f"Contradiction: insight claims {selected.get('label')} as {target}/most decisive, "
            f"but {top.get('label')} is {target} on {selected.get('metric')} "
            f"({format_value(top.get('value'))} vs {format_value(selected.get('value'))})."
        )
        return result

    if selected.get("analysis_type") == "KDA / Driver Analysis":
        p_value = selected.get("p_value")
        if p_value is not None and p_value > 0.05 and positive:
            result["analysis_validation_status"] = "REVIEW"
            result["analysis_validation_reason"] = (
                f"KDA driver matched, but p-value is {format_value(p_value)}, so the insight should be described as directional unless confirmed."
            )
            return result

    result["analysis_validation_status"] = "PASS"
    if positive or negative:
        result["analysis_validation_reason"] = (
            f"Supported by {selected.get('analysis_type')}: claimed item aligns with the matched {selected.get('metric')} ranking."
        )
    else:
        result["analysis_validation_reason"] = (
            f"Matched to {selected.get('analysis_type')} evidence; no contradiction detected in the matched metric."
        )
    return result


def append_analysis_validation_to_cross_source(row: dict[str, Any], analysis_result: dict[str, str]) -> tuple[str, str]:
    metrics = str(row.get("quantitative_metrics_validated", "") or "")
    validation = str(row.get("cross_source_validation", "") or "")
    analysis_metrics = str(analysis_result.get("analysis_metrics_validated", "") or "")
    analysis_reason = str(analysis_result.get("analysis_validation_reason", "") or "")
    status = str(analysis_result.get("analysis_validation_status", "") or "")
    if analysis_metrics:
        metrics = compact_text(" | ".join(bit for bit in [analysis_metrics, metrics] if bit), 900)
    if analysis_reason and status in {"FAIL", "REVIEW", "PASS"}:
        prefix = "Contradiction" if status == "FAIL" else ("Supported" if status == "PASS" else "Review")
        validation = compact_text(" | ".join(bit for bit in [f"{prefix}: {analysis_reason}", validation] if bit), 700)
    return metrics, validation


def add_report_level_contradiction_checks(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return report
    enriched = report.copy()
    if "report_contradiction_status" not in enriched.columns:
        enriched["report_contradiction_status"] = "PASS"
    if "report_contradiction_reason" not in enriched.columns:
        enriched["report_contradiction_reason"] = "No report-level contradiction detected."

    for idx, row in enriched.iterrows():
        combined = " ".join(
            str(row.get(col, "") or "")
            for col in ["cross_source_validation", "analysis_validation_reason", "chart_validation_reason", "quality_challenge_flags"]
        ).lower()
        if "contradiction" in combined or "opposite-condition" in combined:
            enriched.at[idx, "report_contradiction_status"] = "FAIL"
            enriched.at[idx, "report_contradiction_reason"] = compact_text(
                row.get("analysis_validation_reason")
                or row.get("chart_validation_reason")
                or row.get("cross_source_validation")
                or "Contradiction detected in row-level validation.",
                700,
            )

    if {"analysis_metrics_validated", "analysis_claimed_item"}.issubset(set(enriched.columns)):
        positive_claim_rows = []
        for idx, row in enriched.iterrows():
            text = f"{row.get('theme', '')} {row.get('insight_text', '')}"
            metric = str(row.get("analysis_metrics_validated", "") or "").split(":")[0]
            claimed = normalize_text(row.get("analysis_claimed_item", ""))
            if metric and claimed and is_positive_decisive(text):
                positive_claim_rows.append((metric, claimed, idx))
        by_metric: dict[str, set[str]] = {}
        for metric, claimed, _ in positive_claim_rows:
            by_metric.setdefault(metric, set()).add(claimed)
        conflicted_metrics = {metric for metric, claims in by_metric.items() if len(claims) > 1}
        for metric, _, idx in positive_claim_rows:
            if metric in conflicted_metrics and enriched.at[idx, "report_contradiction_status"] != "FAIL":
                enriched.at[idx, "report_contradiction_status"] = "REVIEW"
                enriched.at[idx, "report_contradiction_reason"] = (
                    "Multiple different items are claimed as strongest/top on the same analysis metric; check report story consistency."
                )
    return enriched
