# Phase 3 — BACnet Adapter Skeleton

This document describes the implementation decisions made in Phase 3 of basis-adapters.

---

## Goal

Introduce a BACnet adapter that normalizes BACnet service primitives into BASIS
authorization requests, following the same adapter contract pattern established by
the REST adapter in Phases 1 and 2.

Non-goals for this phase: live BACnet network communication, bacpypes, BACnet/IP
stack, gateway transport, authentication, enforcement, Docker, Kubernetes, CI/CD.

---

## Files Added

```
src/basis_adapters/bacnet/__init__.py       — package exports
src/basis_adapters/bacnet/mapping.py        — BacnetOperation, BacnetRouteMapping, BacnetMappingConfig
src/basis_adapters/bacnet/adapter.py        — BacnetAdapter

tests/test_bacnet_adapter.py                — normalization behavior tests
tests/test_bacnet_mapping.py                — mapping config and model tests
tests/test_bacnet_contract.py               — contract preservation tests

docs/architecture/bacnet-adapter.md        — architecture reference
docs/implementation/phase-3-bacnet-adapter.md  — this file
schemas/bacnet-mapping.schema.json         — JSON Schema for mapping config
examples/bacnet/mapping.example.json       — example BACnet mapping config
```

---

## Design Decisions

### BacnetOperation Is the Adapter's Input Type

The REST adapter accepts `ProtocolOperation`, a generic container. The BACnet adapter
accepts `BacnetOperation`, a domain-specific frozen dataclass with typed fields:
`service`, `object_type`, `object_instance` (int), `property_identifier`, `device_id`
(optional), `priority` (optional), `value_present` (bool).

This is intentional. BACnet operations have structured semantics that benefit from
named, typed fields. Generic key-value metadata would lose the structure that makes
matching meaningful.

`BacnetOperation` converts to `ProtocolOperation` via `to_protocol_operation()` for
use as `protocol_evidence`. This preserves the full operation in the normalized
request without requiring basis-gateway to understand BACnet-specific types.

### Matching Is Field Equality, Not Regex

REST matching compiles path patterns to anchored regular expressions. BACnet matching
compares three fields — `service`, `object_type`, `property_identifier` — for equality,
with `"*"` as a wildcard sentinel. This is simpler and more appropriate for the BACnet
object model, where field values are symbolic identifiers, not path segments.

### object_instance Is Not a Match Key

`object_instance` is an integer that identifies a specific object within an object_type.
It is not used as a match key in routing because routes describe authorization policies
over object *types*, not individual instances. Instance-level granularity is expressed
in the resource_id template (e.g., `{object_instance}` substituted into the resource ID),
where basis-gateway and basis-core can apply instance-level rules.

### Empty action Defers to Default Service Map

A `BacnetRouteMapping` with `action=""` defers action resolution to
`_DEFAULT_SERVICE_ACTION_MAP` at normalization time:

```
ReadProperty  → read
WriteProperty → write
SubscribeCOV  → subscribe
CommandValue  → control
```

This lets a single wildcard route cover all four services without requiring four
separate routes with explicit action values.

### device_id=None With a {device_id} Template Is a Hard Failure

If the resource_id template references `{device_id}` and the operation's `device_id`
is `None`, the adapter returns a normalization failure with an explicit error message.
Silently substituting an empty string would produce a malformed resource ID
(e.g., `:1:presentValue`) that might accidentally match an unrelated resource.
Explicit failure is safer.

### Protocol Evidence Path Format

The canonical path in `ProtocolOperation` is:
```
{object_type}:{object_instance}:{property_identifier}
```

This is compact, human-readable, and uniquely identifies the addressed object property.
The device_id, priority, and value_present fields are preserved in metadata rather than
encoded in the path, since path-based matching is not used for BACnet.

### No bacpypes Dependency

The BACnet adapter is a pure normalization library. It does not parse BACnet wire
packets, manage BACnet/IP sockets, or decode APDU frames. The caller is responsible
for obtaining a `BacnetOperation` from whatever BACnet transport layer they use.
This keeps the adapter portable and testable without a BACnet network.

---

## Test Strategy

Three test files cover different concerns:

**test_bacnet_mapping.py** — unit tests for `BacnetOperation`, `BacnetRouteMapping`,
and `BacnetMappingConfig`. Validates eager config validation, field matching, wildcard
semantics, first-match-wins ordering, template resolution, and from_dict parsing.

**test_bacnet_adapter.py** — integration tests for the four service primitives
(ReadProperty→read, WriteProperty→write, SubscribeCOV→subscribe, CommandValue→control),
wildcard matching, exact matching, template substitution, protocol evidence preservation,
failure result shapes, and subject hint forwarding.

**test_bacnet_contract.py** — contract tests that verify the adapter satisfies the
canonical adapter contract: AdapterResult shape invariants, absence of basis_core and
basis_gateway imports, protocol evidence always present, fail-closed semantics,
and normalize() never raises.

---

## Relationship to the REST Adapter

Both adapters share:
- `ProtocolOperation`, `NormalizedAuthorizationRequest`, `AdapterContext`, `AdapterResult` from `basis_adapters.models`
- `AdapterError`, `InvalidMappingError`, `UnknownRouteError` from `basis_adapters.errors`
- `VALID_ACTIONS` from `basis_adapters.rest.mapping`
- The fail-closed contract from `docs/contracts/adapter-contract.md`

They differ in:
- Input type: REST uses `ProtocolOperation`; BACnet uses `BacnetOperation`
- Matching: REST compiles path patterns to regex; BACnet uses field equality with wildcards
- Default action resolution: REST uses HTTP method defaults; BACnet uses service defaults
