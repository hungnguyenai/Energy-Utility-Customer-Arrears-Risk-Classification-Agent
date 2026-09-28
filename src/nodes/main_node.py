"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict (return ONLY changed keys)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - S-1 trust declared via required_trust_level ClassVar (collections/customer-ops staff)

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import (
    ANSWERED,
    NO_MATCH,
    classify_tier,
    recommend_intervention,
    retrieve_policies,
)

from shared.utils.audit_logger import emit_trace_event


class MainNode(FunctionNode):
    """PolicyRetrieve + TierClassify.

    Retrieves applicable METI arrears-handling guideline / internal collections
    policy passages for the arrears case (a case may match multiple risk-tier
    policies at once — the ambiguous-signal case), classifies the case into a
    risk tier (hardship/dispute/chronic/fraud) with rationale — fail-safe
    toward `hardship` on any ambiguous signal — and recommends the next
    intervention. `retrieved_policies` is written once here — NON-SUPPRESSIBLE
    (the citation trail); downstream nodes must never filter or empty it.

    The injected kb_client (production) or the deterministic corpus (CI) is
    used. If it yields no matched policy, return a `NO_MATCH` disposition and
    NEVER an affirmative classification without grounding.

    S-1: INTERNAL.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def __init__(self, kb_client: Any = None) -> None:
        super().__init__()
        self._kb_client = kb_client

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value):
            return {}

        emit_trace_event("policy_retrieve_start", {"node": "MainNode"}, state)

        query = state.get("sanitized_case_notes") or state.get("validated_input") or ""

        try:
            policies = retrieve_policies(query, kb_client=self._kb_client)
        except Exception as e:  # noqa: BLE001
            emit_trace_event("policy_retrieve_error", {"error": str(e)}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", []) + [f"MainNode: {e}"],
            }

        # Readiness gate: no matched policy must never affirm a risk-tier
        # classification — force NO_MATCH rather than a fabricated tier.
        if not policies:
            emit_trace_event("no_policy_match", {"query_length": len(query)}, state)
            return {
                "disposition": NO_MATCH,
                "retrieved_policies": [],
                "kb_version_manifest": [],
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", [])
                + [
                    "MainNode: no_policy_match — no applicable METI arrears-handling guideline "
                    "or internal collections policy matched this case; cannot classify a risk "
                    "tier without policy grounding"
                ],
            }

        for p in policies:
            emit_trace_event(
                "policy_retrieved",
                {
                    "citation": p.get("citation"),
                    "tier": p.get("tier"),
                    "effective_date": p.get("effective_date"),
                    "kb_date": p.get("kb_date"),
                },
                state,
            )

        kb_version_manifest = sorted({f"{p['citation']} ({p['kb_date']})" for p in policies})
        tier, rationale = classify_tier(policies)
        intervention = recommend_intervention(tier)

        emit_trace_event(
            "tier_classify_complete",
            {"risk_tier": tier, "policy_count": len(policies)},
            state,
        )

        return {
            "retrieved_policies": policies,
            "kb_version_manifest": kb_version_manifest,
            "disposition": ANSWERED,
            "risk_tier": tier,
            "classification_rationale": rationale,
            "recommended_intervention": intervention,
            "status": AgentStatus.SUCCESS.value,
        }
