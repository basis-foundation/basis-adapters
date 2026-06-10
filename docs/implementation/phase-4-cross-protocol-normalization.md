# Phase 4 — Cross-Protocol Normalization Contract

## Status

Complete.

## Objective

Stabilize the shared output contract for the REST and BACnet adapters before
adding any additional protocol (Modbus, Niagara, MQTT, or otherwise). This
phase defines exactly what `NormalizedAuthorizationRequest` looks like across
protocols, how it serializes, and what enforcement boundaries should do with it.

## What Was Built

### Serialization support

`NormalizedAuthorizationRequest.to_dict()` — deterministic, JSON-compatible
serialization of the normalized output. Produces the canonical shape defined
in `schemas/normalized-authorization-request.schema.json`.

`ProtocolOperation.to_dict()` — serializes the protocol evidence embedded in
every normalized request.

### Contract documentation

`docs/contracts/normalization-contract.md` — the authoritative cross-protocol
contract. Covers:
- Canonical field definitions
- How REST and BACnet each map into the shared shape
- How enforcement boundaries consume normalized output
- The adapter topology model (embedded vs. adjacent)
- What adapters must never do

### JSON Schema

`schemas/normalized-authorization-request.schema.json` — machine-readable
schema for the serialized `NormalizedAuthorizationRequest`. Aligned with the
current model; no invented fields.

### Example handoff payloads

`examples/handoff/rest-normalized-request.example.json` — a realistic REST
adapter output, serialized and ready for handoff.

`examples/handoff/bacnet-normalized-request.example.json` — a realistic BACnet
adapter output, serialized and ready for handoff.

Both examples demonstrate that REST and BACnet produce identical field sets
while preserving protocol-specific evidence.

### Contract tests

`tests/test_normalization_contract.py` — 20 contract tests covering:
- REST serializes to canonical shape
- BACnet serializes to canonical shape
- Required fields present for both protocols
- Protocol evidence nested correctly
- No authorization decision field present
- No resolved subject identity field present
- No gateway transport code invoked
- No `basis_core` import exists
- REST and BACnet outputs share the same field set
- Serialization is deterministic

## What Was Not Built (Intentional Non-Goals)

- Modbus adapter — Phase 5
- Gateway HTTP client or transport — belongs outside adapters entirely
- `basis-core` integration — evaluation is not an adapter concern
- Authorization evaluation or enforcement
- Authentication or JWT validation
- Proxy server
- Docker, Kubernetes, GitHub Actions
- Packaging or publishing

## Governing Principle

> Adapters normalize. Gateway enforces. Kernel evaluates.

Nothing in this phase moves normalization logic into the enforcement boundary,
nor does it introduce enforcement logic into adapters. The handoff artifact
(`NormalizedAuthorizationRequest`) carries intent; it carries no decision.

## Recommended Phase 5 Scope

Phase 5 should add the Modbus adapter, which will immediately participate in
the cross-protocol contract defined here. By stabilizing the contract first
in Phase 4, the Modbus adapter can be validated against the same canonical
shape without revisiting design decisions.

Suggested deliverables for Phase 5:

- `src/basis_adapters/modbus/` — adapter + mapping
- `schemas/modbus-mapping.schema.json`
- `examples/modbus/mapping.example.json`
- `examples/handoff/modbus-normalized-request.example.json`
- `tests/test_modbus_adapter.py`, `tests/test_modbus_contract.py`
- Addition of Modbus to `tests/test_normalization_contract.py` cross-protocol
  field set checks
- `docs/architecture/modbus-adapter.md`
- `docs/implementation/phase-5-modbus-adapter.md`
