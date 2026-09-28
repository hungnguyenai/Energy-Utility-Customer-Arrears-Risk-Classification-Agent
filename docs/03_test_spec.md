# docs/03_test_spec.md — ENE-C2-072 Test Specification

Traceability: docs/02_design.md

---

## 1. Functional Coverage

| # | Scenario | Test | Expected |
|---|----------|------|----------|
| F1 | Hardship-signal case | `test_main_node.py::test_hardship_case_retrieves_and_classifies` | `ANSWERED`, tier `hardship`, cites `METI-ARREARS-2026-03` |
| F2 | Ambiguous case (hardship + chronic) | `test_main_node.py::test_ambiguous_case_fails_safe_to_hardship` | Both citations present, classified `hardship` (fail-safe) |
| F3 | Unambiguous single-tier case (fraud) | `test_main_node.py::test_unambiguous_fraud_case_classifies_fraud` | Classified `fraud`, cites `INTERNAL-FRAUD-2026-01` |
| F4 | Full backbone happy path | `test_invoke.py::test_invoke_happy_path_succeeds_with_internal_trust` | `SUCCESS`, all 5 nodes in `node_history`, cited recommendation |
| F5 | Whitespace normalisation | `test_pre_process_node.py::test_whitespace_normalized` | Collapsed to single spaces |

## 2. Negative / Error-Path Coverage

| # | Scenario | Test | Expected |
|---|----------|------|----------|
| N1 | Empty / whitespace-only input | `test_pre_process_node.py::TestPreProcessNodeValidation` | `ERROR`, error_log entry |
| N2 | Oversized input (>10,000 chars) | `test_pre_process_node.py::test_oversized_input_returns_error` | `ERROR` |
| N3 | Out-of-scope / credential-shaped input | `test_pre_process_node.py::TestPreProcessNodeOutOfScope` | `ERROR` |
| N4 | Unmatched case (no tier hit) | `test_main_node.py::test_unmatched_case_forces_no_match` | `disposition=NO_MATCH`, `ERROR`, no `risk_tier` |
| N5 | Empty injected kb_client | `test_main_node.py::TestMainNodeKBClientInjection` | `NO_MATCH`, never classifies |

## 3. Security Coverage

| # | Layer | Test | Expected |
|---|-------|------|----------|
| S1 | S-1 trust gate | `test_pre_process_node.py::test_internal_trust_declared` + siblings | `required_trust_level == INTERNAL` on all 3 nodes |
| S2 | S-2 input scan | `test_pre_process_node.py::TestPreProcessNodeSecurityGate` | Oversized / credential-shaped input rejected at `_extra_security_gate_input` |
| S2b | UnredactedPIIScreen (domain S-2) | `test_pre_process_node.py::TestPreProcessNodeUnredactedPIIScreen` | Case notes carrying a raw-PII label (EN) rejected before retrieval |
| S3 | S-3 grounding + human-confirm gate | `test_post_process_node.py::TestPostProcessNodeS3Grounding` | Uncited recommendation, credential pattern, PII leakage, certainty phrasing, and ungated collections-eligible outcome all raise |
| S3b | Non-suppressible human-confirmation notice | `test_post_process_node.py::test_disclaimer_appended` | Every `ANSWERED` response carries the human-confirmation notice |
| S4 | S-4 audit | `test_pb_domain.py::TestPB1TraceEmission` | `emit_trace_event` present in every node's `execute()` |
| S5 | Credential scan | CI `gate-credential-scan` | No hardcoded secrets in source |

## 4. Proof-of-Boundary Coverage (graph-level, real `Graph.invoke()`)

Node-level tests alone are
insufficient; these drive the real production entry point with the framework's built-in S-2
PII-masking pipeline in front of every node.

| # | Test (`tests/proof_of_boundary/test_pb_domain.py::TestGraphLevelInputGate`) | Proves |
|---|------------------------------------------------------------------------------|--------|
| PB-D1 | `test_graph_invoke_unredacted_pii_rejected_zero_kb_retrieval` | Case notes carrying a raw-PII label never reach `PolicyRetrieve` — zero `kb_client.retrieve` calls, `PostProcessNode` never runs |
| PB-D2 | `test_graph_invoke_out_of_scope_rejected_zero_kb_retrieval` | A credential-shaped/out-of-scope input is rejected before retrieval |
| PB-D3 | `test_graph_invoke_positive_control_legitimate_case_reaches_kb_client` | The negative assertions above are conditioned on the real gate outcome, not on retrieval being unreachable in general |
| PB-D4 | `test_graph_invoke_unmatched_case_never_synthesises` | A case matching no policy tier forces `NO_MATCH` through the real graph — never a fabricated tier |
| PB-D5 | `test_graph_invoke_pii_shaped_value_does_not_defeat_legitimate_classification` | Built-in digit-run PII masking does not swallow a legitimate retrieval/classification signal |
| PB-D6 | `test_graph_invoke_pii_masking_does_not_defeat_unredacted_pii_rejection` | Built-in digit-run PII masking does not defeat the phrase-based unredacted-PII rejection (the HCR-class hazard, proved absent here) |

Also standard scaffold PB suites (generic, unmodified): `test_import_isolation.py` (L1-direct, no
Level-0/Level-2 imports), `test_state_safety.py` (no credentials/Pydantic/dataclass in State),
`test_pb_invoke_order.py` (S-1 → node_start → S-2 → execute → S-3 → node_complete order for every
node), `test_pb7_hitl_interrupt_propagation.py` (skip-guarded — `hitl.enabled` is `false` for this
template).

## 5. Acceptance Criteria for CI / STG

- All 12 CI gates green: scaffold-integrity, ci-stubs-deprecation, import-isolation, composition,
  invoke-chain, credential-scan, trust-level, cat-consistency, run-tests, test, stub-check,
  dep-pinning.
- `pytest tests/` and `pytest tests/proof_of_boundary/` both fully green, no skips other than the
  HITL PB-7 placeholder (this template has `hitl.enabled: false`).
- STG first-invoke: a legitimate arrears case returns `status=SUCCESS`
  with a cited, human-confirmation-notice-carrying recommendation.
