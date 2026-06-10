# Phase 13 — KNX Adapter Skeleton

## Objective

Add KNX as the eighth protocol family in `basis-adapters`, following the
established adapter pattern (REST, BACnet, Modbus, OPC UA, MQTT, DNP3,
IEC 61850). The KNX adapter normalizes group value read, group value write,
group value response, and observe/monitor intents into canonical BASIS
authorization requests. Pure normalization — no KNX/IP tunneling, no routing,
no multicast, no bus monitoring, no packet parsing, no live communication, no
runtime enforcement.

## What Was Built

- `src/basis_adapters/knx/` — `KnxOperation`, `KnxRouteMapping`,
  `KnxMappingConfig` (mapping.py), `KnxAdapter` (adapter.py), package
  exports (`__init__.py`). Follows the IEC 61850/MQTT module pattern
  exactly: frozen dataclasses, eager config validation, first-match-wins
  routing, fail-closed `normalize()` that never raises.
- `schemas/knx-mapping.schema.json` — mapping config schema.
- `examples/knx/mapping.example.json`,
  `examples/knx/mapping-invalid.example.json` — valid and deliberately
  invalid mapping configs.
- `examples/handoff/knx-group-value-read-normalized-request.example.json`,
  `examples/handoff/knx-group-value-write-normalized-request.example.json`,
  `examples/handoff/knx-observe-normalized-request.example.json` — canonical
  handoff payloads (the write example carries the written value, datapoint
  type, and frame priority as evidence).
- `docs/architecture/knx-adapter.md` — architecture documentation.
- Tests: `test_knx_adapter.py`, `test_knx_mapping.py`,
  `test_knx_contract.py`, plus KNX coverage in
  `test_normalization_contract.py` (eight-way parity) and
  `test_schema_examples.py`.

## Key Design Decisions

- **No new action vocabulary.** GROUP_VALUE_READ→`read`;
  GROUP_VALUE_WRITE→`write`; GROUP_VALUE_RESPONSE→`read` (a response is data
  flowing back to a reader — read semantics); OBSERVE→`subscribe` (explicit
  monitoring intent, the MQTT SUBSCRIBE / DNP3 ENABLE_UNSOLICITED pattern).
  Routes may override using existing canonical actions. The canonical action
  enum is unchanged.
- **Group addresses are verbatim identifiers.** Three-level (`1/2/3`),
  two-level (`1/200`), and free-style (`2563`) notations are accepted and
  validated for format and KNX range limits only. Route matching is exact
  string comparison or `"*"` — no topology expansion, no room/floor/equipment
  inference, no group-address authorization logic in the adapter.
- **Every supported operation requires a group address.** All four supported
  operations are group-address operations; a missing or malformed group
  address fails closed.
- **Datapoint types are evidence with a shape check only.** DPT notation
  (e.g. `1.001`) is validated for basic shape; payload semantics are not
  parsed, values are never coerced into operational meaning, and no policy
  decisions are made on DPT.
- **Observe means intent, not monitoring.** OBSERVE→`subscribe` normalizes a
  declared monitoring intent. No bus sniffing, no multicast monitoring, no
  KNX/IP routing or tunneling, no retained bus state. GROUP_VALUE_RESPONSE
  is normalized statelessly — no correlation with prior reads.
- **Values and protocol state are evidence, never identity.** `value`,
  `payload_type`, `priority`, and `datapoint_type` are preserved in
  `protocol_evidence.metadata` and are not valid resource ID template
  fields. `individual_address` is never copied into `subject_hint`.
- **Resource ID convention:** `knx:group:{group_address}`, optionally
  extended with `/object:{communication_object}`, or device-rooted
  `knx:device:{device_address}/object:{communication_object}`.

## Validation Behavior (Fail Closed)

| Invalid input | Outcome |
|---|---|
| Missing/empty/unsupported operation (incl. lowercase) | failure result |
| Missing group_address | failure result |
| Malformed group address (format or range, e.g. `1/8/3`, `32/2/3`, `a/b/c`) | failure result |
| Malformed individual_address or device_address (e.g. `16.1.5`, `1.1`, `1-1-5`) | failure result |
| Non-integer or negative communication_object | failure result |
| Malformed datapoint_type (e.g. `dpt-1`, `1_001`) | failure result |
| Invalid priority (not system/urgent/normal/low) | failure result |
| Out-of-range area/line/device topology evidence | failure result |
| Malformed mapping config; evidence-only fields (`{value}`, `{payload_type}`, `{priority}`, `{datapoint_type}`) in templates | `InvalidMappingError` at construction |
| No matching route | `UnknownRouteError` → failure result |

## Status

The KNX adapter is **normalization-complete, not a live KNX/IP client,
router, tunnel, multicast listener, bus monitor, or building automation
controller.** See `docs/architecture/knx-adapter.md`.

## Suggested Next Phase

Phase 14 — Niagara adapter skeleton.
