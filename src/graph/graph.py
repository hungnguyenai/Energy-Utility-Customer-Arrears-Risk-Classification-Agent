"""AgentCore Platform v1.0"""

# ENE-C2-072 — Energy Utility Customer Arrears Risk Classification Agent
# (VectorRAG node-backbone)
#
# Cat 2 — Multi-step domain workflow (job-to-be-done).
#   Parent  : AgentBaseGraph (outer graph, L1 direct).
#   Pipeline: START → initialize → pre_process → main → post_process → finalize → END
#   Pattern : VectorRAG (arrears-handling policy retrieval + risk-tier
#             classification grounded in a versioned METI/internal policy
#             corpus snapshot).
#
#   pre_process  — InputValidate + UnredactedPIIScreen: sanitise · S-2 gate ·
#                  deterministic unredacted-PII/raw-account-number reject
#   main         — PolicyRetrieve + TierClassify (VectorRAG over the arrears-
#                  handling policy KB; fail-safe toward `hardship` on ambiguity)
#   post_process — RecommendAssemble + OutputValidate (S-3 human-confirm +
#                  grounding gate) + DecisionTraceAudit (S-4)
#
# The versioned policy kb_client is injected via graph config at
# register_nodes() time (a DATA dependency on the template-owned versioned
# approved-corpus index — no cross-template code import); absent → deterministic
# CI-safe fallback corpus (services.service). No live API at query time; no
# runtime/user memory or shared KG.

from framework.graph.agent_base_graph import AgentBaseGraph

from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State


class Graph(AgentBaseGraph):
    """Cat 2 outer graph for ENE-C2-072.

    Backbone: initialize → pre_process → main → post_process → finalize (fixed).
    Class name matches config/agent.yaml `class:` exactly.
    """

    @property
    def name(self) -> str:
        return "ene_c2_072"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        cfg = getattr(self, "config", None) or {}
        kb_client = cfg.get("kb_client")

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(kb_client=kb_client)
        self._nodes["post_process"] = PostProcessNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.
