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

from shared.utils.audit_logger import emit_trace_event

# Credential-like patterns rejected in output (additive to the default scan).
_SENSITIVE_PATTERNS = (
    "bearer ",
    "authorization:",
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "connection_string",
    "conn_str",
)

# Unredacted customer PII / raw-account-number labels must never leak into the
# assembled recommendation (mirrors the pre_process UnredactedPIIScreen labels).
_PII_LEAK_PATTERNS = (
    "ssn:",
    "social security number",
    "credit card number",
    "card number:",
    "cvv:",
    "full account number",
    "date of birth:",
    "dob:",
)

# Unsupported-certainty phrasing the recommendation must NOT assert. This
# agent produces an informational risk-tier classification + recommended next
# intervention, never a final/binding collections or disconnection decision.
_UNSUPPORTED_CERTAINTY_PATTERNS = (
    "guaranteed collections outcome",
    "final collections decision",
    "legally binding determination",
    "certified for disconnection",
    "this is a final decision",
    "no further review is required",
)

# RecommendAssemble — a "collections-eligible" recommendation MUST always be
# paired with an explicit human-confirmation requirement (never an
# automatically actionable collections determination).
_COLLECTIONS_ELIGIBLE_MARKER = "collections-eligible"
_HUMAN_CONFIRM_MARKER = "human confirmation"

# ResponseValidate — an assembled recommendation MUST retain a policy citation
# marker so it stays grounded in the policy passages it cites.
_CITATION_MARKERS = ("METI-ARREARS-", "METI-DISCONNECT-", "INTERNAL-COLLECT-", "INTERNAL-FRAUD-", "KB version")

# The non-suppressible informational notice appended to every classified response.
_DISCLAIMER = (
    "\n\n---\n**This is an informational risk-tier classification and recommended next "
    "intervention, not a final collections/disconnection decision.** Any collections-eligible "
    "outcome requires human confirmation before action is taken."
)

# Sentinel used when disposition is NO_MATCH (no grounding to check).
_NO_MATCH_SENTINEL = "no_policy_match"

# Rendered when there is no classification to validate (e.g. main_node never
# ran, or was invoked directly with a degenerate state). The grounding check
# below is skipped for this sentinel — there is nothing to cite.
_NO_ANSWER_SENTINEL = "No risk-tier classification synthesized"


class PostProcessNode(FunctionNode):
    """RecommendAssemble + OutputValidate (S-3) + DecisionTraceAudit (S-4).

    Responsibilities:
    - Append the non-suppressible "informational — requires human confirmation"
      notice to every classified response.
    - S-3: block credential-like patterns; block unredacted-PII leakage; block
      unsupported certainty phrasing; block a "collections-eligible" outcome
      that is not paired with an explicit human-confirmation requirement;
      ResponseValidate rejects a recommendation that carries no policy
      citation (grounding requirement).
    - S-4: emit_trace_event audit record — risk tier, KB source/version
      manifest, citation count, disposition; no PII/credentials.

    S-1: INTERNAL.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("status") in (AgentStatus.ERROR, AgentStatus.ERROR.value):
            return {}

        emit_trace_event("output_validate_start", {"node": "PostProcessNode"}, state)

        risk_tier = state.get("risk_tier") or ""
        rationale = state.get("classification_rationale") or ""
        intervention = state.get("recommended_intervention") or ""
        policies = state.get("retrieved_policies") or []
        kb_version_manifest = state.get("kb_version_manifest") or []
        disposition = state.get("disposition") or _NO_MATCH_SENTINEL

        if rationale.strip() and intervention.strip():
            citations = ", ".join(sorted({p.get("citation") for p in policies if p.get("citation")}))
            body = (
                f"Risk tier: {risk_tier.upper()}\n"
                f"Rationale: {rationale}\n"
                f"Recommended intervention: {intervention}\n"
                f"Policy basis: {citations}"
            )
        else:
            body = _NO_ANSWER_SENTINEL

        validated_recommendation = body + _DISCLAIMER
        citation_count = len({p.get("citation") for p in policies if p.get("citation")})

        emit_trace_event(
            "decision_trace_audit",
            {
                "disposition": disposition,
                "risk_tier": risk_tier,
                "kb_version_manifest": kb_version_manifest,
                "citation_count": citation_count,
            },
            state,
        )

        return {
            "validated_recommendation": validated_recommendation,
            "citation_count": citation_count,
            "formatted_output": validated_recommendation,
            "result": validated_recommendation,
            "status": AgentStatus.SUCCESS.value,
        }

    # ── S-3 output gate ────────────────────────────────────────────────────

    def _extra_security_gate_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """S-3 domain hook (runs after the default credential scan).

        Contract (FunctionNode 1.0.0): receive the execute() result dict, RETURN it;
        MAY raise to block output.
        - Block credential-like patterns / connection strings.
        - Block unredacted-PII leakage.
        - Block unsupported-certainty phrasing.
        - Block a "collections-eligible" outcome not paired with an explicit
          human-confirmation requirement.
        - ResponseValidate: a classified recommendation MUST retain a policy
          citation marker (grounding requirement — no unsupported risk-tier claim).
        """
        for key, value in result.items():
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            for pattern in _SENSITIVE_PATTERNS:
                if pattern in lowered:
                    raise RuntimeError(f"PostProcessNode S-3: sensitive pattern '{pattern}' in result['{key}']")
            for pattern in _PII_LEAK_PATTERNS:
                if pattern in lowered:
                    raise RuntimeError(f"PostProcessNode S-3: unredacted-PII pattern '{pattern}' in result['{key}']")
            for pattern in _UNSUPPORTED_CERTAINTY_PATTERNS:
                if pattern in lowered:
                    raise RuntimeError(
                        f"PostProcessNode S-3: unsupported-certainty phrasing " f"'{pattern}' in result['{key}']"
                    )
            if _COLLECTIONS_ELIGIBLE_MARKER in lowered and _HUMAN_CONFIRM_MARKER not in lowered:
                raise RuntimeError(
                    "PostProcessNode S-3: a collections-eligible outcome must be paired with an "
                    "explicit human-confirmation requirement"
                )

        recommendation = result.get("validated_recommendation")
        if isinstance(recommendation, str) and recommendation.strip() and _NO_ANSWER_SENTINEL not in recommendation:
            if not any(marker in recommendation for marker in _CITATION_MARKERS):
                raise RuntimeError(
                    "PostProcessNode S-3 ResponseValidate: recommendation carries no policy "
                    "citation — blocking unsupported risk-tier classification claim"
                )
        return result
