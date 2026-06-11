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

## MQTT (`basis_adapters.mqtt`)

| Name | Purpose |
|---|---|
| `MqttAdapter` | Normalizes MQTT PUBLISH/SUBSCRIBE intents into a `NormalizedAuthorizationRequest`. |
| `MqttMappingConfig` | Validated MQTT mapping configuration; `from_dict()` constructor. Schema: `schemas/mqtt-mapping.schema.json`. |
| `MqttOperation` | Typed MQTT operation (operation, topic, client ID, QoS, retain, payload type, protocol version). |
| `MqttRouteMapping` | A single MQTT route mapping entry. |
| `VALID_MQTT_OPERATIONS` | Allowed MQTT operation names (`PUBLISH`, `SUBSCRIBE`). |
| `VALID_MQTT_PAYLOAD_TYPES` | Allowed declared payload types (`json`, `text`, `binary`, `unknown`). |
| `VALID_MQTT_QOS_LEVELS` | Allowed QoS levels (0, 1, 2). |
| `VALID_MQTT_TEMPLATE_FIELDS` | Allowed fields in MQTT resource-ID templates. |

## DNP3 (`basis_adapters.dnp3`)

| Name | Purpose |
|---|---|
| `Dnp3Adapter` | Normalizes DNP3 read/control intents into a `NormalizedAuthorizationRequest`. |
| `Dnp3MappingConfig` | Validated DNP3 mapping configuration; `from_dict()` constructor. Schema: `schemas/dnp3-mapping.schema.json`. |
| `Dnp3Operation` | Typed DNP3 operation (operation, addresses, outstation/master, object group/variation, point identity, control evidence). |
| `Dnp3RouteMapping` | A single DNP3 route mapping entry. |
| `DNP3_CONTROL_OPERATIONS` | DNP3 operations treated as point-specific control commands (`SELECT`, `OPERATE`, `DIRECT_OPERATE`, `CONTROL`). |
| `VALID_DNP3_ACTIONS` | Normalized action verbs accepted for DNP3 routes (shared set plus `execute`). |
| `VALID_DNP3_CONTROL_MODELS` | Allowed control models (`select_before_operate`, `direct_operate`). |
| `VALID_DNP3_OPERATIONS` | Allowed DNP3 operation names (`READ`, `SELECT`, `OPERATE`, `DIRECT_OPERATE`, `CONTROL`, `ENABLE_UNSOLICITED`). |
| `VALID_DNP3_POINT_TYPES` | Allowed DNP3 point types (`binary_input`, `binary_output`, `analog_input`, `analog_output`, `counter`, `frozen_counter`). |
| `VALID_DNP3_TEMPLATE_FIELDS` | Allowed fields in DNP3 resource-ID templates. |

## IEC 61850 (`basis_adapters.iec61850`)

| Name | Purpose |
|---|---|
| `Iec61850Adapter` | Normalizes IEC 61850 read/write/control/reporting intents into a `NormalizedAuthorizationRequest`. |
| `Iec61850MappingConfig` | Validated IEC 61850 mapping configuration; `from_dict()` constructor. Schema: `schemas/iec61850-mapping.schema.json`. |
| `Iec61850Operation` | Typed IEC 61850 operation (operation, IED/logical device/logical node/data object/data attribute identity, functional constraint, dataset, control block names, control evidence). |
| `Iec61850RouteMapping` | A single IEC 61850 route mapping entry. |
| `IEC61850_CONTROL_OPERATIONS` | IEC 61850 operations treated as data-object-specific control commands (`SELECT`, `SELECT_WITH_VALUE`, `OPERATE`, `DIRECT_OPERATE`, `CANCEL`). |
| `IEC61850_SUBSCRIPTION_OPERATIONS` | IEC 61850 operations treated as control-block subscriptions (`ENABLE_REPORTING`, `ENABLE_GOOSE`, `ENABLE_SAMPLED_VALUES`). |
| `IEC61850_SBO_CONTROL_MODELS` | Control models declaring select-before-operate semantics. |
| `IEC61850_DIRECT_CONTROL_MODELS` | Control models declaring direct-operate semantics. |
| `VALID_IEC61850_ACTIONS` | Normalized action verbs accepted for IEC 61850 routes (shared set plus `execute`). |
| `VALID_IEC61850_CONTROL_MODELS` | Allowed control models (`status_only`, `direct_with_normal_security`, `sbo_with_normal_security`, `direct_with_enhanced_security`, `sbo_with_enhanced_security`). |
| `VALID_IEC61850_FUNCTIONAL_CONSTRAINTS` | Allowed functional constraints (`ST`, `MX`, `CO`, `SP`, `CF`, ...). |
| `VALID_IEC61850_OPERATIONS` | Allowed IEC 61850 operation names (`READ`, `WRITE`, `SELECT`, `SELECT_WITH_VALUE`, `OPERATE`, `DIRECT_OPERATE`, `CANCEL`, `ENABLE_REPORTING`, `ENABLE_GOOSE`, `ENABLE_SAMPLED_VALUES`). |
| `VALID_IEC61850_TEMPLATE_FIELDS` | Allowed fields in IEC 61850 resource-ID templates. |

## KNX (`basis_adapters.knx`)

| Name | Purpose |
|---|---|
| `KnxAdapter` | Normalizes KNX group value read/write/response and observe intents into a `NormalizedAuthorizationRequest`. |
| `KnxMappingConfig` | Validated KNX mapping configuration; `from_dict()` constructor. Schema: `schemas/knx-mapping.schema.json`. |
| `KnxOperation` | Typed KNX operation (operation, group address, individual/device address, communication object, datapoint type, payload/value/priority evidence, topology area/line/device). |
| `KnxRouteMapping` | A single KNX route mapping entry. |
| `VALID_KNX_ACTIONS` | Normalized action verbs accepted for KNX routes (shared set, unchanged). |
| `VALID_KNX_OPERATIONS` | Allowed KNX operation names (`GROUP_VALUE_READ`, `GROUP_VALUE_WRITE`, `GROUP_VALUE_RESPONSE`, `OBSERVE`). |
| `VALID_KNX_PRIORITIES` | Allowed KNX frame priorities (`system`, `urgent`, `normal`, `low`). |
| `VALID_KNX_TEMPLATE_FIELDS` | Allowed fields in KNX resource-ID templates. |

## Niagara (`basis_adapters.niagara`)

| Name | Purpose |
|---|---|
| `NiagaraAdapter` | Normalizes Niagara platform read/write/invoke/browse/subscribe intents into a `NormalizedAuthorizationRequest`. |
| `NiagaraMappingConfig` | Validated Niagara mapping configuration; `from_dict()` constructor. Schema: `schemas/niagara-mapping.schema.json`. |
| `NiagaraOperation` | Typed Niagara platform operation (operation, station, host, ord, component/slot/point/schedule/alarm/history identity, point type/value/facet/category/baja type/nav path evidence, niagara_user/niagara_role evidence). |
| `NiagaraRouteMapping` | A single Niagara route mapping entry. |
| `VALID_NIAGARA_ACTIONS` | Normalized action verbs accepted for Niagara routes (shared set plus `execute` and `browse`, both pre-existing). |
| `VALID_NIAGARA_OPERATIONS` | Allowed Niagara operation names (`READ_COMPONENT`, `READ_POINT`, `READ_SLOT`, `READ_HISTORY`, `READ_ALARM`, `READ_SCHEDULE`, `WRITE_POINT`, `WRITE_SLOT`, `UPDATE_SCHEDULE`, `ACK_ALARM`, `INVOKE_ACTION`, `COMMAND_POINT`, `OVERRIDE_POINT`, `RELEASE_OVERRIDE`, `BROWSE`, `RESOLVE_ORD`, `LIST_CHILDREN`, `SUBSCRIBE_POINT`, `SUBSCRIBE_ALARM`, `SUBSCRIBE_HISTORY`). |
| `VALID_NIAGARA_TEMPLATE_FIELDS` | Allowed fields in Niagara resource-ID templates. |

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
