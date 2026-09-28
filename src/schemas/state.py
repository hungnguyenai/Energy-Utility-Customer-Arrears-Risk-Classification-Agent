"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict (see ADR-005 for the prohibited alternatives).
# LangGraph checkpoints use msgpack serialization; non-flat objects cause silent
# corruption. Extend AgentState with agent-specific fields only. Do NOT add
# credentials, secrets, or other non-flat objects.

from typing import Optional

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """State for ENE-C2-072 Energy Utility Customer Arrears Risk Classification Agent.

    Inherited fields from AgentState (do not re-declare):
      user_input, status, session_id, node_history, error_log,
      validated_input, hitl_*, trace_id, correlation_id, schema_version,
      response_metadata, trust_level, formatted_output, result

    An arrears case (account note history + arrears data, free text) arrives as
    user_input. All fields below are flat, msgpack-safe primitives (ADR-005) — no
    credentials, no connection strings. Only policy citations + snippets are
    retained; unredacted customer PII must never reach this state (rejected at
    pre_process before it is stored).
    """

    # ── pre_process outputs (InputValidate + UnredactedPIIScreen) ────────
    sanitized_case_notes: Optional[str]
    # True when the case notes were rejected for containing unredacted PII /
    # raw account numbers (domain S-2 gate) instead of the required redacted form.
    pii_reject_flagged: Optional[bool]

    # ── main outputs (PolicyRetrieve + TierClassify) ─────────────────────
    # Retrieved policy passages: {citation, tier, effective_date, jurisdiction, kb_date, snippet}.
    # NON-SUPPRESSIBLE citation trail — downstream nodes must never empty it (a
    # recommendation must stay grounded in the policy basis it cites).
    retrieved_policies: Optional[list[dict[str, str | int | float | bool | None]]]
    # Versioned KB manifest — one entry per policy source cited (S-4 audit + data-currency).
    kb_version_manifest: Optional[list[str]]
    # ANSWERED | NO_MATCH — NO_MATCH forces a "no applicable policy found" reply,
    # never an affirmative classification without grounding.
    disposition: Optional[str]
    # hardship | dispute | chronic | fraud — fail-safe toward hardship on ambiguity.
    risk_tier: Optional[str]
    # Draft rationale + recommendation (pre-S-3) — tier + policy basis + intervention.
    classification_rationale: Optional[str]
    recommended_intervention: Optional[str]

    # ── post_process outputs (RecommendAssemble + OutputValidate S-3 + S-4) ─
    validated_recommendation: Optional[str]  # final recommendation incl. human-confirm notice
    citation_count: Optional[int]  # number of distinct policy citations in the recommendation
