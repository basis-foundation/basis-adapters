# Phase 11 — DNP3 Adapter Skeleton

## Objective

Add DNP3 as the sixth protocol family in `basis-adapters`, following the
established adapter pattern (REST, BACnet, Modbus, OPC UA, MQTT). The DNP3
adapter normalizes read and control intents into canonical BASIS
authorization requests. Pure normalization — no DNP3 master or outstation, no
protocol stack, no packet parsing, no live communication, no runtime
enforcement.

## What Was Built

- `src/basis_adapters/dnp3/` — `Dnp3Operation`, `Dnp3RouteMapping`,
  `Dnp3MappingConfig` (mapping.py), `Dnp3Adapter` (adapter.py), package
  exports (`__init__.py`). Follows the OPC UA/MQTT module pattern exactly:
  frozen dataclasses, eager config validation, first-match-wins routing,
  fail-closed `normalize()` that never raises.
- `schemas/dnp3-mapping.schema.json` — mapping config schema.
- `examples/dnp3/mapping.example.json`,
  `examples/dnp3/mapping-invalid.example.json` — valid and deliberately
  invalid mapping configs.
- `examples/handoff/dnp3-read-normalized-request.example.json`,
  `examples/handoff/dnp3-direct-operate-normalized-request.example.json` —
  canonical handoff payloads (the direct-operate example carries CROB
  evidence: control code, control model, and command value).
- `docs/architecture/dnp3-adapter.md` — architecture documentation.
- Tests: `test_dnp3_adapter.py`, `test_dnp3_mapping.py`,
  `test_dnp3_contract.py`, plus DNP3 coverage in
  `test_normalization_contract.py` (six-way parity) and
  `test_schema_examples.py`.

## Key Design Decisions

- **No new action vocabulary.** READ→`read`;
  SELECT/OPERATE/DIRECT_OPERATE/CONTROL→`execute` (control commands are
  commands to equipment, preferred over `write`);
  ENABLE_UNSOLICITED→`subscribe`. Routes may override using existing
  canonical actions. The canonical action enum is unchanged.
- **Protocol-native operation names.** `Dnp3Operation.operation` is `"READ"`,
  `"SELECT"`, `"OPERATE"`, `"DIRECT_OPERATE"`, `"CONTROL"`, or
  `"ENABLE_UNSOLICITED"` — uppercase DNP3 function names, consistent with
  `"GET"`, `"ReadProperty"`, `"PUBLISH"`. Lowercase variants fail closed.
- **Required target identity.** Every operation must carry `outstation_id`
  or `destination_address`; control operations must additionally carry
  `point_index`, and control routes must reference `{point_index}` in their
  templates (the OPC UA Call/`{method_id}` pattern).
- **Stateless select-before-operate.** SELECT and OPERATE normalize
  independently; the adapter keeps no correlation, timeout, sequencing, or
  replay state. The `control_model` is preserved in evidence, and
  inconsistent declarations fail closed.
- **Events: one clear mapping only.** ENABLE_UNSOLICITED→`subscribe`
  (authorization to receive updates). Unsolicited delivery, event buffering,
  confirmations, and session behavior are documented limitations, not
  invented runtime models.
- **Values are evidence, never identity.** `value` and `control_code` are
  preserved in `protocol_evidence.metadata` and are not valid resource ID
  template fields.
- **Resource ID convention:**
  `dnp3:outstation:{outstation_id}/{point_type}/{point_index}` and
  `dnp3:outstation:{outstation_id}/group/{object_group}/variation/{variation}`.

## Validation Behavior (Fail Closed)

| Invalid input | Outcome |
|---|---|
| Missing/empty/unsupported operation (incl. lowercase) | failure result |
| No outstation_id and no destination_address | failure result |
| Address outside 0-65535, or non-integer | failure result |
| object_group / variation / function_code / qualifier / control_code outside 0-255 | failure result |
| variation without object_group | failure result |
| Negative or non-integer point_index | failure result |
| Unknown point_type | failure result |
| Unknown control_model; control_model inconsistent with operation | failure result |
| Control operation without point_index | failure result |
| event_class outside 0-3 | failure result |
| Malformed mapping config; control route without `{point_index}` | `InvalidMappingError` at construction |
| No matching route | `UnknownRouteError` → failure result |

## Status

The DNP3 adapter is **normalization-complete, not a live DNP3 master,
outstation, proxy, or protocol stack.** See
`docs/architecture/dnp3-adapter.md`.

## Suggested Next Phase

Phase 12 — IEC 61850 adapter skeleton.
