# Phase 10 — MQTT Adapter Skeleton

## Objective

Add MQTT as the fifth protocol family in `basis-adapters`, following the
established adapter pattern (REST, BACnet, Modbus, OPC UA). The MQTT adapter
normalizes PUBLISH and SUBSCRIBE intents into canonical BASIS authorization
requests. Pure normalization — no broker connectivity, no client library, no
packet parsing, no TLS, no runtime enforcement.

## What Was Built

- `src/basis_adapters/mqtt/` — `MqttOperation`, `MqttRouteMapping`,
  `MqttMappingConfig` (mapping.py), `MqttAdapter` (adapter.py), package
  exports (`__init__.py`). Follows the Modbus/OPC UA module pattern exactly:
  frozen dataclasses, eager config validation, first-match-wins routing,
  fail-closed `normalize()` that never raises.
- `schemas/mqtt-mapping.schema.json` — mapping config schema.
- `examples/mqtt/mapping.example.json`,
  `examples/mqtt/mapping-invalid.example.json` — valid and deliberately
  invalid mapping configs.
- `examples/handoff/mqtt-publish-normalized-request.example.json`,
  `examples/handoff/mqtt-subscribe-normalized-request.example.json` —
  canonical handoff payloads (the subscribe example carries a `+` wildcard
  filter, preserved verbatim).
- `docs/architecture/mqtt-adapter.md` — architecture documentation.
- Tests: `test_mqtt_adapter.py`, `test_mqtt_mapping.py`,
  `test_mqtt_contract.py`, plus MQTT coverage in
  `test_normalization_contract.py` (five-way parity) and
  `test_schema_examples.py`.

## Key Design Decisions

- **No new action vocabulary.** PUBLISH→`write`, SUBSCRIBE→`subscribe` via
  the default operation→action map; routes may override (e.g. `control` for
  command topics). The canonical action enum is unchanged — unlike Phase 7,
  no additive schema change was needed.
- **Protocol-native operation names.** `MqttOperation.operation` is
  `"PUBLISH"` or `"SUBSCRIBE"` (MQTT packet names), consistent with `"GET"`,
  `"ReadProperty"`, `"ReadHoldingRegisters"`, `"Read"`. Lowercase variants
  fail closed — no silent coercion.
- **Wildcards preserved, never expanded.** Topic filters containing `+`/`#`
  normalize to a single request with the filter verbatim in `resource_id`
  and evidence. Route topic matching is literal string equality (or the
  `"*"` sentinel) — no MQTT filter semantics in the adapter.
- **`client_id` is evidence, never identity.** It is preserved in
  `protocol_evidence.metadata` and never copied into `subject_hint`
  (asserted by contract tests).
- **Operation-level runtime validation** in `adapter._validate_operation()`
  raising bare `AdapterError` (the OPC UA pattern): unsupported operation,
  empty topic, QoS outside {0,1,2} (booleans rejected), non-boolean retain,
  retain=True on SUBSCRIBE, unknown payload_type, empty client_id /
  protocol_version when present.
- **Resource ID convention:** `mqtt:{topic}`.

## Validation Behavior (Fail Closed)

| Invalid input | Outcome |
|---|---|
| Missing/empty/whitespace topic | failure result |
| Unsupported operation (e.g. CONNECT, lowercase publish) | failure result |
| QoS not in {0, 1, 2} | failure result |
| Non-boolean retain; retain=True on SUBSCRIBE | failure result |
| Unknown payload_type | failure result |
| Template references `{client_id}` with no client_id | failure result |
| Malformed mapping config | `InvalidMappingError` at construction |
| No matching route | `UnknownRouteError` → failure result |

## Status

The MQTT adapter is **normalization-complete, not a live MQTT broker, proxy,
or MQTT client implementation.** See `docs/architecture/mqtt-adapter.md`.

## Suggested Next Phase

Phase 11 — DNP3 adapter skeleton.
