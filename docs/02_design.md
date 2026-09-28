# docs/02_design.md — ENE-C2-072 Design Specification

**Template ID**: ENE-C2-072
**Name**: Energy Utility Customer Arrears Risk Classification Agent
**Category**: Cat 2 | **Industry**: ENE | **Pattern**: VectorRAG
**L1 Base:** AgentBaseGraph (L1 direct)
**Status**: Design — new-gen scaffold
**Scaffold issue**: (internal reference withheld) — source of truth

---

## 1. Overview

Electricity/gas arrears risk-tier classification for the utility retailer's collections /
customer-operations function. When a customer account falls into arrears, the call-centre or
collections team triggers this agent with the account note history and arrears data. The agent
validates and screens the case, retrieves the applicable METI arrears-handling guideline and
internal collections policy from a policy KB, classifies the case into a risk tier
(hardship / dispute / chronic / fraud) with rationale — fail-safe toward `hardship` on any
ambiguous signal — and recommends the appropriate next intervention (hardship payment plan,
billing review, collections escalation requiring human confirmation, or fraud investigation
referral). It replaces a 10-15 minute manual review and reduces the regulatory risk of
misrouting a hardship customer into collections.

Example: *"Customer has missed 3 payments and case notes mention she was recently laid off and
is struggling to pay her electricity bill."* → risk tier `HARDSHIP`, citing
`METI-ARREARS-2026-03`, recommending an extended/adjusted payment plan and explicitly
NOT escalating to collections.

Scope: **IN** — risk-tier classification + intervention recommendation for an arrears case.
**DEFERRED** — executing any collections action (human), issuing the actual payment plan (human).

---

## 2. Architecture — L1 Base

**L1 Base:** `AgentBaseGraph` (`framework/graph/agent_base_graph.py`), inherited directly.

Per the 2026-05-18 architecture change, templates inherit directly from L1; the retired
base-agent layer is no longer an inheritance path. `VectorRAGAgent` survives only as the
**node-backbone pattern** label (`config/agent.yaml` `base_type`). The outer graph
`Graph(AgentBaseGraph)` registers three domain nodes into the fixed framework backbone;
`InitializeNode`/`FinalizeNode` are injected by `super().register_nodes()`. `add_edges()` is
NOT overridden.

The canonical arrears-handling flow (InputValidate → UnredactedPIIScreen → PolicyRetrieve →
TierClassify → RecommendAssemble → OutputValidate(S-3) → DecisionTraceAudit(S-4)) is
consolidated onto the fixed 3 domain slots: InputValidate+UnredactedPIIScreen fold into
`pre_process`; PolicyRetrieve+TierClassify fold into `main`; RecommendAssemble+OutputValidate+
DecisionTraceAudit fold into `post_process`. All canonical steps are preserved across the 3
nodes — no step is dropped.

---

## 3. Node Flow (5-node backbone)

```
START → initialize → pre_process → main → post_process → finalize → END
```

| Slot | Node | Canonical step(s) | Responsibility |
|------|------|-------------------|-----------------|
| `initialize`   | InitializeNode (framework) | — | Seed IDs / context |
| `pre_process`  | PreProcessNode (FunctionNode) | InputValidate + UnredactedPIIScreen | Validate + sanitise + S-2 out-of-scope/credential-shaped block + deterministic unredacted-PII/raw-account-number reject |
| `main`         | MainNode (FunctionNode) | PolicyRetrieve + TierClassify | Retrieve applicable METI/internal arrears policy passages (VectorRAG); classify risk tier — fail-safe toward `hardship`; recommend next intervention; `NO_MATCH` if nothing matched |
| `post_process` | PostProcessNode (FunctionNode) | RecommendAssemble + S-3 + DecisionTraceAudit + S-4 | Append non-suppressible human-confirmation notice; block uncited/credential/PII/certainty/ungated-collections output; emit audit record |
| `finalize`     | FinalizeNode (framework) | — | Finalize status |

`main` is a `FunctionNode` (no inner graph). The versioned policy KB client is injected via
graph config; absent → deterministic fallback corpus. Any node returning `AgentStatus.ERROR`
short-circuits the remaining domain nodes (an `UnredactedPIIScreen` reject or a `NO_MATCH`
never reaches `post_process`).

---

## 4. State Schema

`src/schemas/state.py` — `class State(AgentState)`. The arrears case (account note history +
arrears data, free text) arrives as inherited `user_input`.

| Field (agent-specific) | Type | Set by | Description |
|-------------------------|------|--------|-------------|
| `sanitized_case_notes` | `Optional[str]` | pre_process | Whitespace-normalised, screened case notes |
| `pii_reject_flagged` | `Optional[bool]` | pre_process | True when UnredactedPIIScreen rejected the case notes |
| `retrieved_policies` | `Optional[list[dict]]` | main | `{citation, tier, effective_date, jurisdiction, kb_date, snippet}` — **non-suppressible citation trail** |
| `kb_version_manifest` | `Optional[list[str]]` | main | One entry per policy source cited (S-4 audit + data-currency) |
| `disposition` | `Optional[str]` | main | `ANSWERED` \| `NO_MATCH` |
| `risk_tier` | `Optional[str]` | main | `hardship` \| `dispute` \| `chronic` \| `fraud` |
| `classification_rationale` | `Optional[str]` | main | Draft rationale (pre-S-3) |
| `recommended_intervention` | `Optional[str]` | main | Draft recommended next intervention (pre-S-3) |
| `validated_recommendation` | `Optional[str]` | post_process | Final recommendation incl. human-confirmation notice |
| `citation_count` | `Optional[int]` | post_process | Number of distinct policy citations in the recommendation |

All fields flat, msgpack-safe primitives (ADR-005) — no non-flat objects, no datetime/bytes, no
credentials or connection strings. Customer PII must never be part of this agent's stored
domain — case notes are expected to arrive already redacted per collections-handling policy;
notes carrying a raw-PII label are rejected before they ever reach state (`pre_process`).

---

## 5. Domain Logic — Screening, Retrieval & Classification

`src/services/service.py` — deterministic offline corpus (`POLICY_KB`) spanning METI Arrears
Handling Guideline (hardship protection, disconnection notice / billing dispute) and internal
collections/fraud policy, each passage carrying `citation`/`tier`/`effective_date`/
`jurisdiction`/`kb_date`/`snippet`.

- **UnredactedPIIScreen** (`is_unredacted_pii`): deterministic phrase/label ruleset (rule/label,
  not digit-shape-based — a digit-shape check would be silently defeated or fabricated by the
  framework's own built-in S-2 PII masker, which runs before this domain gate). Runs in
  `pre_process`, BEFORE retrieval — case notes flagged here never reach `PolicyRetrieve`.
- **PolicyRetrieve** (`retrieve_policies`): keyword-matched retrieval across all four risk-tier
  lexicons at once — a case may legitimately match multiple tiers (the ambiguous-signal case,
  e.g. hardship phrasing alongside a chronic-non-payment history). No match across any tier →
  `NO_MATCH`.
- **TierClassify** (`classify_tier`): deterministic classification, fail-safe toward `hardship` —
  if `hardship` is among the matched tiers at all (even alongside a competing tier), the case is
  classified `hardship`; if no hardship signal is present but more than one other tier matched
  (genuinely ambiguous), the classifier still fails safe toward `hardship` rather than guessing;
  a single unambiguous non-hardship match is classified as that tier. This deterministic
  classifier is the offline/CI fallback for an injected LLM reasoner (deferred — §11); the
  citation/tier/rationale contract stays stable either way.

In production the injected versioned `kb_client` replaces the corpus (same
`retrieve(query) -> list[dict]` interface — template-owned versioned approved-corpus index; no
runtime/user memory, no write-back, no shared KG abstraction). Only policy citations + snippets
are ever surfaced — never customer PII or source-system credentials.

---

## 6. Security Model (5-layer)

| Layer | Where | Design |
|-------|-------|--------|
| S-1 Trust | every node | `required_trust_level = INTERNAL` (authorized collections/customer-ops staff) — declared on all three FunctionNode subclasses + `config/agent.yaml` |
| S-2 Input | `PreProcessNode._extra_security_gate_input` + `execute()` | Length-cap + out-of-scope/credential-shaped guard (returns state; never raises); execute() also runs the deterministic UnredactedPIIScreen |
| S-3 Output | `PostProcessNode._extra_security_gate_output` | Block credential patterns; block unredacted-PII leakage; block unsupported-certainty phrasing; block a "collections-eligible" outcome not paired with an explicit human-confirmation requirement; **ResponseValidate** rejects a recommendation with no policy citation (grounding); the informational notice is appended non-suppressibly in `execute()` |
| S-4 Audit | every `execute()` | `emit_trace_event()` domain events (input_validated, pii_rejected, policy_retrieved, no_policy_match, tier_classify_complete, decision_trace_audit …) — no PII, no credentials |
| S-5 Credential | CI `gate-credential-scan` + deps | No hardcoded secrets; deps `==`-pinned; no secrets/connection strings in State or corpus |

`retrieved_policies` is written once by `main` and never filtered downstream (citation-trail
integrity — a recommendation must stay grounded in the policy basis it cites).

---

## 7. KB Dependency (versioned offline snapshot)

Data dependency on the versioned METI arrears-handling guideline + internal collections/fraud
policy corpus — a template-owned approved-corpus index. **No cross-template code import**; the
indexer is not called at runtime. Readiness gate: corpus must be current before deploy.
Fallback: `NO_MATCH` disposition when the injected client (or the deterministic corpus) yields
nothing — the agent never classifies a risk tier without current policy grounding. The KB
version manifest is recorded in state + audit.

---

## 8. Interfaces

**Input** (`user_input`): account note history + arrears data (free text), already redacted of
customer PII per collections-handling policy.
**Output** (`result.output` / `formatted_output`): risk tier + rationale + recommended next
intervention + policy citation(s) + non-suppressible human-confirmation notice.
Entry points: `src/api/server.py` (`POST /invoke`, `GET /health`) and direct `agent.invoke()`.

---

## 9. Failure / Error Routing

| Condition | Node | Behaviour |
|-----------|------|-----------|
| Empty / whitespace input | pre_process | `status=ERROR`, error_log entry; downstream nodes short-circuit |
| Oversized input (> 10,000 chars) | pre_process (execute + S-2 gate) | `status=ERROR` |
| Out-of-scope / credential-shaped input | pre_process (execute + S-2 gate) | `status=ERROR` |
| Unredacted-PII / raw-account-number case notes | pre_process (UnredactedPIIScreen) | `status=ERROR`, `pii_reject_flagged=True`; retrieval never runs |
| Below-trust caller (< INTERNAL) | S-1 gate (framework) | refused before domain execute |
| No applicable policy matched | main | `NO_MATCH` `status=ERROR` — never classify without grounding |
| Uncited / credential / PII / certainty / ungated-collections output | post_process S-3 | `RuntimeError` raised, output blocked |

---

## 10. Acceptance Criteria

- Backbone runs `initialize → pre_process → main → post_process → finalize` in fixed order.
- Valid INTERNAL invocation for an in-scope, retrievable case returns a classified risk tier
  (`validated_recommendation` carries a `METI-ARREARS-`/`METI-DISCONNECT-`/`INTERNAL-COLLECT-`/
  `INTERNAL-FRAUD-`/`KB version` citation marker + the human-confirmation notice) with
  `status=SUCCESS`.
- Case notes carrying unredacted PII / a raw-PII label are rejected before retrieval — zero KB
  calls, `post_process` never runs.
- No recommendation passes S-3 without at least one policy citation.
- No `collections-eligible` recommendation passes S-3 without an explicit human-confirmation
  requirement.
- An unmatched case forces `NO_MATCH` — never an affirmative classification without grounding.
- An ambiguous signal (competing tiers, or hardship alongside another tier) is classified
  `hardship` — never a fabricated tier not grounded in `retrieved_policies`.
- All CI gates green: scaffold-integrity, design, import-isolation, composition, invoke-chain,
  credential-scan, trust-level, cat-consistency, stub-check, dep-pinning, run-tests.

---

## 11. Deferred to later implementation issues

The day-0 implementation is CI-safe and deterministic offline. The following land via their own
issues:

- **Versioned vector-KB retrieval** — replace the deterministic corpus with the injected
  versioned client over the real self-hosted policy knowledge graph (with snapshot-freshness
  checks). Self-host vs platform KG/memory primitive is an architectural ruling, consistent with
  sibling templates in this batch — a persistence-layer design choice, not a hard blocker for
  this implementation.
- **LLM classification reasoner** — richer rationale / edge-case reasoning via an injected
  `BaseLLM` (`ctx.secrets.require(...)`); the deterministic classifier is retained as
  offline/CI fallback.
- **Policy corpus refresh pipeline** — scheduled versioned ingest of official METI / internal
  collections-policy sources (build-time pipeline, not part of the query-time graph).
- **Human-in-the-loop collections confirmation workflow** — this template recommends and gates
  on human confirmation textually; wiring an actual HITL interrupt/approval step is out of scope
  (`hitl.enabled: false` for this template).


---

## Supported entry point — HTTP/gateway only (Marketplace out of scope)

Every node in this template declares `required_trust_level = INTERNAL`, which is the design
decision recorded for this agent: the data it reads is not material an arbitrary authenticated
caller should be able to query.

The one-shot Marketplace runner stamps the caller at `VERIFIED_EXTERNAL` and exposes no
configuration surface or elevation path to `INTERNAL`, so the S-1 gate refuses every Marketplace
invocation **before** `execute()` runs. Two consequences are worth stating, because both read as
a broken image: the Pod still reports success and the audit counters do not move, and the terminal
failure carries no reason, so the chat surface shows an opaque error.

Nesting does not change this. A subgraph is invoked with the caller's own context
(`subgraph.invoke(..., ctx=ctx)`), so the trust level propagates unchanged and an inner node
cannot be reached at a higher level than the outer call arrived with.

### The HTTP path is also closed, deliberately

The standalone adapter used to promote an anonymous caller straight to `INTERNAL` once it
presented the shared `INVOKE_AUTH_TOKEN`. That token authenticates a *deployment*, not a person,
so granting `INTERNAL` on it placed a back door behind the very gate this design depends on. The
adapter now grants `VERIFIED_EXTERNAL`, which is what its own documentation always described.
**The gate is unchanged** — every node still requires `INTERNAL`.

The consequence is stated rather than hidden: since the nodes require `INTERNAL` and nothing in
either entry point can now supply it, **this template currently has no reachable entry point at
all**. That is fail-closed and intended.

One legitimate route remains open: trust established by upstream middleware is passed through
unchanged, so a gateway that has verified the caller's identity can still reach these nodes.

### What is NOT being done

- The nodes' `required_trust_level` is **not** lowered. Doing so would widen who may query this
  data, which is a product decision and not an engineering one.
- No Marketplace image is published and the template is not registered as a Marketplace agent.
