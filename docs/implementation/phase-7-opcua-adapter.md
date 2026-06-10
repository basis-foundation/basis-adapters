# Phase 7 — OPC UA Adapter Skeleton

## Status

Complete.

## Objective

Add OPC UA as the fourth protocol family in `basis-adapters`. The primary goal
is to prove that a modern, structured, address-space protocol — with
first-class methods and subscriptions and built-in connection security —
normalizes into the same BASIS handoff contract as REST, BACnet, and Modbus,
without the adapter absorbing any OPC UA networking or security machinery.

## Scope

This phase implements:

- `OpcuaOperation` — typed operation model representing an OPC UA service request
- `OpcuaRouteMapping` — frozen dataclass mapping service + attribute to
  normalized authorization semantics
- `OpcuaMappingConfig` — validated route collection with first-match-wins semantics
- `OpcuaAdapter` — normalization adapter following the same pattern as REST,
  BACnet, and Modbus
- JSON Schema for OPC UA mapping configuration
- Example mapping configuration
- Example handoff payload (serialized `NormalizedAuthorizationRequest`)
- Three test files covering mapping, adapter behavior, and contract preservation
- OPC UA participation in the cross-protocol contract tests and schema/example
  validation tests
- Additive extension of the canonical action vocabulary with `execute` and
  `browse`

## Supported OPC UA Services

All five targeted services are modeled:

| Service | Default Action | Typical Resource Type |
|---|---|---|
| Read | read | opcua_node |
| Write | write | opcua_node |
| Call | execute | opcua_method |
| Subscribe | subscribe | opcua_node |
| Browse | browse | opcua_node |

`execute` and `browse` are new normalized action verbs introduced in this
phase. The change is additive: the canonical schema enum gained two values and
no existing protocol behavior changed. REST, BACnet, and Modbus route configs
continue to validate against their original action sets.

## Operation Model

`OpcuaOperation` fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `service` | str | yes | OPC UA service name (Read, Write, Call, Subscribe, Browse) |
| `node_id` | str | yes | Target node identifier, e.g. `ns=2;s=Building.AHU1.SupplyTemp` |
| `attribute_id` | str \| None | no | Attribute identifier, e.g. `Value` |
| `method_id` | str \| None | for Call | Method node identifier |
| `namespace_index` | int \| None | no | Namespace index of the target node |
| `identifier` | str \| None | no | Bare identifier portion of the node ID |
| `identifier_type` | str \| None | no | `numeric`, `string`, `guid`, or `opaque` |
| `browse_name` | str \| None | no | Browse name of the target node |
| `parent_node_id` | str \| None | no | Parent/owning node identifier |
| `subscription_id` | int \| None | no | Subscription identifier |
| `monitored_item_id` | int \| None | no | Monitored item identifier |
| `value_present` | bool | no (default False) | True if write data present |
| `endpoint_url` | str \| None | no | Endpoint URL the request was addressed to |
| `session_id` | str \| None | no | OPC UA session identifier (evidence only) |
| `metadata` | dict | no | Additional fields |

Operations are validated at normalization time (fail closed, never raise):
unsupported or missing service, missing/non-string `node_id`, non-integer
`namespace_index`, invalid `identifier_type`, and `Call` without a `method_id`
all produce failure results.

## Mapping Model

Routes match on `service` and `attribute_id`. Wildcards (`"*"`) match any
value — for `attribute_id`, the wildcard also matches operations that carry no
attribute, while an exact attribute route only matches operations carrying that
attribute. Routes are evaluated in order; **the first match wins**.

Resource ID template fields: `{service}`, `{node_id}`, `{attribute_id}`,
`{method_id}`, `{namespace_index}`, `{browse_name}`, `{parent_node_id}`.
Optional fields are only substitutable when present on the operation; a
template referencing an absent field fails closed at render time.

Config validation is eager (`InvalidMappingError` at parse time): unsupported
services, empty actions/resource types, malformed or unknown-field templates,
duplicate route names, and Call routes whose template does not reference
`{method_id}` are all rejected before any operation is normalized.

Example mapping:

```json
{
  "routes": [
    {
      "name": "read-node-value",
      "service": "Read",
      "attribute_id": "Value",
      "action": "read",
      "resource_type": "opcua_node",
      "resource_id_template": "{node_id}:{attribute_id}"
    },
    {
      "name": "call-method",
      "service": "Call",
      "action": "execute",
      "resource_type": "opcua_method",
      "resource_id_template": "{node_id}:method:{method_id}"
    }
  ]
}
```

## Example Normalizations

Input:
```
service = Read
node_id = ns=2;s=Building.AHU1.SupplyTemp
attribute_id = Value
```

Output:
```
protocol      = opcua
action        = read
resource_type = opcua_node
resource_id   = ns=2;s=Building.AHU1.SupplyTemp:Value
```

Input:
```
service = Call
node_id = ns=2;s=Building.AHU1
method_id = ns=2;s=Building.AHU1.Reset
```

Output:
```
protocol      = opcua
action        = execute
resource_type = opcua_method
resource_id   = ns=2;s=Building.AHU1:method:ns=2;s=Building.AHU1.Reset
```

Input:
```
service = Subscribe
node_id = ns=2;s=Building.AHU1.SupplyTemp
attribute_id = Value
```

Output:
```
protocol      = opcua
action        = subscribe
resource_type = opcua_node
resource_id   = ns=2;s=Building.AHU1.SupplyTemp:Value
```

## Non-Goals

This phase deliberately does not implement:

- Live OPC UA communication (no TCP, no binary or HTTPS transport)
- Endpoint discovery
- Certificate handling
- Secure channel setup
- Session management
- Subscription runtime (monitored item delivery, keep-alives)
- OPC UA packet/message parsing
- asyncua or any OPC UA library dependency
- Gateway HTTP client
- basis-core integration
- Authentication, policy evaluation, or enforcement
- Proxy server behavior
- Docker, Kubernetes, or CI configuration

## Tests Added

| File | What Is Covered |
|---|---|
| `tests/test_opcua_mapping.py` | Route validation, duplicate names, matching (exact/wildcard/attribute), first-match-wins, action resolution, template substitution, from_dict |
| `tests/test_opcua_adapter.py` | All 5 services, evidence (node/namespace/endpoint/session), subject_hint, operation-validation failures, result shape |
| `tests/test_opcua_contract.py` | Canonical shape, isolation (no basis_core/gateway/asyncua), determinism, forbidden fields, session-as-evidence |
| `tests/test_normalization_contract.py` | OPC UA added to four-way cross-protocol parity, determinism, and evidence tests |
| `tests/test_schema_examples.py` | OPC UA mapping/handoff examples and live adapter output validated against schemas |

## Recommended Phase 8

Suggested directions, in rough priority order:

- **OPC UA contract hardening** (analogous to Phase 2 for REST): structured
  NodeId grammar validation, per-attribute vocabularies, browse-path modeling,
  and an `docs/contracts/opcua-contract.md` document.
- Subscription lifecycle services (CreateMonitoredItems, ModifySubscription,
  DeleteSubscription) as distinct normalized intents.
- HistoryRead/HistoryUpdate modeling.
- Alternatively: begin the first integration layer that embeds an adapter
  inside a real enforcement boundary in `basis-gateway`, now that four
  protocol families prove the handoff contract.
