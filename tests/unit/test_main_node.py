# ENE-C2-072 — Unit Tests: MainNode (PolicyRetrieve + TierClassify)

import inspect

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.main_node import MainNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation", "session_id": "test-session",
        "trace_id": "test-trace", "node_history": [], "error_log": [],
    }
    base.update(kw)
    return base


class TestMainNodeRetrievalAndClassification:
    def test_hardship_case_retrieves_and_classifies(self):
        r = MainNode().execute(
            _state(sanitized_case_notes="Customer reports financial hardship after job loss.")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["disposition"] == "ANSWERED"
        assert r["retrieved_policies"]
        assert any(p["citation"] == "METI-ARREARS-2026-03" for p in r["retrieved_policies"])
        assert r["risk_tier"] == "hardship"

    def test_ambiguous_case_fails_safe_to_hardship(self):
        r = MainNode().execute(
            _state(
                sanitized_case_notes=(
                    "Customer has financial hardship but also a long-standing arrears history "
                    "with repeated missed payments over multiple billing cycles."
                )
            )
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        citations = {p["citation"] for p in r["retrieved_policies"]}
        assert "METI-ARREARS-2026-03" in citations
        assert "INTERNAL-COLLECT-2025-12" in citations
        assert r["risk_tier"] == "hardship"

    def test_unambiguous_fraud_case_classifies_fraud(self):
        r = MainNode().execute(
            _state(sanitized_case_notes="Investigation notes indicate suspected meter tampering on the account.")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["risk_tier"] == "fraud"
        assert any(p["citation"] == "INTERNAL-FRAUD-2026-01" for p in r["retrieved_policies"])

    def test_unmatched_case_forces_no_match(self):
        r = MainNode().execute(_state(sanitized_case_notes="What is the weather today?"))
        assert r["status"] == AgentStatus.ERROR.value
        assert r["disposition"] == "NO_MATCH"
        assert r["retrieved_policies"] == []
        assert any("no_policy_match" in e for e in r["error_log"])

    def test_error_state_short_circuits(self):
        r = MainNode().execute(_state(status=AgentStatus.ERROR.value))
        assert r == {}


class TestMainNodeKBClientInjection:
    class _EmptyKB:
        def retrieve(self, query):
            return []

    def test_empty_injected_kb_forces_no_match_never_classifies(self):
        r = MainNode(kb_client=self._EmptyKB()).execute(
            _state(sanitized_case_notes="Customer reports financial hardship")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["disposition"] == "NO_MATCH"
        assert "risk_tier" not in r  # never issues an ungrounded classification


class TestMainNodeContract:
    def test_execute_method_signature(self):
        assert hasattr(MainNode, "execute"), "MainNode must implement execute()"
        sig = inspect.signature(MainNode.execute)
        params = list(sig.parameters.keys())
        assert len(params) >= 2
        assert params[1] == "state"
        assert "_invoke_impl" not in MainNode.__dict__

    def test_internal_trust_declared(self):
        assert MainNode.required_trust_level == TrustLevel.INTERNAL
