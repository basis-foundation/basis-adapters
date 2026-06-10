# Phase 12 — IEC 61850 Adapter Skeleton

## Objective

Add IEC 61850 as the seventh protocol family in `basis-adapters`, following
the established adapter pattern (REST, BACnet, Modbus, OPC UA, MQTT, DNP3).
The IEC 61850 adapter normalizes read, write, control, and
reporting/GOOSE/Sampled Values intents into canonical BASIS authorization
requests. Pure normalization — no MMS stack, no GOOSE subscriber, no Sampled
Values processor, no packet parsing, no live communication, no runtime
enforcement.

## What Was Built

- `src/basis_adapters/iec61850/` — `Iec61850Operation`,
  `Iec61850RouteMapping`, `Iec61850MappingConfig` (mapping.py),
  `Iec61850Adapter` (adapter.py), package exports (`__init__.py`). Follows
  the DNP3/MQTT module pattern exactly: frozen dataclasses, eager config
  validation, first-match-wins routing, fail-closed `normalize()` that never
  raises.
- `schemas/iec61850-mapping.schema.json` — mapping config schema.
- `examples/iec61850/mapping.example.json`,
  `examples/iec61850/mapping-invalid.example.json` — valid and deliberately
  invalid mapping configs.
- `examples/handoff/iec61850-read-normalized-request.example.json`,
  `examples/handoff/iec61850-direct-operate-normalized-request.example.json`,
  `examples/handoff/iec61850-enable-reporting-normalized-request.example.json`
  — canonical handoff payloads (the direct-operate example carries control
  evidence: control model, origin, cause, and command value).
- `docs/architecture/iec61850-adapter.md` — architecture documentation.
- Tests: `test_iec61850_adapter.py`, `test_iec61850_mapping.py`,
  `test_iec61850_contract.py`, plus IEC 61850 coverage in
  `test_normalization_contract.py` (seven-way parity) and
  `test_schema_examples.py`.

## Key Design Decisions

- **No new action vocabulary.** READ→`read`; WRITE→`write`;
  SELECT/SELECT_WITH_VALUE/OPERATE/DIRECT_OPERATE/CANCEL→`execute` (control
  commands are commands to equipment, preferred over `write`);
  ENABLE_REPORTING/ENABLE_GOOSE/ENABLE_SAMPLED_VALUES→`subscribe`. Routes may
  override using existing canonical actions. The canonical action enum is
  unchanged.
- **Hierarchical target identity.** Every operation must carry `ied_name`;
  `logical_node` requires `logical_device`, `data_object` requires
  `logical_node`, `data_attribute` requires `data_object`. READ/WRITE
  require a logical node; control operations require a data object, and
  control routes must reference `{data_object}` in their templates (the
  DNP3 `{point_index}` pattern). Subscription routes must reference their
  control block field.
- **Stateless select-before-operate.** SELECT, SELECT_WITH_VALUE, OPERATE,
  CANCEL, and DIRECT_OPERATE normalize independently; the adapter keeps no
  correlation, timeout, sequencing, or confirmation state. The
  `control_model` (ctlModel: status_only, direct/sbo × normal/enhanced
  security) is preserved in evidence, and inconsistent declarations fail
  closed.
- **GOOSE and Sampled Values: enable intent only.** ENABLE_GOOSE and
  ENABLE_SAMPLED_VALUES→`subscribe` with control block identity preserved as
  evidence. No multicast behavior, frame parsing, timing semantics,
  protection-trip behavior, or stream processing — documented limitations,
  not invented runtime models.
- **Reporting: enable intent only.** ENABLE_REPORTING→`subscribe`; report
  control block and dataset preserved as evidence. No buffering, integrity
  periods, confirmations, or event sequencing.
- **Values and protocol state are evidence, never identity.** `value`,
  `quality`, `timestamp`, `origin`, and `cause` are preserved in
  `protocol_evidence.metadata` and are not valid resource ID template
  fields. `origin` is never copied into `subject_hint`.
- **Resource ID convention:**
  `iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}/da:{data_attribute}`
  with `/rcb:`, `/gcb:`, and `/svcb:` segments for control blocks.

## Validation Behavior (Fail Closed)

| Invalid input | Outcome |
|---|---|
| Missing/empty/unsupported operation (incl. lowercase) | failure result |
| Missing ied_name | failure result |
| logical_node without logical_device; data_object without logical_node; data_attribute without data_object | failure result |
| READ/WRITE without logical_node | failure result |
| Control operation without data_object | failure result |
| Subscription operation without its control block (or logical_node) | failure result |
| Unknown functional_constraint | failure result |
| Unknown control_model; control_model inconsistent with operation (DIRECT_OPERATE + sbo_*, SELECT/OPERATE/CANCEL + direct_*, any control op + status_only) | failure result |
| Empty string in any optional identity field; non-dict origin | failure result |
| Malformed mapping config; control route without `{data_object}`; subscription route without its control block field; evidence-only fields (`{value}`, `{quality}`, `{timestamp}`, `{origin}`, `{cause}`) in templates | `InvalidMappingError` at construction |
| No matching route | `UnknownRouteError` → failure result |

## Status

The IEC 61850 adapter is **normalization-complete, not a live IEC 61850
client, server, MMS stack, GOOSE subscriber, Sampled Values processor, or
substation gateway.** See `docs/architecture/iec61850-adapter.md`.

## Suggested Next Phase

Phase 13 — KNX adapter skeleton.
