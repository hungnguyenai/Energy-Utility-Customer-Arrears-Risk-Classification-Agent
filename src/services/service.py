"""AgentCore Platform v1.0"""

# Deterministic offline arrears-handling policy corpus + reasoning core for
# ENE-C2-072.
#
# Electricity/gas arrears risk-tier classification: given an account note
# history + arrears data (free text), the agent retrieves the applicable METI
# arrears-handling guideline / internal collections policy and classifies the
# case into a risk tier (hardship / dispute / chronic / fraud) with rationale,
# then recommends the appropriate next intervention. Fail-safe: any ambiguous
# signal is classified toward `hardship` — the regulatory risk this template
# exists to reduce is misrouting a hardship customer into collections.
#
# This module is the deterministic, fully CI-safe offline core: no external
# dependency, no live API. In production the retrieval below is replaced by an
# injected versioned `kb_client` (same `retrieve(query) -> list[dict]`
# interface); absent, retrieval falls back to the corpus below. If an injected
# kb_client yields nothing, callers must surface a `NO_MATCH` disposition (see
# MainNode) rather than an affirmative classification. Only policy citations +
# snippets are ever stored — never customer PII or source-system credentials (S-5).

from __future__ import annotations

from typing import Any, Optional, cast

# Snapshot version of the bundled arrears-handling policy corpus.
# In production the injected kb_client supplies the real per-source version.
KB_VERSION = "2026-07-01"

# Disposition labels (single source of truth).
ANSWERED = "ANSWERED"
NO_MATCH = "NO_MATCH"

# Risk tiers (single source of truth).
TIER_HARDSHIP = "hardship"
TIER_DISPUTE = "dispute"
TIER_CHRONIC = "chronic"
TIER_FRAUD = "fraud"

# Versioned arrears-handling policy corpus. Each passage carries a citation id,
# the risk tier it governs, the effective date, the jurisdiction, the KB
# snapshot date, and a snippet.
POLICY_KB: list[dict[str, Any]] = [
    {
        "citation": "METI-ARREARS-2026-03",
        "tier": TIER_HARDSHIP,
        "regime": "METI Arrears Handling Guideline — Hardship Customer Protection",
        "effective_date": "2026-03-01",
        "jurisdiction": "Japan",
        "kb_date": KB_VERSION,
        "snippet": "METI's arrears-handling guideline requires retailers to offer an extended or "
        "adjusted payment plan, and to defer any disconnection or collections escalation, for "
        "customers showing signs of financial hardship (経済的困窮者への配慮), before any "
        "collections action is taken.",
    },
    {
        "citation": "METI-DISCONNECT-2025-10",
        "tier": TIER_DISPUTE,
        "regime": "METI Arrears Handling Guideline — Disconnection Notice & Billing Dispute",
        "effective_date": "2025-10-01",
        "jurisdiction": "Japan",
        "kb_date": KB_VERSION,
        "snippet": "Where a customer disputes a charge or meter reading (需要家からの異議申立て), the "
        "retailer must investigate and resolve the billing dispute before proceeding with any "
        "disconnection notice or collections escalation.",
    },
    {
        "citation": "INTERNAL-COLLECT-2025-12",
        "tier": TIER_CHRONIC,
        "regime": "Internal Collections Policy — Chronic Non-Payment Escalation Criteria",
        "effective_date": "2025-12-01",
        "jurisdiction": "Internal",
        "kb_date": KB_VERSION,
        "snippet": "A case may be escalated to collections only after repeated missed payment-plan "
        "instalments or sustained non-response to contact attempts over multiple billing cycles, "
        "and only once hardship and dispute have been ruled out; escalation always requires human "
        "confirmation before any collections action is taken.",
    },
    {
        "citation": "INTERNAL-FRAUD-2026-01",
        "tier": TIER_FRAUD,
        "regime": "Internal Policy — Suspected Meter Tampering / Fraud Investigation Referral",
        "effective_date": "2026-01-01",
        "jurisdiction": "Internal",
        "kb_date": KB_VERSION,
        "snippet": "A case showing signs of meter tampering, an unauthorized/bypassed connection, or "
        "suspected fraudulent account use must be referred to the fraud investigation team and "
        "must NOT be routed through the standard collections process.",
    },
]

# ── keyword lexicons (deterministic retrieval + risk-tier classification) ───

_HARDSHIP_INDICATORS = (
    "hardship",
    "financial difficulty",
    "financial hardship",
    "unemployed",
    "lost my job",
    "low income",
    "on welfare",
    "can't afford",
    "cannot afford",
    "struggling to pay",
    "medical emergency",
    "生活困窮",
    "支払い困難",
    "経済的困窮",
)
_DISPUTE_INDICATORS = (
    "billing error",
    "incorrect bill",
    "disputes the charge",
    "disputing the charge",
    "wrong meter reading",
    "overcharged",
    "billing dispute",
    "meter reading error",
    "請求誤り",
    "検針ミス",
    "異議申立て",
)
_CHRONIC_INDICATORS = (
    "repeated missed payments",
    "multiple broken payment plans",
    "chronic non-payment",
    "no response to contact",
    "months overdue",
    "long-standing arrears",
    "missed several payment plans",
    "延滞が続いている",
    "支払い計画不履行",
)
_FRAUD_INDICATORS = (
    "meter tampering",
    "bypassed meter",
    "unauthorized connection",
    "suspected fraud",
    "stolen electricity",
    "illegal connection",
    "tampered meter",
    "メーター改ざん",
    "不正使用",
    "不正接続",
)

_TIER_ROUTING: list[tuple[str, tuple[str, ...]]] = [
    (TIER_HARDSHIP, _HARDSHIP_INDICATORS),
    (TIER_DISPUTE, _DISPUTE_INDICATORS),
    (TIER_CHRONIC, _CHRONIC_INDICATORS),
    (TIER_FRAUD, _FRAUD_INDICATORS),
]

# Deterministic unredacted-PII / raw-account-number screen (phrase/label based,
# NOT digit-shape based — a digit-shape check would be silently defeated or
# fabricated by the framework's own built-in S-2 PII masker, which runs before
# this domain gate ever sees the input; see the masking-survivability defect class).
# Case notes must arrive already redacted per collections-handling policy; an
# explicit raw-PII label indicates the caller pasted unredacted customer data.
_UNREDACTED_PII_MARKERS = (
    "ssn:",
    "social security number",
    "credit card number",
    "card number:",
    "cvv:",
    "full account number",
    "date of birth:",
    "dob:",
    "driver's license",
    "passport number",
)


def is_unredacted_pii(text: str) -> bool:
    """Deterministic phrase/label screen for unredacted customer PII in case notes."""
    t = (text or "").lower()
    return any(marker in t for marker in _UNREDACTED_PII_MARKERS)


def retrieve_policies(query: str, kb_client: Optional[Any] = None) -> list[dict[str, Any]]:
    """Return arrears-handling policy passages relevant to the query, across all tiers.

    Production: defer to the injected versioned kb_client (template-owned
    approved-corpus index). Offline/CI: deterministic keyword-matched corpus
    above. A query may match multiple tier lexicons at once (ambiguous case);
    classify_tier() below applies the fail-safe-toward-hardship rule.
    Only citations + snippets are returned — never customer PII.
    """
    if kb_client is not None:
        return cast("list[dict[str, Any]]", kb_client.retrieve(query))

    t = (query or "").lower()
    matched_tiers = {tier for tier, keywords in _TIER_ROUTING if any(k in t for k in keywords)}
    if not matched_tiers:
        return []
    return [p for p in POLICY_KB if p["tier"] in matched_tiers]


def classify_tier(policies: list[dict[str, Any]]) -> tuple[str, str]:
    """Classify the case's risk tier from the retrieved policy set.

    Fail-safe rule: if `hardship` is among the matched tiers at all — even
    alongside other tiers — the case is classified `hardship`. This is
    deliberate: the regulatory risk this template exists to reduce is
    misrouting a hardship customer into collections, so any hardship signal
    takes precedence over an ambiguous or competing chronic/dispute/fraud
    signal. Only when `hardship` is absent AND more than one other tier is
    matched (a genuinely ambiguous case) does the classifier still fail safe
    toward `hardship` rather than guess. A single unambiguous non-hardship
    match is classified as that tier.
    """
    matched = {p["tier"] for p in policies}

    if TIER_HARDSHIP in matched:
        rationale = (
            "Classified HARDSHIP: hardship indicators present in the case notes "
            "(fail-safe — any hardship signal takes precedence over a competing "
            "dispute/chronic/fraud signal per METI-ARREARS-2026-03)."
        )
        return TIER_HARDSHIP, rationale

    if len(matched) >= 2:
        rationale = (
            f"Ambiguous case — matched tiers {sorted(matched)} without a hardship signal; "
            "fail-safe default to HARDSHIP rather than guessing between competing tiers, "
            "per METI-ARREARS-2026-03."
        )
        return TIER_HARDSHIP, rationale

    tier = next(iter(matched))
    rationale = f"Classified {tier.upper()}: unambiguous {tier} indicators present in the case notes."
    return tier, rationale


_RECOMMENDATIONS = {
    TIER_HARDSHIP: (
        "Hardship intervention: offer an extended or adjusted payment plan; do NOT escalate "
        "to collections or disconnection while hardship status stands."
    ),
    TIER_DISPUTE: (
        "Billing review: route to the billing dispute review team; hold any disconnection "
        "or collections escalation until the dispute is resolved."
    ),
    TIER_CHRONIC: (
        "Collections-eligible candidate: this case may proceed toward collections escalation, "
        "but ONLY after human confirmation — no automated collections/disconnection action."
    ),
    TIER_FRAUD: (
        "Investigation referral: route to the fraud/meter-tampering investigation team; do "
        "NOT process through the standard collections workflow."
    ),
}


def recommend_intervention(tier: str) -> str:
    """Deterministic next-intervention recommendation for the classified tier."""
    return _RECOMMENDATIONS[tier]
