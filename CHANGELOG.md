# AICF Tool - changes from v5 to v6

Every change below is either a correctness fix with a reproducible symptom, or a
structural change made to prevent that class of fault recurring. The seven
dimensions, their weights, the ICI arithmetic (`weighted score x 20`) and the
80 / 60 band thresholds are unchanged.

---

## 1. Critical scoring faults

### 1.1 Sidebar selections inflated every score

**Symptom.** The same insight scored differently depending on which study type
was chosen in the sidebar, with no change to the insight or its evidence:

| Input | v5 ICI | v5 band |
|---|---|---|
| Vacuous insight, nothing selected | 56.0 | Low Confidence |
| Same insight, study type = Customer Satisfaction | 69.0 | Medium Confidence |
| Same insight + the app's own file-summary string | 80.0 | **High Confidence** |

**Cause.** `auto_dimension_scores` built one `study_context` string by
concatenating the insight, its evidence, and the sidebar values. Detectors such
as `satisfaction_report_context` matched the dropdown value itself and then
applied floors of the form `scores[key] = max(scores[key], 4)`. Selecting
"Customer Satisfaction" therefore lifted five of the seven dimensions to at
least 4/5 for every row in the study.

**Fix.** Study context now selects *which lexicon to apply* and never awards
points. All `max(score, 4)` floors are removed and replaced with bounded,
evidence-conditional adjustments. Locked by
`test_study_type_selection_does_not_change_the_score`.

### 1.2 One shared evidence blob was counted as every insight's evidence

**Symptom.** All insights in a study received near-identical dimension scores,
so the index stopped discriminating between well- and poorly-supported claims.

**Cause.** `enrich_insight_evidence` appended the same study-level summary
("Questionnaire uploaded... Primary data uploaded: n=347 rows... Additional
analysis uploaded...") to *every* row's `evidence_note`. The scorer then read
that note looking for `n=`, `%`, "respondents" and "survey", found them in every
row, and awarded evidence and triangulation credit to all of them. A separate
check, `has_additional_analysis`, floored Evidence Strength and Triangulation at
4/5 for every row whenever any file was uploaded.

**Fix.** `strip_study_level_context()` removes study-level file summaries before
scoring. Each insight is scored on its own evidence note, its own matched
metrics, and its own chart/analysis validator results. Study context is kept in
separate columns for the audit trail. Locked by
`test_study_level_blob_does_not_inflate_confidence`.

### 1.3 Evidence tiers now bound the score

New concept, and the main reason the number is defensible in the paper. Every
insight is placed in one of five tiers:

| Tier | Meaning |
|---|---|
| 0 | No evidence attached |
| 1 | Narrative note only, no numbers |
| 2 | Numbers stated but not matched to any source |
| 3 | At least one figure matched to an uploaded table, chart or analysis output |
| 4 | Matched **and** comparative (carries a comparison, base size or significance marker) |

Evidence Strength derives directly from the tier, and **High Confidence now
requires tier 3 or above**. An insight cannot be called high-confidence because
it is well written; it has to have been checked against something. The tier is
reported per insight in the `verification_status` and `evidence_tier_label`
columns.

### 1.4 Client-specific vocabulary was hardcoded into generic logic

`auto_dimension_scores` and `dimension_explanations` contained literal strings
from a previous project, including a brand name, and produced explanation text
such as "relevant to ... Prime subscription intent" and "a client action for
Prime communication" for *any* study. `ppt_insight_reader.py` carried a research
agency's name and a building-services word list in its slide-selection cues.

All of it has been removed. Method vocabulary now lives in `aicf_config.py`, and
two tests fail the build if a client-specific term reappears in the config or the
scoring engine.

---

## 2. Faults that stopped studies running at all

### 2.1 The banner-table parser only recognised one vendor's export layout

**Symptom.** Cross-source validation silently found nothing on most studies, so
every comparative claim was flagged "no quantitative comparison table" and capped
at Medium or Low. This is the most likely cause of "issues when I run any type of
study".

**Cause.** `extract_quantitative_metric_records` required the literal strings
`"frequency row"` and `"vertical % row"` in the table. Those markers come from
one tabulation package's export format. The project's own
`sample_table_output.csv` does not contain them, and returns **zero** metric
records.

**Fix.** `aicf_evidence.py` keeps that layout as a fast path and adds a general
parser that recognises the ordinary shape of a research table: a header row of
column labels, an optional base row, and labelled data rows carrying two or more
numeric cells. Banner groups above the header are read as parent labels, so
within-group comparisons still work. Locked by
`test_generic_banner_table_is_parsed`.

### 2.2 Heuristic keyword mismatches were fatal errors with no override

**Symptom.** Valid studies were refused with "Not Scorable: the questionnaire,
data/analysis and insight report cannot be reliably mapped to the same study."

**Cause.** `validate_study_context` raised blocking errors from keyword
heuristics and then called `st.stop()`. One check demanded that at least three
words from the typed objective reappear verbatim in the uploaded files
(`objective_overlap < 3`). The app's own default objective text failed this on
most real studies. Other checks hard-failed when a study's vocabulary was simply
not in the built-in lexicons.

**Fix.** `aicf_context_gate.py` splits checks into **blockers** (missing file,
missing required column, no readable insight rows, no evidence source — all
mechanical and always correct) and **advisories** (everything heuristic).
Advisories are shown, and the researcher either confirms the files belong
together or continues without confirming, in which case context alignment is
reduced and confidence drops. The tool no longer refuses to produce a result on a
keyword guess.

### 2.3 Duplicated taxonomy entries caused self-contradicting validation

The technique list offered "Key Driver Analysis" *and* "KDA / Driver Analysis",
and "Conjoint", "MaxDiff" *and* "Conjoint / MaxDiff". Selecting one variant made
the validator look for the other variant's keywords and fail. The list is now
canonical, with `TAXONOMY_ALIASES` so previously saved CSVs still load.

### 2.4 Undefined names in shipped code

`generate_table_insights_from_uploads` called `read_table_file` and
`generate_insights_from_table`, neither of which was imported anywhere — a
`NameError` waiting to be wired up. That function and the two orphan modules
(`story_generator.py`, `table_insight_generator.py`, imported by nothing) have
been removed.

### 2.5 Short exclude cues silently deleted valid insights

**Symptom.** Insights disappeared from the report with no message. On a
three-slide test deck only one insight was extracted.

**Cause.** `looks_like_question_or_note` tests exclude cues as **substrings**,
and the cue list contained the bare tokens `"x"`, `"xx"` and `"n="`. Any sentence
containing the letter x was discarded — "next", "experience", "index", "context",
"complexity", "explains", "product mix", "we expect", "flexible", "maximum". Any
sentence quoting a base size was discarded too, so the *best-evidenced* insights
were the most likely to be lost.

**Fix.** Exclude cues are split into `NON_INSIGHT_CUES` (long, distinctive,
matched as substrings) and `NON_INSIGHT_EXACT` (short tokens, matched against the
whole string only). The same flaw was present in the Word reader and is fixed
there too. Locked by
`test_short_exclude_cues_are_matched_exactly_not_as_substrings`.

### 2.6 A file supplied twice was parsed twice

A PowerPoint deck is commonly uploaded as both the insight report and the
evidence source, since it carries the claims and the charts. v6 build 1 parsed it
twice and double-counted every chart record. Evidence files are now deduplicated
by content hash, and the skip is reported in Diagnostics.

---

## 7. Sample studies

`samples/` contains two complete, runnable studies with documented expected
results: a concept test delivered as a PowerPoint deck with real editable charts,
and a satisfaction study delivered as CSV plus banner tables. Each includes a
deliberately incorrect insight so you can confirm contradiction detection works
on your deployment. See `samples/README.md`.

---

## 3. Correctness of the QA layer

### 3.1 Number verification produced false PASS results

`number_supported` used a plain substring test, so `"12%"` matched inside
`"112%"` and `"5%"` matched inside `"45%"`. A quoted figure that did not appear
in the evidence could be reported as correct. v6 anchors the match on digit
boundaries. Locked by `test_number_matching_respects_digit_boundaries`.

### 3.2 QA statuses are now data, not prose

v5 stored each check as `"FAIL: ..."` and recovered the status with
`str.startswith("FAIL")`, so any wording change silently broke the roll-up. v6
writes `qa_<check>_status` (PASS / FAIL / REVIEW / N/A) and `qa_<check>_note`
separately, and computes the overall status from the status columns.

`N/A` is new and matters: v5 reported PASS for a numbers check on an insight
quoting no numbers, which inflated the apparent pass rate.

### 3.3 One bad row no longer kills the run

`parse_score` raised inside the scoring loop, so a single malformed manual score
aborted the whole report. Failed rows are now collected and reported, and the
rest of the study still scores.

---

## 4. Performance and deployment

- **Nothing runs until "Run AICF validation" is pressed.** v5 re-parsed every
  file and re-scored every insight on each widget interaction, including each
  keystroke in the objective box. With a large deck or workbook this was the main
  source of slowness and of timeouts on Streamlit Community Cloud.
- **All file parsing is cached** on the file's content hash, so re-running after
  a dropdown change reuses parsed data.
- **Upload cap reduced from 1024 MB to 300 MB.** Community Cloud provides roughly
  1 GB of RAM per app; a 1 GB upload could exhaust memory mid-run.
- **Requirements pinned with upper bounds.** v5 used open-ended `>=` pins, so a
  breaking Streamlit or pandas release could take the deployed app down with no
  repository change. `reportlab` was declared but never used and has been dropped.
- **`__pycache__` removed** from the distribution and added to `.gitignore`.
- Deprecated `use_container_width` migrated to `width="stretch"`.

---

## 5. Usability

- **Results are tabbed**: Summary, Insights, First-layer QA, Evidence trail,
  Diagnostics, Downloads. v5 dumped roughly 60 columns into one table.
- **Per-insight cards** show the seven dimension scores, the verification status,
  the weakest dimensions, the root cause and the improvement action.
- **A Diagnostics tab reports what the parser found in each file** — how many
  metric rows, how many chart series, how many advanced-analysis records, and why
  a file yielded nothing. When cross-source validation comes back empty you can
  now see the reason instead of guessing.
- **Every score carries a `score_trace`** recording each adjustment that produced
  it. For a framework whose argument is auditability, the number should be
  explainable line by line.
- **Exports**: CSV, multi-sheet Excel (Scores / First-layer QA / Evidence trail /
  Governance / Run settings / Full output), a Word validation summary for
  circulation, and the existing PowerPoint deck.
- Empty-string sidebar defaults replaced with placeholder text, so the tool no
  longer ships a generic default objective that weakens context alignment.

---

## 6. Structure and tests

The 1,916-line `app.py` is split into focused modules:

| Module | Responsibility |
|---|---|
| `aicf_config.py` | Dimensions, weights, thresholds, taxonomy, lexicons |
| `aicf_framework.py` | Scoring engine, evidence tiers, ICI |
| `aicf_evidence.py` | Table and chart parsing, metric-to-insight binding |
| `aicf_context_gate.py` | Blockers vs advisories |
| `aicf_qa.py` | First-layer research QA checklist |
| `aicf_exports.py` | Excel and Word exports |
| `app.py` | UI and orchestration only |

`tests/test_aicf.py` contains 20 tests, each pinning one of the defects above.
Run with `pytest -q`.
