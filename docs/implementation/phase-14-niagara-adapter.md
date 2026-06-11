# Phase 14 — Niagara Adapter Skeleton

## Objective

Add Niagara as the ninth protocol family in `basis-adapters`, following the
established adapter pattern (REST, BACnet, Modbus, OPC UA, MQTT, DNP3,
IEC 61850, KNX) — and the first **platform-operation** adapter rather than a
device-protocol adapter. The Niagara adapter normalizes representative
Niagara platform operations (reads, writes, invokes/commands/overrides,
browsing/ORD resolution, and subscriptions across components, points, slots,
histories, alarms, and schedules) into canonical BASIS authorization
requests. Pure normalization — no Fox/Foxs client, no Baja runtime, no
Haystack client, no REST connector, no station/supervisor/JACE connectivity,
no packet parsing, no live communication, no Niagara permission system, no
runtime enforcement.

This phase completes the initial planned adapter roadmap.

## What Was Built

- `src/basis_adapters/niagara/` — `NiagaraOperation`,
  `NiagaraRouteMapping`, `NiagaraMappingConfig` (mapping.py),
  `NiagaraAdapter` (adapter.py), package exports (`__init__.py`). Follows
  the KNX/IEC 61850 module pattern exactly: frozen dataclasses, eager
  config validation, first-match-wins routing, fail-closed `normalize()`
  that never raises.
- `schemas/niagara-mapping.schema.json` — mapping config schema.
- `examples/niagara/mapping.example.json`,
  `examples/niagara/mapping-invalid.example.json` — valid and deliberately
  invalid mapping configs.
- `examples/handoff/niagara-point-read-normalized-request.example.json`,
  `examples/handoff/niagara-override-normalized-request.example.json`,
  `examples/handoff/niagara-resolve-ord-normalized-request.example.json`,
  `examples/handoff/niagara-ack-alarm-normalized-request.example.json` —
  canonical handoff payloads (the override example carries the override
  value, level, and duration as evidence; the override and ack-alarm
  examples carry `niagara_user`/`niagara_role` as evidence with
  `subject_hint` null).
- `docs/architecture/niagara-adapter.md` — architecture documentation.
- Tests: `test_niagara_adapter.py`, `test_niagara_mapping.py`,
  `test_niagara_contract.py`, plus Niagara coverage in
  `test_normalization_contract.py` (nine-way parity) and
  `test_schema_examples.py`.

## Key Design Decisions

- **Platform adapter, not a driver.** Niagara is modeled as a set of
  representative platform-operation intents, not as Fox/Foxs services or a
  component-model runtime. The operation model is deliberately small and
  does not attempt to model the full Niagara platform.
- **No new action vocabulary.** READ_* → `read`; WRITE_POINT/WRITE_SLOT/
  UPDATE_SCHEDULE → `write`; ACK_ALARM/INVOKE_ACTION/COMMAND_POINT/
  OVERRIDE_POINT/RELEASE_OVERRIDE → `execute`; BROWSE/RESOLVE_ORD/
  LIST_CHILDREN → `browse`; SUBSCRIBE_* → `subscribe`. The `execute` and
  `browse` verbs already existed (introduced for OPC UA); the canonical
  action enum is unchanged.
- **ACK_ALARM → `execute`.** Acknowledgement is treated as an action/event
  on the alarm rather than a data write; routes may override using existing
  canonical actions.
- **Identity boundary is explicit.** `niagara_user` and `niagara_role` are
  evidence only: never copied into `subject_hint`, never treated as BASIS
  identity, never interpreted, never role-mapped, and never valid in
  resource ID templates. Identity belongs to basis-gateway.
- **ORDs are opaque verbatim identifiers.** No grammar parsing, no
  resolution, no link following, no component-meaning inference. ORDs may
  participate in deterministic resource IDs via `{ord}`.
- **Every operation requires a station** (resource IDs are
  station-rooted), and target-specific operations require their target
  field (point/slot/component/alarm/history/schedule/ord; INVOKE_ACTION
  requires at least one of component/point/ord).
- **Values, facets, and platform typing are evidence, never identity.**
  `value`, `facet`, `point_type`, `baja_type`, `nav_path`, and `category`
  are preserved in `protocol_evidence.metadata` and are not valid resource
  ID template fields.
- **Override/release are stateless execute intents.** No priority-array
  behavior, no override state, no release semantics, no command state;
  override metadata (duration, level) is preserved as evidence.
- **Resource ID convention:** station-rooted —
  `niagara:station:{station}/point:{point}`,
  `niagara:station:{station}/ord:{ord}`,
  `niagara:station:{station}/component:{component}/slot:{slot}`,
  `niagara:station:{station}/history:{history}`,
  `niagara:station:{station}/alarm:{alarm}`,
  `niagara:station:{station}/schedule:{schedule}`.

## Validation Behavior (Fail Closed)

| Invalid input | Outcome |
|---|---|
| Missing/empty/unsupported operation (incl. lowercase) | failure result |
| Missing or empty station | failure result |
| Missing target field for target-specific operations (e.g. READ_POINT without point, ACK_ALARM without alarm, READ_HISTORY without history, UPDATE_SCHEDULE without schedule, RESOLVE_ORD without ord) | failure result |
| INVOKE_ACTION without component/point/ord | failure result |
| Empty optional string fields (e.g. blank ord, blank niagara_user) | failure result |
| Malformed mapping config; evidence-only fields (`{value}`, `{facet}`, `{point_type}`, `{baja_type}`, `{nav_path}`, `{category}`, `{niagara_user}`, `{niagara_role}`) in templates | `InvalidMappingError` at construction |
| Template referencing a field absent on the operation | failure result at render time |
| No matching route | `UnknownRouteError` → failure result |

## Status

The Niagara adapter is **normalization-complete, not a live Niagara station
integration, Fox/Foxs client, Baja runtime, Haystack client, REST connector,
station driver, supervisor integration, JACE integration, or Niagara
permission system.** See `docs/architecture/niagara-adapter.md`.

With Niagara complete, the initial planned adapter roadmap (REST, BACnet,
Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, Niagara) is complete.

## Suggested Next Phase

Phase 15 — adapter release readiness / v0.1.0 preparation.
