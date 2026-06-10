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
  handoff/
    rest-normalized-request.example.json     canonical REST handoff payload
    bacnet-normalized-request.example.json   canonical BACnet handoff payload
    modbus-normalized-request.example.json   canonical Modbus handoff payload
```

## Mapping Examples

Mapping configs are adapter input: they define how protocol operations map to
normalized actions, resource types, and resource IDs. Each protocol has its own
mapping schema, but all of them validate fail-fast — a structurally invalid config
raises `InvalidMappingError` at load time, before any operation is normalized.

`examples/rest/mapping-invalid.example.json` is intentionally broken. It exists to
prove that validation rejects bad configs; it must continue to fail schema
validation and config loading.

## Handoff Examples

Handoff examples are adapter output: serialized `NormalizedAuthorizationRequest`
payloads exactly as an enforcement boundary would receive them. All three protocols
emit the same canonical shape — same top-level fields, protocol detail confined to
`protocol_evidence`. Comparing the three files side by side is the quickest way to
see the cross-protocol normalization contract in action.

These files are illustrations of the contract in
`schemas/normalized-authorization-request.schema.json`; the schema is authoritative.

## Using the Examples in Code

Each adapter's package docstring (`basis_adapters.rest`, `basis_adapters.bacnet`,
`basis_adapters.modbus`) and the README show how to load a mapping example and
normalize an operation. The pattern is identical across protocols: load config via
`from_dict()`, construct an `AdapterContext`, call `adapter.normalize(op)`, and
respect the fail-closed contract — if `result.success` is false, do not forward
the operation.
