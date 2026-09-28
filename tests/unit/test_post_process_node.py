# ENE-C2-072 — Unit Tests: PostProcessNode (RecommendAssemble + OutputValidate S-3 + S-4)

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation", "session_id": "test-session",
        "trace_id": "test-trace", "node_history": [], "error_log": [],
    }
    base.update(kw)
    return base


def _classified_state(tier="hardship"):
    return _state(
        disposition="ANSWERED",
        risk_tier=tier,
        kb_version_manifest=["METI-ARREARS-2026-03 (2026-07-01)"],
        classification_rationale="Classified HARDSHIP: hardship indicators present.",
        recommended_intervention=(
            "Hardship intervention: offer an extended or adjusted payment plan; do NOT "
            "escalate to collections or disconnection while hardship status stands."
        ),
        retrieved_policies=[
            {"citation": "METI-ARREARS-2026-03", "tier": "hardship",
             "effective_date": "2026-03-01", "jurisdiction": "Japan", "kb_date": "2026-07-01",
             "snippet": "..."},
        ],
    )


class TestPostProcessNodeNoticeAndAudit:
    def test_notice_appended(self):
        r = PostProcessNode().execute(_classified_state())
        assert r["status"] == AgentStatus.SUCCESS.value
        assert "informational" in r["validated_recommendation"].lower()
        assert "human confirmation" in r["validated_recommendation"].lower()

    def test_citation_count_computed(self):
        r = PostProcessNode().execute(_classified_state())
        assert r["citation_count"] == 1

    def test_error_state_short_circuits(self):
        r = PostProcessNode().execute(_state(status=AgentStatus.ERROR.value))
        assert r == {}


class TestPostProcessNodeS3Grounding:
    def test_uncited_recommendation_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "Offer a payment plan.", "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 ResponseValidate must block a recommendation with no policy citation"

    def test_cited_recommendation_passes(self):
        node = PostProcessNode()
        result = {
            "validated_recommendation": "Per METI-ARREARS-2026-03, offer a payment plan.",
            "status": AgentStatus.SUCCESS.value,
        }
        node._extra_security_gate_output(result)  # must not raise

    def test_credential_pattern_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "the password is hunter2 (METI-ARREARS-2026-03)",
                  "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a credential pattern from reaching output"

    def test_pii_leak_pattern_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "SSN: 123-45-6789 (METI-ARREARS-2026-03)",
                  "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block an unredacted-PII pattern from reaching output"

    def test_unsupported_certainty_phrasing_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "This is a final collections decision (METI-ARREARS-2026-03).",
                  "status": AgentStatus.SUCCESS.value}
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block unsupported-certainty phrasing"

    def test_collections_eligible_without_human_confirm_blocked(self):
        node = PostProcessNode()
        result = {
            "validated_recommendation": "This case is collections-eligible (INTERNAL-COLLECT-2025-12).",
            "status": AgentStatus.SUCCESS.value,
        }
        raised = False
        try:
            node._extra_security_gate_output(result)
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a collections-eligible outcome with no human-confirmation requirement"

    def test_collections_eligible_with_human_confirm_passes(self):
        node = PostProcessNode()
        result = {
            "validated_recommendation": (
                "This case is collections-eligible but requires human confirmation "
                "before any action (INTERNAL-COLLECT-2025-12)."
            ),
            "status": AgentStatus.SUCCESS.value,
        }
        node._extra_security_gate_output(result)  # must not raise


class TestPostProcessNodeTrust:
    def test_internal_trust_declared(self):
        assert PostProcessNode.required_trust_level == TrustLevel.INTERNAL
