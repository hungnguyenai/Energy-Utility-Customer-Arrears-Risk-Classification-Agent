# ENE-C2-072 — Energy Utility Customer Arrears Risk Classification Agent

> **Category**: Cat 2 (domain workflow — business logic in src/)
> **Industry**: Energy

## Overview

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

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and operational documentation
```

See `docs/` for the design spec and test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.

