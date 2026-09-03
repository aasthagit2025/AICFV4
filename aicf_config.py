"""Single source of truth for AICF dimensions, thresholds and taxonomies.

Everything that used to be duplicated across app.py, aicf_framework.py and
ppt_insight_reader.py now lives here. Editing a lexicon in one place changes
the whole application.

Design rule enforced by tests/test_aicf.py: no organisation-specific or
study-specific vocabulary is allowed in this file. Lexicons describe *market
research method vocabulary*, never a particular client, brand or project.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# AICF dimensions and weights (unchanged from the published framework)
# ---------------------------------------------------------------------------

DIMENSIONS: dict[str, dict[str, object]] = {
    "evidence_strength": {
        "label": "Evidence Strength",
        "weight": 0.20,
        "low_score_action": "Add stronger source support, base size, or a traceable table/chart reference.",
    },
    "methodological_fit": {
        "label": "Methodological Fit",
        "weight": 0.15,
        "low_score_action": "Check whether the claim fits the research objective and the method that produced it.",
    },
    "triangulation": {
        "label": "Triangulation / Consistency",
        "weight": 0.15,
        "low_score_action": "Compare against another data source, banner cut, wave, or independent analyst read.",
    },
    "interpretability": {
        "label": "Interpretability",
        "weight": 0.10,
        "low_score_action": "Make the reasoning path clearer and quantify vague wording.",
    },
    "business_relevance": {
        "label": "Business Relevance",
        "weight": 0.15,
        "low_score_action": "Connect the insight more directly to a decision the organisation has to make.",
    },
    "actionability": {
        "label": "Actionability",
        "weight": 0.15,
        "low_score_action": "Translate the insight into a practical recommendation or next step.",
    },
    "bias_risk": {
        "label": "Bias / Risk Control",
        "weight": 0.10,
        "low_score_action": "Review for overclaiming, sampling bias, or unsupported causality.",
    },
}

REQUIRED_COLUMNS = ["insight_id", "insight_text"]
MANUAL_SCORE_COLUMNS = list(DIMENSIONS.keys())

DIMENSION_MAX_POINTS = {
    key: int(round(float(item["weight"]) * 100)) for key, item in DIMENSIONS.items()
}

# ICI band thresholds, exposed so a pilot can recalibrate them without a code change.
ICI_HIGH_THRESHOLD = 80.0
ICI_MEDIUM_THRESHOLD = 60.0

CLASSIFICATIONS = ["High Confidence", "Medium Confidence", "Low Confidence", "Not Scorable"]


# ---------------------------------------------------------------------------
# Evidence tiers - the backbone of the rebuilt scoring model
# ---------------------------------------------------------------------------
# An insight can never score above its evidence tier on Evidence Strength.
# This is what makes the ICI defensible: the number is bounded by what was
# actually verified, not by how confident the wording sounds.

EVIDENCE_TIERS = {
    0: ("No evidence", "No evidence note, no matched table, no matched chart."),
    1: ("Narrative only", "A qualitative evidence note exists but carries no numbers."),
    2: ("Numbers stated", "Numbers are quoted in the insight or note but were not matched to a source."),
    3: ("Numbers matched", "At least one quoted metric was matched to an uploaded table, chart or analysis output."),
    4: ("Matched and comparative", "Matched to source AND carries a comparison, base size, or significance marker."),
}

TIER_TO_EVIDENCE_SCORE = {0: 1, 1: 2, 2: 3, 3: 4, 4: 5}


# ---------------------------------------------------------------------------
# Taxonomy - deduplicated
# ---------------------------------------------------------------------------
# v5 offered "Key Driver Analysis" AND "KDA / Driver Analysis", plus "Conjoint",
# "MaxDiff" AND "Conjoint / MaxDiff". Selecting one variant made the validator
# look for the other variant's keywords and hard-fail. Canonical names below,
# with aliases so previously saved CSVs still load.

STUDY_TYPES = [
    "Customer Satisfaction / NPS",
    "Brand Tracker",
    "Concept / Message Test",
    "Segmentation",
    "Correspondence Analysis",
    "Text Analytics",
    "Conjoint",
    "MaxDiff",
    "Usage and Attitude",
    "Other Market Research Study",
]

ANALYTICAL_TECHNIQUES = [
    "Descriptive / Banner Tables",
    "KPI Measurement Table",
    "KDA / Driver Analysis",
    "Segmentation",
    "Brand Tracking",
    "Brand Funnel",
    "CSAT / NPS",
    "Unmet Needs Exploration",
    "Usage and Attitude Behaviour",
    "Text Analytics",
    "Correspondence Analysis",
    "Conjoint",
    "MaxDiff / TURF",
    "PowerPoint Report Review",
]

TAXONOMY_ALIASES = {
    "Customer Satisfaction": "Customer Satisfaction / NPS",
    "Concept Test": "Concept / Message Test",
    "Conjoint / MaxDiff": "Conjoint",
    "Usage and Attitude Study": "Usage and Attitude",
    "Usage and Attitude Behaviour Study": "Usage and Attitude Behaviour",
    "Key Driver Analysis": "KDA / Driver Analysis",
    "MaxDiff": "MaxDiff / TURF",
}

INDUSTRIES = [
    "Automotive",
    "BFSI",
    "Consumer Goods / FMCG",
    "E-commerce / Retail",
    "Education",
    "Healthcare / Pharma",
    "Media / Entertainment",
    "Real Estate",
    "Technology / SaaS",
    "Telecom",
    "Travel / Hospitality",
    "Other",
]

DATA_ENVIRONMENTS = [
    "Survey data",
    "SPSS data",
    "Excel / CSV tables",
    "Banner tables",
    "PowerPoint report",
    "Text analytics output",
    "Conjoint / MaxDiff output",
    "Dashboard / BI output",
    "Other",
]

INSIGHT_SOURCES = ["AI", "Human", "Human + AI"]


def canonical(value: str) -> str:
    """Map a legacy taxonomy label to its canonical name."""
    return TAXONOMY_ALIASES.get(str(value).strip(), str(value).strip())


def canonical_list(values) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        name = canonical(value)
        if name and name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# Lexicons - method vocabulary only
# ---------------------------------------------------------------------------

STUDY_TYPE_KEYWORDS = {
    "Customer Satisfaction / NPS": [
        "satisfaction", "satisfied", "dissatisfied", "csat", "nps", "promoter",
        "detractor", "passive", "complaint", "resolution", "service", "experience",
        "loyalty", "advocacy", "recommend", "rating", "top box", "top-two-box",
    ],
    "Brand Tracker": [
        "awareness", "consideration", "usage", "preference", "familiarity", "recall",
        "brand", "funnel", "equity", "perception", "image", "wave", "tracker", "salience",
    ],
    "Concept / Message Test": [
        "concept", "message", "appeal", "fit", "purchase intent", "intent",
        "believability", "uniqueness", "relevance", "clarity", "trial", "monadic",
        "likeability", "diagnostics", "stimulus",
    ],
    "Segmentation": [
        "segment", "cluster", "profile", "persona", "segment size", "attractiveness",
        "needs", "attitudes", "typology", "differentiating",
    ],
    "Correspondence Analysis": [
        "correspondence", "perceptual map", "map", "association", "attribute",
        "proximity", "dimension", "inertia", "quadrant",
    ],
    "Text Analytics": [
        "verbatim", "open-ended", "open ended", "theme", "coding", "sentiment",
        "mentions", "text", "qualitative", "topic",
    ],
    "Conjoint": [
        "conjoint", "cbc", "utility", "utilities", "attribute", "level",
        "importance", "preference share", "simulation", "part-worth",
    ],
    "MaxDiff": [
        "maxdiff", "best worst", "best-worst", "item score", "relative importance",
        "rank", "turf", "reach",
    ],
    "Usage and Attitude": [
        "usage", "attitude", "behaviour", "behavior", "frequency", "occasion",
        "need", "habit", "category", "user", "non-user", "penetration",
    ],
    "Other Market Research Study": ["survey", "respondent", "sample", "questionnaire", "base"],
}

TECHNIQUE_KEYWORDS = {
    "Descriptive / Banner Tables": ["table", "banner", "crosstab", "cross-tab", "total", "base", "column %"],
    "KPI Measurement Table": ["kpi", "metric", "score", "top box", "mean", "base", "index"],
    "KDA / Driver Analysis": ["driver", "importance", "coefficient", "performance", "dependent", "regression", "shapley"],
    "Segmentation": ["segment", "cluster", "profile", "persona", "segment size"],
    "Brand Tracking": ["awareness", "consideration", "usage", "preference", "wave", "tracker"],
    "Brand Funnel": ["funnel", "awareness", "consideration", "trial", "usage", "conversion"],
    "CSAT / NPS": ["csat", "satisfaction", "nps", "promoter", "detractor", "recommend"],
    "Unmet Needs Exploration": ["unmet", "need", "demand", "gap", "desired", "priority"],
    "Usage and Attitude Behaviour": ["usage", "attitude", "behaviour", "behavior", "frequency", "occasion"],
    "Text Analytics": ["verbatim", "open-ended", "theme", "coding", "sentiment", "topic"],
    "Correspondence Analysis": ["correspondence", "map", "association", "proximity", "perceptual", "inertia"],
    "Conjoint": ["conjoint", "cbc", "utility", "attribute", "level", "simulation", "preference share"],
    "MaxDiff / TURF": ["maxdiff", "best worst", "best-worst", "rank", "item score", "turf", "reach"],
    "PowerPoint Report Review": ["slide", "powerpoint", "executive summary", "key takeaway"],
}

INDUSTRY_KEYWORDS = {
    "Automotive": ["automotive", "car", "vehicle", "dealer", "ev", "mobility"],
    "BFSI": ["bank", "financial", "insurance", "loan", "credit", "account", "investment", "premium"],
    "Consumer Goods / FMCG": ["fmcg", "consumer", "pack", "food", "beverage", "household", "sku"],
    "E-commerce / Retail": ["ecommerce", "e-commerce", "retail", "shopping", "cart", "store", "delivery", "basket"],
    "Education": ["education", "student", "school", "college", "learning", "course", "faculty"],
    "Healthcare / Pharma": ["health", "healthcare", "pharma", "patient", "physician", "treatment", "therapy"],
    "Media / Entertainment": ["media", "entertainment", "streaming", "content", "ott", "viewer", "audience"],
    "Real Estate": ["real estate", "property", "tenant", "occupant", "building", "lease", "facility", "amenities"],
    "Technology / SaaS": ["technology", "software", "saas", "platform", "app", "digital", "cloud"],
    "Telecom": ["telecom", "network", "operator", "data pack", "sim", "broadband", "tariff"],
    "Travel / Hospitality": ["travel", "hotel", "hospitality", "flight", "booking", "guest", "itinerary"],
    "Other": [],
}

# Generic wording cues, used to decide whether a sentence is a research claim.
INSIGHT_CUES = [
    "outperform", "drives", "stronger", "higher", "lower", "most", "least", "clearly",
    "leads", "lags", "trails", "winning", "winner", "weaker", "weakest", "lift",
    "indicates", "suggests", "validates", "reinforces", "prefer", "preference",
    "satisfied", "satisfaction", "loyal", "advocacy", "intent", "recall", "appeal",
    "awareness", "consideration", "conversion", "perception", "demand", "unmet",
    "gap", "opportunity", "priority", "friction", "pain point", "improvement",
    "significantly", "compared", "versus", "rated", "ranks", "share",
]

# Slide furniture and boilerplate that should never be scored as an insight.
# SUBSTRING cues: safe to match anywhere in the text. Every entry must be long
# and distinctive enough that it cannot occur inside an ordinary research
# sentence. Short fragments belong in NON_INSIGHT_EXACT below.
NON_INSIGHT_CUES = [
    "prepared for", "prepared by", "sample size", "qualifying criteria",
    "methodology", "target audience", "appendix", "thank you", "agenda",
    "table of contents", "confidential", "disclaimer", "significance testing",
    "uppercase letters", "lowercase letters", "chart series:",
    "copyright", "all rights reserved", "background and objectives",
]

# EXACT cues: matched against the whole cleaned string, never as a substring.
# v5 (and the first v6 build) put "x", "xx" and "n=" in the substring list,
# which silently discarded every insight containing the letter x ("next",
# "experience", "index", "context", "complexity") and every insight quoting a
# base size ("n=347"). The best-evidenced insights were the most likely to be
# lost, and nothing reported the loss.
NON_INSIGHT_EXACT = [
    "x", "xx", "xxx", "-", "--", "n/a", "na", "tbc", "tbd", "note", "notes",
    "base", "total", "source", "q", "yes", "no",
]

# Wording that asserts a ranked or superlative outcome. Such claims must be
# matched to comparative numbers or they are capped.
DECISIVE_CLAIM_TERMS = [
    "winner", "winning", "most effective", "best", "strongest", "highest",
    "leader", "leading", "leads", "outperforms", "most credible", "most convincing",
    "most preferred", "top concept", "top message", "most recalled", "most noticeable",
    "lowest", "least", "weakest", "worst", "trails", "lags behind",
]

CONTRADICTORY_EVIDENCE_TERMS = [
    "bottom", "lowest", "least", "weaker", "weakest", "underperform", "trails",
    "lags", "lower than", "declines", "not effective", "less effective",
    "not significant", "no significant", "insignificant", "at parity", "parity",
    "below benchmark", "below average", "does not lead",
]

COMPARATIVE_EVIDENCE_TERMS = [
    "vs", "versus", "compared", "higher than", "lower than", "significantly",
    "95%", "90%", "top box", "rank", "ranking", "highest", "lowest",
    "outperforms", "leads", "trails", "benchmark", "index",
]

OVERCLAIM_TERMS = [
    "all customers", "everyone", "every customer", "always", "never",
    "fully satisfied", "no improvement required", "completely", "guarantees",
    "proves", "definitively",
]

CAUSAL_TERMS = ["caused by", "main reason", "primary cause", "only reason", "because of", "leads to", "drives"]

CAUSAL_METHOD_TERMS = ["driver", "regression", "kda", "shapley", "key driver", "structural equation", "causal"]

ACTION_TERMS = [
    "should", "priority", "improve", "focus", "recommend", "opportunity",
    "strengthen", "investigate", "invest", "reduce", "launch", "target",
    "optimise", "optimize", "address", "protect",
]

HEDGE_TERMS = ["may", "suggest", "indicates", "appears", "directional", "hypothesis", "should be interpreted"]

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "each", "study",
    "research", "insight", "insights", "report", "data", "analysis", "output",
    "client", "business", "market", "validate", "validation", "evidence",
    "are", "you", "your", "who", "any", "other", "than", "them", "under", "was",
    "were", "have", "has", "been", "their", "there", "these", "those", "also",
}

APP_VERSION = "AICF v6.0 - evidence-bound scoring, 2026-08-30"
