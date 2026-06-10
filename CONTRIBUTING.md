# Contributing to basis-adapters

Thank you for your interest in contributing. This document explains how to set up a
development environment, what quality gates must pass, and — most importantly — the
architectural boundaries every contribution must respect.

---

## Project Purpose

`basis-adapters` is part of the BASIS ecosystem, an open-source architecture for
identity-aware authorization in operational technology (OT) environments.

```
basis-core       evaluates authorization decisions
basis-gateway    authenticates, normalizes identity, and enforces decisions
basis-adapters   normalize protocol-specific operations into BASIS authorization semantics
```

The governing principle:

> **Adapters normalize. Gateway enforces. Kernel evaluates.**

Adapters translate raw protocol operations (an HTTP request, a BACnet service
primitive, a Modbus function, an OPC UA service request, an MQTT
publish/subscribe intent, a DNP3 read or control intent) into a canonical,
protocol-agnostic authorization request. That is the entire job. Everything else belongs elsewhere in the ecosystem.

## Architectural Guardrails

These are hard boundaries, not preferences. A pull request that crosses any of them
will not be merged, regardless of code quality.

Adapters must not:

- authenticate callers
- validate JWTs or tokens
- call identity providers
- evaluate policy
- enforce or reinterpret decisions
- call `basis-core`
- call `basis-gateway` during normalization
- perform live protocol/network communication
- become proxy servers

Adapters must:

- fail closed — if normalization fails, the caller must not forward the operation
- preserve protocol evidence verbatim in every normalized request
- emit the canonical normalized request shape defined in
  `schemas/normalized-authorization-request.schema.json`
- keep models immutable and deterministic

See `docs/contracts/adapter-contract.md` and `docs/contracts/normalization-contract.md`
for the full contracts.

## Local Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quality Gates

All four must pass before opening a pull request:

```bash
python -m pytest
ruff check .
ruff format --check .
mypy src
```

GitHub Actions runs these same four gates on every pull request and on pushes
to `main` (`.github/workflows/ci.yml`), so a PR that passes locally should pass
CI. Note that the type-checking gate is `mypy src`, not `mypy .`.

See `docs/development-workflow.md` for the recommended day-to-day workflow.

## Branch Naming

Use a short, descriptive prefix:

```
feature/<short-description>     new capability or docs
fix/<short-description>         bug fix
docs/<short-description>        documentation-only change
```

Examples from this repository's history: `feature/rest-adapter-contract-hardening`,
`feature/modbus-adapter-skeleton`.

## Commit Messages

Follow the existing style: a conventional-commit-flavored summary line, imperative
mood, under ~72 characters.

```
feat: add Modbus adapter skeleton
fix: reject empty resource_type in REST mapping validation
docs: clarify fail-closed semantics in adapter contract
```

## Pull Request Expectations

- Keep PRs focused — one concern per PR.
- All quality gates pass locally.
- Tests accompany behavior changes; contract changes require contract tests.
- Update docs, examples, and JSON Schemas when the surfaces they describe change.
- Confirm the adapter contract is preserved (the PR template has a checklist).
- Do not commit generated artifacts (`__pycache__/`, `.venv/`, caches — see
  `.gitignore`).

## Adding a Future Protocol

New protocol adapters are welcome, but they must conform to the existing pattern.
The current roadmap (see the README) plans KNX and Niagara. A new protocol
PR should include, mirroring `rest/`, `bacnet/`, `modbus/`, `opcua/`,
`mqtt/`, `dnp3/`, and `iec61850/`:

1. A typed operation model for the protocol (frozen dataclass).
2. A mapping model with fail-fast validation (`InvalidMappingError` on bad config,
   `UnknownRouteError` semantics for unmatched operations).
3. An adapter that emits `AdapterResult` and, on success, a
   `NormalizedAuthorizationRequest` conforming to the canonical schema — no
   protocol-specific top-level output fields.
4. A JSON Schema for the mapping config under `schemas/`.
5. Examples under `examples/<protocol>/` and a handoff example under
   `examples/handoff/`.
6. Architecture documentation under `docs/architecture/`.
7. Tests: adapter, mapping, and participation in the cross-protocol contract tests
   (`tests/test_normalization_contract.py`).

Open a feature request issue first so the protocol's normalization model can be
discussed before significant work begins.

## Non-Goals

Do not propose or include:

- live protocol communication (sockets, packet parsing, protocol stacks)
- a gateway HTTP client or any `basis-gateway`/`basis-core` integration
- authorization evaluation, enforcement, or authentication
- a standalone proxy server
- Docker/Kubernetes deployment artifacts

If a contribution needs any of these, it belongs in a different BASIS repository.

## Questions

Open a GitHub issue. For suspected security problems, do **not** open a public
issue — see [SECURITY.md](SECURITY.md).
