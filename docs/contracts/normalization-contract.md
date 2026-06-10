# Cross-Protocol Normalization Contract

## Status

Stable — Phase 10

## Overview

Every adapter in `basis-adapters` produces a single output type:
`NormalizedAuthorizationRequest`. This document defines the canonical shape of
that output, how REST, BACnet, Modbus, OPC UA, and MQTT all map into it, and
how an enforcement boundary should consume it.

---

## What the Normalized Authorization Request Is

The normalized authorization request is a **handoff artifact**.

> It is not a decision.
> It is not enforcement.
> It is not authentication.

It is the adapter's normalized description of *what a caller is trying to do*,
expressed in protocol-agnostic terms. An enforcement boundary uses it to
decide whether the operation should be allowed. The adapter itself does not
participate in that decision.

---

## Canonical Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol` | string | yes | Originating protocol identifier (`"rest"`, `"bacnet"`, `"modbus"`, `"opcua"`, `"mqtt"`) |
| `action` | string | yes | Normalized action verb (`"read"`, `"write"`, `"control"`, `"discover"`, `"subscribe"`, `"execute"`, `"browse"`) |
| `resource_type` | string | yes | Logical resource category (e.g. `"point"`, `"device"`, `"schedule"`) |
| `resource_id` | string | yes | Stable identifier for the target resource |
| `protocol_evidence` | object | yes | The original protocol operation, preserved verbatim for audit |
| `subject_hint` | string or null | no | Unverified identity hint forwarded from the protocol layer |

> `execute` (method invocation) and `browse` (address-space traversal) were
> added additively in Phase 7 for OPC UA. Existing protocol mappings and
> downstream consumers are unaffected; the action vocabulary only grew.

### Protocol Evidence

The `protocol_evidence` object is a serialized `ProtocolOperation`:

| Field | Type | Required | Description |
|---|---|---|---|
| `protocol` | string | yes | Protocol that produced this evidence (same as the parent `protocol` field) |
| `method` | string | yes | Protocol method or service name (e.g. `"GET"`, `"ReadProperty"`) |
| `path` | string | yes | Resource path or address in protocol-native form |
| `metadata` | object | yes | Additional protocol-specific fields (headers, qualifiers, BACnet properties, etc.) |

The `protocol_evidence` field is always present. Adapters must never strip it.
Enforcement boundaries and audit systems depend on it for traceability.

---

## Protocol-Independent Fields

`protocol`, `action`, `resource_type`, and `resource_id` are fully
protocol-independent. An enforcement boundary may evaluate policy using only
these fields and have no knowledge of REST or BACnet specifics.

## Protocol-Specific Evidence

`protocol_evidence` preserves everything the wire protocol delivered. Its
internal structure differs by protocol:

**REST:** `method` is the HTTP verb. `path` is the request path (query string
stripped). `metadata` may include `subject_hint` and any other HTTP-level
fields the adapter was given.

**BACnet:** `method` is the BACnet service name (e.g. `ReadProperty`). `path`
encodes object identity as `{object_type}:{object_instance}:{property_identifier}`.
`metadata` carries `service`, `object_type`, `object_instance`,
`property_identifier`, `device_id`, `priority`, and `value_present`.

**Modbus:** `method` is the Modbus function code name (e.g. `ReadHoldingRegisters`).
`path` encodes unit and address as `unit:{unit_id}:addr:{address}`. `metadata`
carries `function`, `unit_id`, `address`, `quantity`, `value_present`,
`register_type`, `source_address`, and `transaction_id`.

**OPC UA:** `method` is the OPC UA service name (e.g. `Read`, `Call`). `path`
is the target node identifier (e.g. `ns=2;s=Building.AHU1.SupplyTemp`).
`metadata` carries `service`, `node_id`, `attribute_id`, `method_id`,
`namespace_index`, `identifier`, `identifier_type`, `browse_name`,
`parent_node_id`, `subscription_id`, `monitored_item_id`, `value_present`,
`endpoint_url`, and `session_id`. Note that `session_id` and `endpoint_url`
are evidence only — they are never treated as verified identity.

**MQTT:** `method` is the MQTT operation name (`PUBLISH` or `SUBSCRIBE`).
`path` is the topic (or topic filter), preserved verbatim — including any
`+`/`#` wildcard characters, which are never expanded. `metadata` carries
`operation`, `topic`, `client_id`, `qos`, `retain`, `payload_type`, and
`protocol_version`. Note that `client_id` is evidence only — it is never
treated as verified identity.

All five structures are nested under `protocol_evidence` so enforcement boundaries
and audit systems can always find protocol-specific detail without it polluting
the canonical fields.

---

## How REST Maps into the Canonical Shape

```
HTTP method      → action (via route action_map or default method→action map)
route.resource_type → resource_type
resource_id_template rendered with path captures → resource_id
"rest"           → protocol
original ProtocolOperation → protocol_evidence
metadata["subject_hint"] → subject_hint
```

## How BACnet Maps into the Canonical Shape

```
BACnet service   → action (via route action or default service→action map)
route.resource_type → resource_type
resource_id_template rendered with BACnet fields → resource_id
"bacnet"         → protocol
BacnetOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

## How Modbus Maps into the Canonical Shape

```
Modbus function  → action (via route action or default function→action map)
route.resource_type → resource_type
resource_id_template rendered with Modbus fields → resource_id
"modbus"         → protocol
ModbusOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for Modbus: `{function}`, `{unit_id}`, `{address}`,
`{quantity}`, `{register_type}`.

## How OPC UA Maps into the Canonical Shape

```
OPC UA service   → action (via route action or default service→action map:
                   Read→read, Write→write, Call→execute,
                   Subscribe→subscribe, Browse→browse)
route.resource_type → resource_type
resource_id_template rendered with OPC UA fields → resource_id
"opcua"          → protocol
OpcuaOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for OPC UA: `{service}`, `{node_id}`, `{attribute_id}`,
`{method_id}`, `{namespace_index}`, `{browse_name}`, `{parent_node_id}`.
Optional fields are only substitutable when present on the operation.

Example: a `Read` of `ns=2;s=Building.AHU1.SupplyTemp` attribute `Value` with
template `{node_id}:{attribute_id}` produces
`resource_id = "ns=2;s=Building.AHU1.SupplyTemp:Value"`; a `Call` of method
`ns=2;s=Building.AHU1.Reset` on node `ns=2;s=Building.AHU1` with template
`{node_id}:method:{method_id}` produces
`resource_id = "ns=2;s=Building.AHU1:method:ns=2;s=Building.AHU1.Reset"`.

## How MQTT Maps into the Canonical Shape

```
MQTT operation   → action (via route action or default operation→action map:
                   PUBLISH→write, SUBSCRIBE→subscribe)
route.resource_type → resource_type
resource_id_template rendered with MQTT fields → resource_id
"mqtt"           → protocol
MqttOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for MQTT: `{operation}`, `{topic}`, `{client_id}`, `{qos}`,
`{payload_type}`. Optional fields are only substitutable when present on the
operation.

Example: a `PUBLISH` to `building/ahu-1/setpoint` with template
`mqtt:{topic}` produces `resource_id = "mqtt:building/ahu-1/setpoint"`; a
`SUBSCRIBE` to the topic filter `building/+/telemetry` with the same template
produces `resource_id = "mqtt:building/+/telemetry"` — the `+` wildcard is
preserved verbatim, never expanded. Wildcard authorization policy belongs to
policy evaluation, not the adapter.

All five protocols produce the same field set. The canonical shape is
identical; only `protocol` and `protocol_evidence` internals differ.

---

## How Enforcement Boundaries Should Consume the Output

An enforcement boundary receives a `NormalizedAuthorizationRequest` from an
adapter. It should:

1. **Authenticate the subject.** The `subject_hint` field is an unverified
   hint — it is not a credential. The enforcement boundary is responsible for
   resolving and verifying identity before submitting a decision request to
   `basis-core`. The adapter deliberately does not authenticate callers.

2. **Construct a `DecisionRequest`.** Pass `action`, `resource_type`, and
   `resource_id` (plus the verified subject) to `basis-core` for evaluation.

3. **Enforce the result.** Act on the decision returned by `basis-core`.
   The adapter does not receive, inspect, or act on authorization decisions.

4. **Preserve protocol evidence.** The `protocol_evidence` field should be
   forwarded to any audit trail or `AuditEvent` emitted after the decision.

### Fail-Closed Requirement

If normalization fails (`AdapterResult.success is False`), the enforcement
boundary **must not forward the operation**. A normalization failure is not an
authorization decision — it is a failure to produce one. Treat it as deny by
default.

---

## Adapter Topology

Adapters are normalization components. They may be embedded inside an
enforcement boundary or run adjacent to one. Topology must not change
semantics:

```
┌─────────────────────────────────────────────┐
│  Trusted enforcement boundary               │
│                                             │
│  ┌────────────┐    NormalizedAuthorization  │
│  │  Adapter   │ ─────────────Request──────► │ authenticate subject
│  └────────────┘                             │ submit DecisionRequest
│                                             │ enforce result
└─────────────────────────────────────────────┘
                                 │
                                 ▼
                           basis-core
                           evaluates
```

Whether the adapter runs inside or outside the enforcement boundary process,
the adapter itself still does not authenticate, evaluate policy, or enforce
decisions.

---

## What Adapters Must Never Do

- Authenticate callers or validate JWTs
- Call identity providers
- Evaluate policy
- Enforce decisions
- Reinterpret gateway or kernel decisions
- Call `basis-core`
- Call `basis-gateway` during normalization
- Become proxy servers

These responsibilities belong to the enforcement boundary and `basis-core`.

---

## Serialization

`NormalizedAuthorizationRequest.to_dict()` produces the canonical serialized
form. It is deterministic: the same input always produces identical output.
The output is JSON-compatible (no Python-specific types). The schema is defined
in `schemas/normalized-authorization-request.schema.json`.

Example handoff payloads are in `examples/handoff/`.

---

## Relationship to Other Contracts

- **`docs/contracts/adapter-contract.md`** — the per-adapter behavioral
  contract (fail-closed, no raises, protocol evidence always attached). This
  document extends it with the cross-protocol output shape.
- **`schemas/normalized-authorization-request.schema.json`** — machine-readable
  JSON Schema for the serialized form.
- **`examples/handoff/`** — concrete example payloads for REST, BACnet,
  Modbus, OPC UA, and MQTT.
