# ENE-C2-072 — Proof-of-Boundary: domain-specific boundary verification
#
# PB-1: emit_trace_event() in every execute() body (S-4 audit)
# PB-6: _security_gate_* not overridden; _extra_* hooks callable; FunctionNode subclasses
# Domain: retrieved_policies NON-SUPPRESSIBLE (citation trail); uncited recommendations blocked
#         (S-3); a case carrying unredacted PII / a raw-PII label is rejected BEFORE retrieval
#         (zero KB calls); an unmatched case forces NO_MATCH (never an affirmative ungrounded
#         classification).
#
# Graph-level coverage: isolated node-level unit tests can pass while the REAL
# Graph.invoke() path (with the framework's own built-in S-2 PII-masking pipeline in front of
# every node) silently defeats a domain gate. These tests drive the SAME real path every
# production caller uses: Graph(config=...).compile().invoke(...) — never a manually composed
# node chain, never .run().
#
# CI-safe: fully deterministic offline (no live API/vector store).

import inspect

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext, TrustLevel

from src.nodes.pre_process_node import PreProcessNode
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.graph.graph import Graph
from src.schemas.state import State


def _state(**kw):
    base = {
        "correlation_id": "pb-corr", "session_id": "pb-session", "thread_id": "pb-thread",
        "trace_id": "pb-trace", "node_history": [], "error_log": [], "input_context": {},
    }
    base.update(kw)
    return base


class TestPB1TraceEmission:
    def test_pre_process_emits(self):
        assert "emit_trace_event" in inspect.getsource(PreProcessNode.execute)

    def test_main_emits(self):
        assert "emit_trace_event" in inspect.getsource(MainNode.execute)

    def test_post_process_emits(self):
        assert "emit_trace_event" in inspect.getsource(PostProcessNode.execute)


class TestPB6SecurityGates:
    def test_gate_input_not_overridden(self):
        assert "_security_gate_input" not in PreProcessNode.__dict__

    def test_gate_output_not_overridden(self):
        assert "_security_gate_output" not in PostProcessNode.__dict__

    def test_extra_hooks_callable(self):
        assert callable(getattr(PreProcessNode(), "_extra_security_gate_input", None))
        assert callable(getattr(PostProcessNode(), "_extra_security_gate_output", None))

    def test_all_nodes_are_functionnode(self):
        for cls in (PreProcessNode, MainNode, PostProcessNode):
            assert issubclass(cls, FunctionNode), f"{cls.__name__} must extend FunctionNode"


class TestRetrievedPoliciesNonSuppressible:
    def _state_with_policies(self):
        return _state(
            disposition="ANSWERED",
            risk_tier="hardship",
            kb_version_manifest=["METI-ARREARS-2026-03 (2026-07-01)"],
            classification_rationale="Classified HARDSHIP: hardship indicators present.",
            recommended_intervention="Hardship intervention: offer an extended payment plan.",
            retrieved_policies=[
                {"citation": "METI-ARREARS-2026-03", "tier": "hardship",
                 "effective_date": "2026-03-01", "jurisdiction": "Japan", "kb_date": "2026-07-01",
                 "snippet": "..."},
            ],
        )

    def test_post_process_does_not_touch_retrieved_policies(self):
        result = PostProcessNode().execute(self._state_with_policies())
        assert "retrieved_policies" not in result, (
            "PostProcessNode must not rewrite/empty the non-suppressible retrieved_policies"
        )
        assert result["status"] == AgentStatus.SUCCESS.value


class TestNoMatchNeverSynthesises:
    class _EmptyKB:
        def retrieve(self, query):
            return []

    def test_empty_kb_forces_error_never_classifies(self):
        r = MainNode(kb_client=self._EmptyKB()).execute(
            _state(sanitized_case_notes="what is the weather forecast for tomorrow")
        )
        assert r["status"] == AgentStatus.ERROR.value
        assert "risk_tier" not in r  # never issues an ungrounded classification
        assert any("no_policy_match" in e for e in r["error_log"])


class TestGraphLevelInputGate:
    """Graph-level Proof-of-Boundary — sibling-incident follow-up.

    Drives real-graph verification: ENE-C2-072's own gates
    (out-of-scope/credential-shaped rejection + UnredactedPIIScreen in
    PreProcessNode) are exercised through `Graph(config={"kb_client": ...})
    .compile().invoke(...)` — the SAME real path production uses — with an
    instrumented spy KB client injected exactly the way `Graph.register_nodes()`
    wires it into `MainNode(kb_client=...)`.

    Also empirically proves the specific HCR-class hazard does NOT apply here:
    `is_unredacted_pii` (src/services/service.py) and the pre_process
    out-of-scope markers are 100% phrase/label based — none key off a
    digit-shaped pattern — so the framework's built-in PII-masking of a long
    digit run can neither defeat an intended rejection nor corrupt a legitimate
    retrieval/classification. Both directions proved empirically below, not
    assumed.
    """

    class _SpyKBClient:
        """Fake versioned arrears-handling policy KB client implementing the
        real interface consumed by `services.service.retrieve_policies`
        (`retrieve(query) -> list[dict]`, exactly as looked up and called from
        inside `MainNode.execute()` via `self._kb_client`). Records every call
        so the test can assert zero retrieval on a rejected path.
        """

        def __init__(self):
            self.calls: list[str] = []

        def retrieve(self, query: str):
            self.calls.append(query)
            return [{
                "citation": "SPY-KB-001", "tier": "hardship",
                "effective_date": "2026-07-01", "jurisdiction": "Global",
                "kb_date": "2026-07-15", "snippet": "spy policy evidence snippet",
            }]

    @staticmethod
    def _build_graph(kb_client):
        graph = Graph(config={"kb_client": kb_client})
        graph.compile()
        return graph

    @staticmethod
    def _ctx(session_id: str) -> InvocationContext:
        # All three ENE-C2-072 nodes declare required_trust_level = INTERNAL
        # (authorized collections/customer-ops staff); use that level so the
        # negative assertions below are conditioned on the domain gates, not
        # an S-1 denial.
        return InvocationContext(
            session_id=session_id,
            caller_trust_level=TrustLevel.INTERNAL,
            caller_id="pb-graph-test",
        )

    # ── negative paths: rejection must survive the REAL graph wiring ────────

    def test_graph_invoke_unredacted_pii_rejected_zero_kb_retrieval(self):
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "SSN: 123-45-6789 — please assess this arrears case for collections.",
            ctx=self._ctx("pb-graph-pii"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert "risk_tier" not in result, (
            "unredacted-PII case notes must never reach PolicyRetrieve"
        )
        assert spy.calls == [], (
            f"Real Graph.invoke() reached policy retrieval (kb_client.retrieve) "
            f"for unredacted-PII case notes — calls: {spy.calls}"
        )
        # route() sends ERROR straight to finalize — post_process must never run.
        assert "PostProcessNode" not in result.get("node_history", []), result.get("node_history")

    def test_graph_invoke_out_of_scope_rejected_zero_kb_retrieval(self):
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Bearer eyJhbGciOiJIUzI1NiJ9.xxx — please assess this arrears case.",
            ctx=self._ctx("pb-graph-outofscope"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert spy.calls == [], (
            f"Real Graph.invoke() reached policy retrieval for a "
            f"credential-shaped/out-of-scope input — calls: {spy.calls}"
        )
        assert "PostProcessNode" not in result.get("node_history", []), result.get("node_history")

    # ── positive control: proves the negative assertions aren't vacuous ─────

    def test_graph_invoke_positive_control_legitimate_case_reaches_kb_client(self):
        """Same real Graph, same real (injected) kb_client, same real .invoke()
        entry point — proves the negative tests above are conditioned on the
        real domain-gate outcome, and not on retrieval being unreachable/broken
        through the graph wiring in general."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Customer reports financial hardship after losing their job and struggling to pay.",
            ctx=self._ctx("pb-graph-positive"),
        )

        assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value), result
        assert spy.calls == [
            "Customer reports financial hardship after losing their job and struggling to pay."
        ], spy.calls
        assert "SPY-KB-001" in str(result.get("output")), result
        assert "informational" in str(result.get("output")).lower()
        assert "PostProcessNode" in result.get("node_history", [])
        assert "MainNode" in result.get("node_history", [])

    # ── NO_MATCH path: must never synthesise through the real graph ─────────

    def test_graph_invoke_unmatched_case_never_synthesises(self):
        class _EmptyKB:
            def retrieve(self, query):
                return []

        graph = self._build_graph(_EmptyKB())

        result = graph.invoke(
            "What is the weather forecast for tomorrow?",
            ctx=self._ctx("pb-graph-nomatch"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), result
        assert not result.get("output"), result
        assert "PostProcessNode" not in result.get("node_history", [])

    # ── HCR-class hazard: built-in PII masking must not corrupt ENE's OWN gate ──

    def test_graph_invoke_pii_shaped_value_does_not_defeat_legitimate_classification(self):
        """A legitimate, in-scope case that also carries a PII-shaped long
        digit run (e.g. a case reference number) must NOT be spuriously
        rejected merely because the built-in S-2 scan masks that digit run to
        `[MASKED]` before PreProcessNode.execute() ever sees it — ENE's own
        UnredactedPIIScreen/retrieval logic is phrase-based and must survive
        intact."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "Case reference 123456789012 — customer reports financial hardship after job loss.",
            ctx=self._ctx("pb-graph-pii-legitimate"),
        )
        assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value), result
        assert spy.calls, (
            "built-in PII masking of the digit run must not have swallowed the "
            f"hardship retrieval signal: {result}"
        )

    def test_graph_invoke_pii_masking_does_not_defeat_unredacted_pii_rejection(self):
        """Empirically confirm ENE's own UnredactedPIIScreen trigger is
        phrase/label-based, not digit-shape-based — unlike a detector whose
        ONLY signal for one input is a digit-shape regex the built-in masker
        also matches (the HCR incident class). Here the rejection label is
        deliberately paired with a maskable digit run; if ENE's detection
        secretly depended on the (now-masked) digits surviving, this would
        flip from ERROR to SUCCESS — it must not."""
        spy = self._SpyKBClient()
        graph = self._build_graph(spy)

        result = graph.invoke(
            "SSN: 123456789012 — please assess this account for collections eligibility.",
            ctx=self._ctx("pb-graph-pii-reject"),
        )

        assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value), (
            "PII-shaped-value masking of the digit run must not have defeated the "
            f"phrase/label-based unredacted-PII rejection: {result}"
        )
        assert spy.calls == [], spy.calls
        assert "PostProcessNode" not in result.get("node_history", [])


class TestS3Grounding:
    def test_uncited_recommendation_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "Offer the customer a payment plan.",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 ResponseValidate must block a recommendation with no policy citation"

    def test_credential_pattern_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "the password is hunter2 (METI-ARREARS-2026-03)",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a credential pattern from reaching output"

    def test_ungated_collections_eligible_blocked(self):
        node = PostProcessNode()
        result = {"validated_recommendation": "This account is collections-eligible (INTERNAL-COLLECT-2025-12).",
                  "status": AgentStatus.SUCCESS.value}
        try:
            node._extra_security_gate_output(result)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "S-3 must block a collections-eligible outcome with no human-confirmation requirement"


class TestGraphStructure:
    def test_inherits_agent_base_graph(self):
        from framework.graph.agent_base_graph import AgentBaseGraph
        assert issubclass(Graph, AgentBaseGraph)

    def test_does_not_override_add_edges(self):
        assert "add_edges" not in Graph.__dict__

    def test_state_schema_is_state(self):
        assert Graph().state_schema is State

    def test_agent_name(self):
        assert Graph().name == "ene_c2_072"
