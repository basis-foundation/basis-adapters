# Public API

This document inventories the public-ish API surface of `basis-adapters` as of the
current pre-release state.

> **Stability:** This API is **pre-v1 and subject to change**. No semantic-versioning
> guarantees are made yet. That said, compatibility is treated carefully: breaking
> changes are deliberate, documented, and reflected in schemas, examples, and
> contract tests — never accidental. See [compatibility.md](compatibility.md).

The public surface is what each package exports via `__all__`. Anything not listed
below (module internals, helper functions, private attributes) is implementation
detail and may change without notice.

## Core (`basis_adapters`)

### Models

| Name | Kind | Purpose |
|---|---|---|
| `ProtocolOperation` | frozen dataclass | Raw operation as received from the wire protocol; un-normalized adapter input. Has `to_dict()`. |
| `NormalizedAuthorizationRequest` | frozen dataclass | Protocol-agnostic authorization request for handoff to basis-gateway. `to_dict()` emits the canonical shape in `schemas/normalized-authorization-request.schema.json`. |
| `AdapterContext` | frozen dataclass | Execution context (adapter ID + config) provided at normalization time. |
| `AdapterResult` | frozen dataclass | Outcome of a normalization attempt; exactly one of `request`/`error` set. Constructors `AdapterResult.ok()` / `AdapterResult.fail()`. |

### Errors

| Name | Purpose |
|---|---|
| `AdapterError` | Base exception for all adapter errors. |
| `InvalidMappingError` | Mapping configuration is structurally invalid; raised at config validation time (fail fast). |
| `UnknownRouteError` | Operation matches no configured route; adapters fail closed. |

## REST (`basis_adapters.rest`)

| Name | Purpose |
|---|---|
| `RestAdapter` | Normalizes HTTP method + path into a `NormalizedAuthorizationRequest`. |
| `RestMappingConfig` | Validated REST mapping configuration; `from_dict()` constructor. Schema: `schemas/rest-mapping.schema.json`. |
| `RouteMapping` | A single REST route mapping entry. |

## BACnet (`basis_adapters.bacnet`)

| Name | Purpose |
|---|---|
| `BacnetAdapter` | Normalizes BACnet service primitives into a `NormalizedAuthorizationRequest`. |
| `BacnetMappingConfig` | Validated BACnet mapping configuration; `from_dict()` constructor. Schema: `schemas/bacnet-mapping.schema.json`. |
| `BacnetOperation` | Typed BACnet operation (service, object type/instance, property, device). |
| `BacnetRouteMapping` | A single BACnet route mapping entry. |
| `VALID_BACNET_SERVICES` | Allowed BACnet service names. |
| `VALID_BACNET_TEMPLATE_FIELDS` | Allowed fields in BACnet resource-ID templates. |

## Modbus (`basis_adapters.modbus`)

| Name | Purpose |
|---|---|
| `ModbusAdapter` | Normalizes Modbus function requests into a `NormalizedAuthorizationRequest`. |
| `ModbusMappingConfig` | Validated Modbus mapping configuration; `from_dict()` constructor. Schema: `schemas/modbus-mapping.schema.json`. |
| `ModbusOperation` | Typed Modbus operation (function, unit ID, address, quantity). |
| `ModbusRouteMapping` | A single Modbus route mapping entry. |
| `VALID_MODBUS_FUNCTIONS` | Allowed Modbus function names. |
| `VALID_MODBUS_TEMPLATE_FIELDS` | Allowed fields in Modbus resource-ID templates. |

## OPC UA (`basis_adapters.opcua`)

| Name | Purpose |
|---|---|
| `OpcuaAdapter` | Normalizes OPC UA service requests into a `NormalizedAuthorizationRequest`. |
| `OpcuaMappingConfig` | Validated OPC UA mapping configuration; `from_dict()` constructor. Schema: `schemas/opcua-mapping.schema.json`. |
| `OpcuaOperation` | Typed OPC UA operation (service, node ID, attribute, method, namespace, session/endpoint evidence). |
| `OpcuaRouteMapping` | A single OPC UA route mapping entry. |
| `VALID_OPCUA_ACTIONS` | Normalized action verbs accepted for OPC UA routes (shared set plus `execute`, `browse`). |
| `VALID_OPCUA_IDENTIFIER_TYPES` | Allowed OPC UA node identifier types (`numeric`, `string`, `guid`, `opaque`). |
| `VALID_OPCUA_SERVICES` | Allowed OPC UA service names (`Read`, `Write`, `Call`, `Subscribe`, `Browse`). |
| `VALID_OPCUA_TEMPLATE_FIELDS` | Allowed fields in OPC UA resource-ID templates. |

## Serialization Contract

`NormalizedAuthorizationRequest.to_dict()` and `ProtocolOperation.to_dict()` are
part of the public surface. Their output is the canonical serialized handoff format
defined by `schemas/normalized-authorization-request.schema.json` and documented in
`docs/contracts/normalization-contract.md`. Output is deterministic, contains no
decision and no resolved identity, and always nests protocol evidence under
`protocol_evidence`.

## What Is Not Public

Anything not exported via `__all__`: internal matching/template-rendering helpers,
module-level constants not listed above, and test utilities. Relying on these is
unsupported.
