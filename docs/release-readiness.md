# Release Readiness — v0.1.0 Checklist

This document defines what must be true before a `v0.1.0` release of
`basis-adapters` is tagged. It is a gate, not a promise of a date.

**Current status: v0.1.0 release candidate.** The initial planned adapter set —
REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, and Niagara — is
complete and normalization-complete. CI runs the four quality gates on every
pull request and push to `main`. All examples and schemas are validated by the
test suite, every adapter ships a deliberately invalid mapping example as a
negative test case, and the canonical normalized request contract is enforced
by cross-protocol contract tests. The version in `pyproject.toml` is `0.1.0`.
No wire-protocol support is claimed, no live network behavior exists, and the
library has no coupling to `basis-core` or `basis-gateway`.

> **Release readiness does not mean production OT readiness.** A `v0.1.0` release
> means the library's contracts, documentation, and quality gates are coherent and
> stable enough for early adopters to build against. It does not mean the library
> has been audited, hardened, or validated for deployment in live operational
> technology environments. No production-readiness claims are made anywhere in this
> repository, and the release must not introduce any.

## Quality Gates

- [ ] All tests pass: `python -m pytest`
- [ ] Lint passes: `ruff check .`
- [ ] Format check passes: `ruff format --check .`
- [ ] Type check passes: `mypy src` (strict mode)

## Documentation

- [ ] README is current: protocol list, status section, and examples reflect the
      actual code.
- [ ] `docs/public-api.md` matches the exported API surface (`__all__` in each
      package).
- [ ] `docs/compatibility.md` reflects current compatibility expectations.
- [ ] Architecture and contract docs describe the code as it exists, not as planned.

## Examples and Schemas

- [ ] All examples under `examples/` are valid against their JSON Schemas
      (enforced by `tests/test_schema_examples.py`; see `docs/schema-validation.md`).
- [ ] Schemas match the implementation: serialized model output validates against
      `schemas/normalized-authorization-request.schema.json`.

## Repository Hygiene

- [ ] No `__pycache__/`, `.venv/`, cache directories, or other generated artifacts
      are committed (`.gitignore` covers them; verify with `git ls-files`).
- [ ] No stray working files, editor droppings, or local tooling output in the tree.

## Claims Discipline

- [ ] No claims of live protocol or network communication anywhere in docs or code
      comments — adapters are pure normalization.
- [ ] No production-readiness claims.
- [ ] Version in `pyproject.toml` matches the tag being prepared.

## Architectural Integrity

- [ ] The adapter contract (`docs/contracts/adapter-contract.md`) remains intact:
      fail-closed semantics, evidence preservation, no authorization logic.
- [ ] REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, and Niagara adapters all emit the canonical
      normalized request shape (enforced by `tests/test_normalization_contract.py`).
- [ ] No coupling to `basis-core` or `basis-gateway` has been introduced.

## v0.1.0 Release Candidate Checklist

The remaining steps between this release candidate and a tag:

- [ ] Final pass of the four quality gates on `main` at the candidate commit.
- [ ] Confirm `git ls-files` shows no generated artifacts or stray files.
- [ ] Confirm the version in `pyproject.toml` (`0.1.0`) matches the tag to be
      created.
- [ ] Tag the release (separate, deliberate step — not automated by anything in
      this repository).

## Out of Scope for v0.1.0

Tagging v0.1.0 explicitly does not require (and must not include): live protocol
communication, a gateway client, a proxy server, Docker/Kubernetes artifacts, or
PyPI publishing automation. Those are separate decisions for later phases.
