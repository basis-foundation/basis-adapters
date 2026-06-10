# Examples Guide

The `examples/` directory contains reference inputs and outputs for every adapter.
All of them are validated against the JSON Schemas in `schemas/` by the test suite
(see [schema-validation.md](schema-validation.md)).

## Layout

```
examples/
  rest/
    mapping.example.json           full REST mapping config
    mapping-minimal.example.json   smallest valid REST mapping config
    mapping-invalid.example.json   deliberately invalid config (negative test case)
  bacnet/
    mapping.example.json           BACnet mapping config
  modbus/
    mapping.example.json           Modbus mapping config
  opcua/
    mapping.example.json           OPC UA mapping config
  mqtt/
    mapping.example.json           MQTT mapping config
    mapping-invalid.example.json   deliberately invalid config (negative test case)
  dnp3/
    mapping.example.json           DNP3 mapping config
    mapping-invalid.example.json   deliberately invalid config (negative test case)
  iec61850/
    mapping.example.json           IEC 61850 mapping config
    mapping-invalid.example.json   deliberately invalid config (negative test case)
  handoff/
    rest-normalized-request.example.json           canonical REST handoff payload
    bacnet-normalized-request.example.json         canonical BACnet handoff payload
    modbus-normalized-request.example.json         canonical Modbus handoff payload
    opcua-normalized-request.example.json          canonical OPC UA handoff payload
    mqtt-publish-normalized-request.example.json   canonical MQTT PUBLISH handoff payload
    mqtt-subscribe-normalized-request.example.json canonical MQTT SUBSCRIBE handoff payload
    dnp3-read-normalized-request.example.json      canonical DNP3 READ handoff payload
    dnp3-direct-operate-normalized-request.example.json canonical DNP3 DIRECT_OPERATE handoff payload
    iec61850-read-normalized-request.example.json  canonical IEC 61850 READ handoff payload
    iec61850-direct-operate-normalized-request.example.json canonical IEC 61850 DIRECT_OPERATE handoff payload
    iec61850-enable-reporting-normalized-request.example.json canonical IEC 61850 ENABLE_REPORTING handoff payload
```

## Mapping Examples

Mapping configs are adapter input: they define how protocol operations map to
normalized actions, resource types, and resource IDs. Each protocol has its own
mapping schema, but all of them validate fail-fast — a structurally invalid config
raises `InvalidMappingError` at load time, before any operation is normalized.

`examples/rest/mapping-invalid.example.json`,
`examples/mqtt/mapping-invalid.example.json`,
`examples/dnp3/mapping-invalid.example.json`, and
`examples/iec61850/mapping-invalid.example.json` are intentionally broken. They exist
to prove that validation rejects bad configs; they must continue to fail schema
validation and config loading.

## Handoff Examples

Handoff examples are adapter output: serialized `NormalizedAuthorizationRequest`
payloads exactly as an enforcement boundary would receive them. All seven protocols
emit the same canonical shape — same top-level fields, protocol detail confined to
`protocol_evidence`. Comparing the files side by side is the quickest way to
see the cross-protocol normalization contract in action. The MQTT subscribe
example carries a `+` wildcard topic filter, preserved verbatim — wildcards are
never expanded by the adapter. The DNP3 direct-operate example carries CROB
control evidence (control code, control model, command value) — preserved in
`protocol_evidence`, never in the resource ID. The IEC 61850 direct-operate
example carries control evidence (control model, origin, cause, command
value) — likewise preserved in `protocol_evidence`, never in the resource ID.

These files are illustrations of the contract in
`schemas/normalized-authorization-request.schema.json`; the schema is authoritative.

## Using the Examples in Code

Each adapter's package docstring (`basis_adapters.rest`, `basis_adapters.bacnet`,
`basis_adapters.modbus`, `basis_adapters.opcua`, `basis_adapters.mqtt`,
`basis_adapters.dnp3`, `basis_adapters.iec61850`) and the
README show how to load a mapping example and normalize an operation. The pattern is identical across
protocols: load config via
`from_dict()`, construct an `AdapterContext`, call `adapter.normalize(op)`, and
respect the fail-closed contract — if `result.success` is false, do not forward
the operation.
