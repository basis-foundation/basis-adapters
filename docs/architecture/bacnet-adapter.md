# BACnet Adapter Architecture

This document describes the architecture of the BACnet adapter: how BACnet protocol
primitives are mapped to BASIS authorization semantics, what the adapter accepts as
input, and what it produces as output.

---

## Where This Fits

```
BACnet device/controller
    │
    │  BACnet/IP or BACnet MS/TP (transport — NOT this library)
    ▼
BacnetOperation                    ← adapter input (your code constructs this)
    │
    │  basis_adapters.bacnet.BacnetAdapter.normalize()
    ▼
NormalizedAuthorizationRequest     ← adapter output
    │
    │  submitted to basis-gateway (not this library)
    ▼
basis-gateway → basis-core → authorization decision
```

The BACnet adapter is a **pure normalization library**. It has no BACnet/IP stack,
no bacpypes dependency, and no network connections. You bring the raw BACnet operation;
the adapter produces a normalized authorization request.

---

## BACnet Object Model

BACnet addresses resources through an object model:

| Concept             | BACnet term           | Example                  |
|---------------------|-----------------------|--------------------------|
| Service primitive   | service               | `ReadProperty`           |
| Object category     | object_type           | `analogInput`            |
| Object number       | object_instance       | `1`                      |
| Property            | property_identifier   | `presentValue`           |
| Device              | device_id             | `device-42`              |
| Write priority      | priority              | `8` (1 = highest)        |
| Value payload       | value_present         | `True`                   |

A BACnet operation is uniquely identified by its (service, object_type, object_instance,
property_identifier) tuple, optionally scoped to a device.

---

## Supported Service Primitives

| BACnet Service  | Normalized Action | Description                               |
|-----------------|-------------------|-------------------------------------------|
| ReadProperty    | `read`            | Read a property value from an object      |
| WriteProperty   | `write`           | Write a value to an object property       |
| SubscribeCOV    | `subscribe`       | Subscribe to change-of-value notifications|
| CommandValue    | `control`         | Issue a command to an object              |

These four services cover the primary access patterns in BACnet systems. Other services
(e.g., ConfirmedCOVNotification, AtomicReadFile) are not currently mapped and will
produce a normalization failure.

---

## Input: BacnetOperation

```python
@dataclass(frozen=True)
class BacnetOperation:
    service: str  # "ReadProperty", "WriteProperty", etc.
    object_type: str  # "analogInput", "binaryOutput", etc.
    object_instance: int  # 0–4194302
    property_identifier: str  # "presentValue", "description", etc.
    device_id: str | None  # optional — "device-42", None
    priority: int | None  # optional — write priority 1–16
    value_present: bool  # True if operation carries a value
    metadata: dict[str, Any]  # additional protocol-specific fields
```

`BacnetOperation` is a frozen dataclass — it cannot be modified after construction.
The adapter never modifies the operation it receives.

### to_protocol_operation()

`BacnetOperation.to_protocol_operation()` converts the operation to the generic
`ProtocolOperation` used as protocol evidence:

```
ProtocolOperation(
    protocol = "bacnet",
    method   = operation.service,         # e.g. "ReadProperty"
    path     = "{object_type}:{object_instance}:{property_identifier}",
    metadata = {all fields}
)
```

The path format is `{object_type}:{object_instance}:{property_identifier}`, which
encodes the BACnet object address in a compact, readable form. All BACnet fields
(including device_id, priority, value_present) are preserved in metadata for audit
purposes.

---

## Mapping Configuration: BacnetMappingConfig

Routes are matched against three fields:

| Field               | Match Type                    |
|---------------------|-------------------------------|
| service             | exact or `"*"` wildcard       |
| object_type         | exact or `"*"` wildcard       |
| property_identifier | exact or `"*"` wildcard       |

Routes are evaluated in order; the **first match wins**.

### Resource ID Templates

Resource IDs are rendered from a template using operation field values:

| Template Field          | Value                                   |
|-------------------------|-----------------------------------------|
| `{service}`             | BACnet service name                     |
| `{object_type}`         | BACnet object type                      |
| `{object_instance}`     | Object instance number (as string)      |
| `{property_identifier}` | Property identifier                     |
| `{device_id}`           | Device identifier (fails if None)       |

Example template: `{object_type}:{object_instance}:{property_identifier}`
→ produces `analogInput:1:presentValue`

If a template references `{device_id}` but `operation.device_id` is `None`, the
adapter returns a normalization failure. Device-scoped routes require device-scoped
operations.

---

## Output: NormalizedAuthorizationRequest

On success, the adapter produces:

```python
NormalizedAuthorizationRequest(
    action           = "read"             # from route or default service action map
    resource_type    = "point"            # from route config
    resource_id      = "analogInput:1:presentValue"  # from template
    protocol         = "bacnet"
    protocol_evidence = ProtocolOperation(...)  # always present
    subject_hint     = None               # from operation.metadata["subject_hint"]
)
```

On failure, `AdapterResult.fail(error_message)` is returned. See the fail-closed
contract below.

---

## Fail-Closed Contract

If `result.success is False`, the caller **must not forward the operation**. A
normalization failure is not an authorization decision — treat it as deny-by-default.

```python
result = adapter.normalize(op)
if not result.success:
    # Deny the operation. Do not forward to gateway.
    # Log result.error for diagnostics.
    return deny()
```

`normalize()` never raises. All errors are captured into `AdapterResult.fail(...)`.

---

## What the BACnet Adapter Never Does

- No BACnet/IP stack or network communication
- No bacpypes dependency
- No authentication or identity resolution
- No policy evaluation
- No authorization enforcement
- No calls to basis-core or basis-gateway during normalization
- No partial normalization on invalid input — failure is always explicit

---

## Configuration Validation

Mapping configuration is validated **eagerly** at construction time:

- Unknown BACnet services (not in `VALID_BACNET_SERVICES`) are rejected
- Unknown action verbs (not in `VALID_ACTIONS`) are rejected
- Malformed resource_id templates (unknown fields, unmatched braces) are rejected
- Duplicate route names are rejected
- Empty required fields (object_type, property_identifier, resource_type, template) are rejected

A misconfigured adapter raises `InvalidMappingError` on startup, not on the first
real operation.
