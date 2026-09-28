"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict (return ONLY changed keys)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - S-1 trust declared via required_trust_level ClassVar (collections/customer-ops staff)

from __future__ import annotations

import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import is_unredacted_pii

from shared.utils.audit_logger import emit_trace_event

# Maximum allowed request length (characters)
_MAX_INPUT_LEN = 10_000

_WS = re.compile(r"\s+")

# Out-of-scope / credential-shaped input rejected at the S-2 boundary
# (data-minimisation + scope — NOT an LLM check).
_OUT_OF_SCOPE_MARKERS = (
    "bearer ",
    "authorization:",
    "api_key",
    "connection_string",
    "-----begin",
    "password:",
    "\\\\",  # credential JSON / file-path shaped input
)


class PreProcessNode(FunctionNode):
    """InputValidate + UnredactedPIIScreen — sanitise and screen the arrears case.

    Responsibilities:
    - Reject empty / oversized input
    - S-2 deterministic scan: reject Bearer token / file-path / credential-JSON /
      out-of-scope free-text (regex/pattern, NOT an LLM check)
    - Deterministic unredacted-PII / raw-account-number screen
      (UnredactedPIIScreen): case notes carrying an explicit raw-PII label
      (e.g. "SSN:", "credit card number") are rejected before retrieval — a
      distinct, prior gate to PolicyRetrieve. Collections/customer-ops policy
      requires case notes to arrive already redacted.
    - Normalise whitespace
    - Emit S-4 trace events: input_validated, pii_rejected

    Authorized collections/customer-ops staff are internal callers — S-1: INTERNAL.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.INTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event("input_validate_start", {"node": "PreProcessNode"}, state)

        user_input = state.get("user_input", "") or ""

        if not user_input.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", []) + ["PreProcessNode: user_input is empty or missing"],
            }

        if len(user_input) > _MAX_INPUT_LEN:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", [])
                + [f"PreProcessNode: user_input exceeds {_MAX_INPUT_LEN} character limit"],
            }

        lowered = user_input.lower()

        if any(m in lowered for m in _OUT_OF_SCOPE_MARKERS):
            emit_trace_event("input_rejected", {"reason": "out_of_scope_or_credential_shaped"}, state)
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", [])
                + ["PreProcessNode: out-of-scope or credential-shaped input rejected"],
            }

        sanitized = _WS.sub(" ", user_input).strip()

        if is_unredacted_pii(sanitized):
            emit_trace_event("pii_rejected", {"input_length": len(sanitized)}, state)
            return {
                "pii_reject_flagged": True,
                "status": AgentStatus.ERROR.value,
                "error_log": state.get("error_log", [])
                + [
                    "PreProcessNode: UnredactedPIIScreen rejected case notes carrying unredacted "
                    "customer PII / a raw-PII label — case notes must arrive already redacted"
                ],
            }

        emit_trace_event(
            "input_validated",
            {"input_length": len(sanitized)},
            state,
        )

        return {
            "sanitized_case_notes": sanitized,
            "pii_reject_flagged": False,
            "validated_input": sanitized,
            "status": AgentStatus.SUCCESS.value,
        }

    def _extra_security_gate_input(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-2 domain hook (runs after the default PII scan).

        Contract (FunctionNode 1.0.0): receive state, RETURN state, never raise —
        reject by setting status=ERROR + appending error_log.
        """
        user_input = state.get("user_input", "") or ""
        if len(user_input) > _MAX_INPUT_LEN:
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = state.get("error_log", []) + [
                f"PreProcessNode S-2: input length {len(user_input)} exceeds {_MAX_INPUT_LEN} limit"
            ]
            return state
        if any(m in user_input.lower() for m in _OUT_OF_SCOPE_MARKERS):
            state["status"] = AgentStatus.ERROR.value
            state["error_log"] = state.get("error_log", []) + [
                "PreProcessNode S-2: out-of-scope or credential-shaped input rejected"
            ]
        return state
