# ENE-C2-072 — Integration test: full agent.invoke() through the 5-node backbone.
# CI-safe: fully deterministic offline (no live API/vector store — corpus fallback).

from framework.schemas.agent_status import AgentStatus
from src.graph.graph import Graph

_EXPECTED_NODES = {"InitializeNode", "PreProcessNode", "MainNode", "PostProcessNode", "FinalizeNode"}

_INPUT = (
    "Customer reports financial hardship after recently losing their job and is struggling "
    "to pay the electricity bill; two consecutive missed payments on the account."
)


def _build():
    agent = Graph()
    agent.compile()
    return agent


def _is_terminal(status) -> bool:
    return status in (
        AgentStatus.SUCCESS, AgentStatus.SUCCESS.value,
        AgentStatus.ERROR, AgentStatus.ERROR.value,
    )


class TestFullInvoke:
    def test_backbone_nodes_registered(self):
        registered = {type(n).__name__ for n in _build()._nodes.values()}
        assert _EXPECTED_NODES.issubset(registered), f"missing: {_EXPECTED_NODES - registered}"

    def test_invoke_reaches_terminal_status(self):
        # No ctx → ANONYMOUS, which S-1 (INTERNAL) correctly refuses; must terminate cleanly.
        out = _build().invoke(_INPUT, session_id="itest")
        status = out.get("status") if isinstance(out, dict) else getattr(out, "status", None)
        assert _is_terminal(status)

    def test_invoke_happy_path_succeeds_with_internal_trust(self):
        from framework.schemas.invocation_context import InvocationContext, TrustLevel

        ctx = InvocationContext(
            session_id="itest2",
            caller_trust_level=TrustLevel.INTERNAL,
            caller_id="itest",
        )
        out = _build().invoke(_INPUT, ctx=ctx)
        status = out.get("status") if isinstance(out, dict) else getattr(out, "status", None)
        assert status in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
        assert _EXPECTED_NODES.issubset(set(out.get("node_history", [])))
        assert out.get("output")
