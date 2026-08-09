# Cross-Protocol Normalization Contract

## Status

Stable — Phase 14

## Overview

Every adapter in `basis-adapters` produces a single output type:
`NormalizedAuthorizationRequest`. This document defines the canonical shape of
that output, how REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, and
Niagara all map into it, and how an enforcement boundary should consume it.

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
| `protocol` | string | yes | Originating protocol identifier (`"rest"`, `"bacnet"`, `"modbus"`, `"opcua"`, `"mqtt"`, `"dnp3"`, `"iec61850"`, `"knx"`, `"niagara"`) |
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

**DNP3:** `method` is the DNP3 operation name (e.g. `READ`, `SELECT`,
`OPERATE`, `DIRECT_OPERATE`). `path` is a deterministic outstation-rooted
address (e.g. `outstation:os-14/binary_output/7`). `metadata` carries
`operation`, `source_address`, `destination_address`, `outstation_id`,
`master_id`, `object_group`, `variation`, `point_index`, `point_type`,
`function_code`, `qualifier`, `control_code`, `control_model`, `event_class`,
and `value`. Note that addresses and `master_id` are evidence only — they are
never treated as verified identity — and command values stay in evidence,
never in resource IDs.

**IEC 61850:** `method` is the IEC 61850 operation name (e.g. `READ`,
`SELECT`, `OPERATE`, `DIRECT_OPERATE`, `ENABLE_REPORTING`). `path` is a
deterministic IED-rooted address (e.g. `ied:ied-sub1/ld:CTRL/ln:CSWI1/do:Pos`).
`metadata` carries `operation`, `ied_name`, `logical_device`, `logical_node`,
`data_object`, `data_attribute`, `functional_constraint`, `dataset`,
`report_control_block`, `goose_control_block`,
`sampled_values_control_block`, `control_model`, `origin`, `cause`,
`quality`, `timestamp`, and `value`. Note that `origin` is evidence only — it
is never treated as verified identity — and values, quality, timestamps, and
cause stay in evidence, never in resource IDs.

**KNX:** `method` is the KNX operation name (e.g. `GROUP_VALUE_READ`,
`GROUP_VALUE_WRITE`, `OBSERVE`). `path` is a deterministic group-rooted
address (e.g. `group:1/2/3/object:4`). `metadata` carries `operation`,
`group_address`, `individual_address`, `device_address`,
`communication_object`, `datapoint_type`, `payload_type`, `value`,
`priority`, `area`, `line`, and `device`. Note that `individual_address` is
evidence only — it is never treated as verified identity — and values,
payloads, priority, and datapoint types stay in evidence, never in resource
IDs.

**Niagara:** `method` is the Niagara operation name (e.g. `READ_POINT`,
`OVERRIDE_POINT`, `RESOLVE_ORD`). `path` is a deterministic station-rooted
address (e.g. `station:station-east/point:AHU1-SupplyTemp`). `metadata`
carries `operation`, `station`, `host`, `ord`, `component`, `slot`, `point`,
`point_type`, `value`, `facet`, `schedule`, `alarm`, `history`, `category`,
`baja_type`, `nav_path`, `niagara_user`, and `niagara_role`. Note that
`niagara_user` and `niagara_role` are evidence only — they are never treated
as BASIS identity, never copied into `subject_hint`, and never role-mapped —
and values, facets, and platform typing stay in evidence, never in resource
IDs.

All nine structures are nested under `protocol_evidence` so enforcement boundaries
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

## How DNP3 Maps into the Canonical Shape

```
DNP3 operation   → action (via route action or default operation→action map:
                   READ→read, SELECT→execute, OPERATE→execute,
                   DIRECT_OPERATE→execute, CONTROL→execute,
                   ENABLE_UNSOLICITED→subscribe)
route.resource_type → resource_type
resource_id_template rendered with DNP3 fields → resource_id
"dnp3"           → protocol
Dnp3Operation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for DNP3: `{operation}`, `{outstation_id}`, `{master_id}`,
`{source_address}`, `{destination_address}`, `{object_group}`, `{variation}`,
`{point_index}`, `{point_type}`, `{event_class}`. Optional fields are only
substitutable when present on the operation. Command values are never
template fields — they remain protocol evidence.

Example: a `READ` of analog input point 3 on outstation `os-14` with template
`dnp3:outstation:{outstation_id}/analog_input/{point_index}` produces
`resource_id = "dnp3:outstation:os-14/analog_input/3"`; a `DIRECT_OPERATE` of
binary output point 7 with template
`dnp3:outstation:{outstation_id}/binary_output/{point_index}` produces
`resource_id = "dnp3:outstation:os-14/binary_output/7"` and
`action = "execute"`. SELECT and OPERATE normalize independently — the
adapter keeps no select/operate state; the control model is preserved in
evidence.

## How IEC 61850 Maps into the Canonical Shape

```
IEC 61850 operation → action (via route action or default operation→action map:
                   READ→read, WRITE→write, SELECT→execute,
                   SELECT_WITH_VALUE→execute, OPERATE→execute,
                   DIRECT_OPERATE→execute, CANCEL→execute,
                   ENABLE_REPORTING→subscribe, ENABLE_GOOSE→subscribe,
                   ENABLE_SAMPLED_VALUES→subscribe)
route.resource_type → resource_type
resource_id_template rendered with IEC 61850 fields → resource_id
"iec61850"       → protocol
Iec61850Operation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for IEC 61850: `{operation}`, `{ied_name}`,
`{logical_device}`, `{logical_node}`, `{data_object}`, `{data_attribute}`,
`{functional_constraint}`, `{dataset}`, `{report_control_block}`,
`{goose_control_block}`, `{sampled_values_control_block}`. Optional fields
are only substitutable when present on the operation. Values, quality,
timestamps, origin, and cause are never template fields — they remain
protocol evidence.

Example: a `READ` of data attribute `mag` on data object `TotW` in logical
node `MMXU1` with template
`iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}/da:{data_attribute}`
produces `resource_id = "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag"`;
a `DIRECT_OPERATE` of data object `Pos` in switch controller `CSWI1` with
template
`iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}`
produces `resource_id = "iec61850:ied:ied-sub1/ld:CTRL/ln:CSWI1/do:Pos"` and
`action = "execute"`. SELECT and OPERATE normalize independently — the
adapter keeps no select/operate state; the control model (ctlModel) is
preserved in evidence.

## How KNX Maps into the Canonical Shape

```
KNX operation    → action (via route action or default operation→action map:
                   GROUP_VALUE_READ→read, GROUP_VALUE_WRITE→write,
                   GROUP_VALUE_RESPONSE→read, OBSERVE→subscribe)
route.resource_type → resource_type
resource_id_template rendered with KNX fields → resource_id
"knx"            → protocol
KnxOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for KNX: `{operation}`, `{group_address}`,
`{individual_address}`, `{device_address}`, `{communication_object}`,
`{area}`, `{line}`, `{device}`. Optional fields are only substitutable when
present on the operation. Values, payloads, payload types, priority, and
datapoint types are never template fields — they remain protocol evidence.

Example: a `GROUP_VALUE_READ` of group address `1/2/3` with template
`knx:group:{group_address}` produces `resource_id = "knx:group:1/2/3"`; a
`GROUP_VALUE_WRITE` of value `true` to the same address with the same
template produces the same `resource_id` and `action = "write"` — the written
value stays in evidence, never in the resource ID. Group addresses are
matched and preserved verbatim — no topology expansion, no semantic
inference. An `OBSERVE` of group address `2/0/14` produces
`action = "subscribe"` with no implication of live bus monitoring.

## How Niagara Maps into the Canonical Shape

```
Niagara operation → action (via route action or default operation→action map:
                   READ_COMPONENT/READ_POINT/READ_SLOT/READ_HISTORY/
                   READ_ALARM/READ_SCHEDULE→read,
                   WRITE_POINT/WRITE_SLOT/UPDATE_SCHEDULE→write,
                   ACK_ALARM/INVOKE_ACTION/COMMAND_POINT/OVERRIDE_POINT/
                   RELEASE_OVERRIDE→execute,
                   BROWSE/RESOLVE_ORD/LIST_CHILDREN→browse,
                   SUBSCRIBE_POINT/SUBSCRIBE_ALARM/SUBSCRIBE_HISTORY→subscribe)
route.resource_type → resource_type
resource_id_template rendered with Niagara fields → resource_id
"niagara"        → protocol
NiagaraOperation.to_protocol_operation() → protocol_evidence
metadata["subject_hint"] → subject_hint
```

Template fields for Niagara: `{operation}`, `{station}`, `{ord}`,
`{component}`, `{slot}`, `{point}`, `{schedule}`, `{alarm}`, `{history}`.
Optional fields are only substitutable when present on the operation. Values,
facets, point types, baja types, nav paths, categories, Niagara users, and
Niagara roles are never template fields — they remain protocol evidence, and
Niagara users/roles are never BASIS identity.

Example: a `READ_POINT` of point `AHU1-SupplyTemp` on station `station-east`
with template `niagara:station:{station}/point:{point}` produces
`resource_id = "niagara:station:station-east/point:AHU1-SupplyTemp"`; an
`OVERRIDE_POINT` of the same point produces `action = "execute"` — an
operational command, not a data write, with the override value, level, and
duration in evidence, never in the resource ID. A `RESOLVE_ORD` of
`station:|slot:/Drivers/BacnetNetwork/AHU1` with template
`niagara:station:{station}/ord:{ord}` produces `action = "browse"` with the
ORD preserved exactly — never parsed, never resolved, never followed.

All nine protocols produce the same field set. The canonical shape is
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

## Relationship to Adapter Evidence Construction

The per-protocol `protocol_evidence.metadata` fields documented above (§
"Protocol-Specific Evidence") are also the source table for
`basis_adapters.evidence`'s governed, closed per-protocol metadata
projection (`basis-adapter-evidence-v1`, per `basis-architecture`'s
ADR-0007) — see
[docs/public-api.md](../public-api.md#adapter-evidence-construction-basis_adaptersevidence).
That projection is a **separate, narrower artifact**: it governs only what
subset of `protocol_evidence.metadata` may be projected into digested
evidence material, never what `normalize()` itself returns.
`NormalizedAuthorizationRequest.protocol_evidence` remains exactly what this
document already defines — complete, verbatim, and unaffected by evidence
construction. `basis_adapters.evidence` does not construct a final
`adapter-evidence-reference`; it constructs only the evidence material and
its digest.

For REST specifically: the `basis-adapter-evidence-v1` REST projection
intentionally excludes all REST metadata. The original normalized request
continues to preserve complete REST protocol evidence — REST's `metadata`
(§ "How REST Maps into the Canonical Shape") is untouched by
`basis_adapters.evidence` and remains exactly what `RestAdapter.normalize()`
returns — but REST metadata does not contribute to the v1 adapter-evidence
digest. This is not redaction of the normalized request; it is a statement
about which fields one evidence-material profile version digests.

## Relationship to Other Contracts

- **`docs/contracts/adapter-contract.md`** — the per-adapter behavioral
  contract (fail-closed, no raises, protocol evidence always attached). This
  document extends it with the cross-protocol output shape.
- **`schemas/normalized-authorization-request.schema.json`** — machine-readable
  JSON Schema for the serialized form.
- **`examples/handoff/`** — concrete example payloads for REST, BACnet,
  Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, and Niagara.
