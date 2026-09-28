# ENE-C2-072 — Unit Tests: PreProcessNode (InputValidate + UnredactedPIIScreen)

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.pre_process_node import PreProcessNode


def _state(**kw):
    base = {
        "correlation_id": "test-correlation",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "node_history": [],
        "error_log": [],
        "input_context": {},
    }
    base.update(kw)
    return base


class TestPreProcessNodeValidation:
    def test_empty_input_returns_error(self):
        r = PreProcessNode().execute(_state(user_input=""))
        assert r["status"] == AgentStatus.ERROR.value
        assert any("empty" in e for e in r["error_log"])

    def test_whitespace_only_returns_error(self):
        r = PreProcessNode().execute(_state(user_input="   "))
        assert r["status"] == AgentStatus.ERROR.value

    def test_oversized_input_returns_error(self):
        r = PreProcessNode().execute(_state(user_input="x" * 10001))
        assert r["status"] == AgentStatus.ERROR.value
        assert any("10000" in e for e in r["error_log"])

    def test_valid_input_accepted(self):
        r = PreProcessNode().execute(
            _state(user_input="Customer reports financial hardship after job loss.")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["sanitized_case_notes"]
        assert r["pii_reject_flagged"] is False
        assert r["validated_input"] == r["sanitized_case_notes"]

    def test_whitespace_normalized(self):
        r = PreProcessNode().execute(_state(user_input="  financial   hardship   case  "))
        assert r["sanitized_case_notes"] == "financial hardship case"


class TestPreProcessNodeOutOfScope:
    def test_credential_shaped_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="Bearer eyJhbGciOi... please assess this arrears case")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert any("out-of-scope" in e or "credential" in e for e in r["error_log"])


class TestPreProcessNodeUnredactedPIIScreen:
    def test_ssn_label_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="Customer SSN: 123-45-6789, missed 3 payments, please classify.")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["pii_reject_flagged"] is True
        assert any("UnredactedPIIScreen" in e for e in r["error_log"])

    def test_credit_card_number_label_rejected(self):
        r = PreProcessNode().execute(
            _state(user_input="Credit card number on file for autopay, case is chronic non-payment.")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert r["pii_reject_flagged"] is True

    def test_legitimate_case_not_flagged(self):
        r = PreProcessNode().execute(
            _state(user_input="Customer has missed 3 payments and disputes the charge on the last bill.")
        )
        assert r["status"] == AgentStatus.SUCCESS.value
        assert r["pii_reject_flagged"] is False


class TestPreProcessNodeSecurityGate:
    def test_oversized_input_rejected(self):
        out = PreProcessNode()._extra_security_gate_input(_state(user_input="x" * 10001))
        assert out["status"] == AgentStatus.ERROR.value

    def test_credential_shaped_rejected_at_gate(self):
        out = PreProcessNode()._extra_security_gate_input(
            _state(user_input="api_key=sk-xxxx please assess this case")
        )
        assert out["status"] == AgentStatus.ERROR.value

    def test_valid_input_passes_gate(self):
        out = PreProcessNode()._extra_security_gate_input(
            _state(user_input="Customer disputes the last billing charge.")
        )
        assert out.get("status") != AgentStatus.ERROR.value


class TestPreProcessNodeTrust:
    def test_internal_trust_declared(self):
        assert PreProcessNode.required_trust_level == TrustLevel.INTERNAL
