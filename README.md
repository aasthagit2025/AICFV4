# Analytical Insight Confidence Framework (AICF) Tool

A Streamlit application that validates Human, AI or Human+AI market research
insights against the questionnaire, the data and the analysis output, and
produces an auditable Insight Confidence Index (ICI) out of 100.

Version 6. See `CHANGELOG.md` for what changed from v5 and why.

---

## What the tool does

You upload the questionnaire, the insight report, and at least one evidence
source. The tool then, for each insight:

1. Binds the claim to the specific table row, chart series or analysis record
   that supports it.
2. Places it in an **evidence tier** describing how well it is actually verified.
3. Scores it across the seven AICF dimensions and computes the ICI.
4. Runs an eleven-point first-layer research QA checklist.
5. Records a `score_trace` explaining every adjustment that produced the number.

Every scored insight still requires named human researcher sign-off. The index is
a governance aid, not a replacement for researcher judgement.

## The seven dimensions

| Dimension | Weight |
|---|---|
| Evidence Strength | 20% |
| Methodological Fit | 15% |
| Triangulation / Consistency | 15% |
| Interpretability | 10% |
| Business Relevance | 15% |
| Actionability | 15% |
| Bias / Risk Control | 10% |

`ICI = weighted score x 20`. Bands: 80+ High Confidence, 60-79 Medium
Confidence, below 60 Low Confidence. Insights that cannot be mapped to the study
are marked Not Scorable.

Weights and thresholds live in `aicf_config.py` and can be recalibrated from a
pilot without touching the scoring code.

## Evidence tiers

This is the part that makes the score defensible. Every insight is placed in one
of five tiers, and **High Confidence requires tier 3 or above**.

| Tier | Meaning |
|---|---|
| 0 | No evidence attached |
| 1 | Narrative note only, no numbers |
| 2 | Numbers stated but not matched to any source |
| 3 | At least one figure matched to an uploaded table, chart or analysis output |
| 4 | Matched and comparative (carries a comparison, base size or significance marker) |

An insight cannot reach High Confidence because it is well written. It has to
have been checked against something.

## What you upload

**Required**

- Questionnaire / QRE: `.docx` or `.txt`
- Insight report: `.csv`, `.xlsx`, `.pptx` or `.docx`

**At least one of**

- Primary data: `.csv`, `.xlsx` or SPSS `.sav`
- Analysis / table output: banner tables, KDA, MaxDiff, Conjoint, Segmentation,
  Brand Funnel or other method output

Insights are never validated from the report alone.

### Insight report columns

Minimum:

```
insight_id, insight_text
```

Recommended:

```
theme, evidence_note
```

`evidence_note` should carry the evidence **for that specific insight** — the
question, the metric, the value and the base. That is what the tool matches
against the source tables. A generic note describing the study does not help any
individual claim.

Optional manual scores, used only when "Use manual evaluator score columns" is
ticked and all seven are present, each 1-5:

```
evidence_strength, methodological_fit, triangulation, interpretability,
business_relevance, actionability, bias_risk
```

## How tables are read

A readable table needs:

- a header row of column labels,
- data rows whose first cell is a label and which carry two or more numbers.

Banner group headings directly above the column labels are read as parent groups,
so comparisons stay within the right banner. Rows whose label contains "base",
"total respondents" or "sample size" are captured as base sizes rather than as
metrics.

Percentages may be written as `62%` or as `0.62`; both are handled.

Charts pasted into PowerPoint as flat images cannot be read. Upload the source
table for those slides. The Diagnostics tab tells you how many slides this
affects.

## Interpreting the output

- **`verification_status`** — whether this claim was checked against a source.
- **`evidence_tier_label`** — how well supported it is.
- **`quality_challenge_flags`** — contradictions, unsupported superlatives,
  overclaims, causal language without a driver model, unverified quoted figures.
- **`qa_*_status`** — PASS / FAIL / REVIEW / N/A per first-layer check.
- **`score_trace`** — the audit line for the number.
- **`how_to_increase_score`** — the concrete next step.

A **contradiction** means the tool found the claimed option in the source and
another option scored higher (or lower, for a "lowest" claim). Treat these as
report errors to fix, not as scores to argue with.

## Context advisories

Heuristic mismatches between your selections and your files are shown as
advisories, not refusals. Either tick "I confirm these files all belong to the
same study" and re-run, or continue without confirming — context alignment is
reduced and confidence drops accordingly. The tool will not refuse to score a
valid study because its vocabulary is outside the built-in lexicons.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Run the tests:

```bash
pytest -q
```

## Deploy on Streamlit Community Cloud

1. Push every file in this folder to a GitHub repository, including
   `.streamlit/config.toml`. Do not commit `__pycache__`.
2. In Streamlit Community Cloud, select the repository.
3. Set the main file path to `app.py`.
4. Deploy.

Upload size is capped at 300 MB in `.streamlit/config.toml`. Community Cloud
provides roughly 1 GB of RAM per app, so raising this risks memory exhaustion
mid-run.

## Project layout

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI and orchestration |
| `aicf_config.py` | Dimensions, weights, thresholds, taxonomy, lexicons |
| `aicf_framework.py` | Scoring engine, evidence tiers, ICI |
| `aicf_evidence.py` | Table and chart parsing, metric-to-insight binding |
| `aicf_context_gate.py` | Blockers vs advisories |
| `aicf_qa.py` | First-layer research QA checklist |
| `aicf_exports.py` | Excel and Word exports |
| `analysis_validators.py` | KDA / MaxDiff / conjoint / segmentation validators |
| `chart_qa_agent.py` | PowerPoint chart and table QA |
| `ppt_insight_reader.py` | Slide-by-slide insight extraction |
| `ppt_exporter.py` | PowerPoint export |
| `insight_generator.py` | Questionnaire and SPSS reading |
| `tests/test_aicf.py` | Regression tests |

## Suggested pilot use

For each study, compare the ICI classification with senior researcher judgement,
record where they disagree, and recalibrate. Two things are worth tracking
separately: whether the **tier** is right (did the tool find the evidence that
exists?) and whether the **score** is right given the tier. They fail for
different reasons and need different fixes.
