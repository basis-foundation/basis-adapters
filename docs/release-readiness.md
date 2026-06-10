# Release Readiness — v0.1.0 Checklist

This document defines what must be true before a future `v0.1.0` release of
`basis-adapters` is tagged. It is a gate, not a promise of a date.

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
- [ ] REST, BACnet, Modbus, OPC UA, MQTT, and DNP3 adapters all emit the canonical
      normalized request shape (enforced by `tests/test_normalization_contract.py`).
- [ ] No coupling to `basis-core` or `basis-gateway` has been introduced.

## Out of Scope for v0.1.0

Tagging v0.1.0 explicitly does not require (and must not include): live protocol
communication, a gateway client, a proxy server, Docker/Kubernetes artifacts, or
PyPI publishing automation. Those are separate decisions for later phases.
