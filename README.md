# basis-adapters

Protocol adapters for the BASIS ecosystem.

Adapters normalize protocol-specific operations into BASIS authorization semantics.
They do not evaluate policy. They do not enforce decisions. They translate.

---

## Where This Fits in BASIS

```
basis-core       evaluates authorization decisions
basis-gateway    authenticates, normalizes identity, and enforces
basis-adapters   normalize protocol-specific operations into BASIS authorization semantics
```

The principle:

> **Adapters normalize. Gateway enforces. Kernel evaluates.**

An adapter accepts a raw protocol operation (e.g. `GET /devices/ahu-1/points/supply-temp`)
and produces a normalized authorization request (e.g. `action=read, resource_type=point,
resource_id=ahu-1:supply-temp, protocol=rest`). The normalized request is submitted to
basis-gateway, which resolves the subject's identity and consults basis-core to get a
decision.

Adapters never see the decision. They do not allow or deny anything.

---

## Current Status

**Phase 5 — Modbus Adapter Skeleton (current)**

Modbus is the third adapter, joining REST and BACnet. All three now participate
in the cross-protocol normalization contract. The contract is proven stable
across a resource-oriented protocol (REST), an object-property protocol
(BACnet), and a register-oriented protocol (Modbus).

What exists:

- Core models: `ProtocolOperation`, `NormalizedAuthorizationRequest`, `AdapterContext`, `AdapterResult`
- Error hierarchy: `AdapterError`, `InvalidMappingError`, `UnknownRouteError`
- REST adapter: HTTP method + path → normalized authorization request
- BACnet adapter: service + object type + property → normalized authorization request
- **Modbus adapter**: function + unit/address → normalized authorization request
- JSON Schema for REST mapping config (`schemas/rest-mapping.schema.json`)
- JSON Schema for BACnet mapping config (`schemas/bacnet-mapping.schema.json`)
- **JSON Schema for Modbus mapping config** (`schemas/modbus-mapping.schema.json`)
- JSON Schema for normalized authorization request (`schemas/normalized-authorization-request.schema.json`)
- Cross-protocol normalization contract (`docs/contracts/normalization-contract.md`)
- `NormalizedAuthorizationRequest.to_dict()` — deterministic, JSON-compatible serialization
- Example handoff payloads (`examples/handoff/`) for REST, BACnet, and Modbus
- Canonical adapter contract documentation (`docs/contracts/adapter-contract.md`)
- BACnet and Modbus architecture documentation (`docs/architecture/`)
- Full test suite (REST + BACnet + Modbus + cross-protocol contract), ruff, mypy strict

**Fail-closed contract:** if `result.success is False`, the caller must not forward
the operation. A normalization failure is not an authorization decision — treat it
as deny-by-default.

**No live Modbus TCP.** The Modbus adapter models normalized intent only. No
pymodbus, no TCP sockets, no packet parsing. Live communication belongs in the
enforcement boundary that embeds this adapter.

What does not exist yet:

- Running proxy server
- Gateway HTTP client
- Modbus contract hardening (Phase 6)
- Docker / Kubernetes / CI configuration
- Integration tests against a live gateway

---

## Why REST First?

REST is the simplest protocol to normalize: HTTP methods map cleanly to action verbs,
URL paths encode resource identity, and there are no protocol-specific object models
to reason about. Starting with REST lets us validate the normalization model before
introducing protocol complexity.

---

## BACnet Adapter

BACnet uses object types, instance numbers, property identifiers, and service primitives
(`ReadProperty`, `WriteProperty`, `SubscribeCOV`, `CommandValue`). The BACnet adapter
maps these to BASIS authorization semantics via a route config with wildcard matching
on service, object type, and property identifier.

```python
from basis_adapters.models import AdapterContext
from basis_adapters.bacnet import BacnetAdapter, BacnetMappingConfig, BacnetOperation

import json

with open("examples/bacnet/mapping.example.json") as f:
    config = BacnetMappingConfig.from_dict(json.load(f))

ctx = AdapterContext(adapter_id="bacnet-primary")
adapter = BacnetAdapter(mapping=config, context=ctx)

op = BacnetOperation(
    service="ReadProperty",
    object_type="analogInput",
    object_instance=1,
    property_identifier="presentValue",
    device_id="device-42",
)

result = adapter.normalize(op)

if result.success:
    req = result.request
    # Submit req to basis-gateway
    print(f"action={req.action} resource_type={req.resource_type} resource_id={req.resource_id}")
    # action=read resource_type=sensor resource_id=analogInput:1
else:
    print(f"Normalization failed: {result.error}")
    # Fail closed — do not forward the operation
```

---

## Modbus Adapter

Modbus uses numeric function codes, unit IDs, and register addresses. The Modbus
adapter maps these to BASIS authorization semantics via a route config matching
on function code and register type.

```python
from basis_adapters.models import AdapterContext
from basis_adapters.modbus import ModbusAdapter, ModbusMappingConfig, ModbusOperation

import json

with open("examples/modbus/mapping.example.json") as f:
    config = ModbusMappingConfig.from_dict(json.load(f))

ctx = AdapterContext(adapter_id="modbus-primary")
adapter = ModbusAdapter(mapping=config, context=ctx)

op = ModbusOperation(
    function="ReadHoldingRegisters",
    unit_id=1,
    address=40001,
    quantity=1,
)

result = adapter.normalize(op)

if result.success:
    req = result.request
    # Submit req to basis-gateway
    print(f"action={req.action} resource_type={req.resource_type} resource_id={req.resource_id}")
    # action=read resource_type=modbus_register resource_id=unit:1:holding_register:40001
else:
    print(f"Normalization failed: {result.error}")
    # Fail closed — do not forward the operation
```

---

## Local Setup

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Commands

**Run tests:**

```bash
python -m pytest
```

**Lint:**

```bash
ruff check .
```

**Check formatting:**

```bash
ruff format --check .
```

**Type check:**

```bash
mypy src
```

---

## Non-Goals

This repository does not and will not contain:

- Authorization policy evaluation (that belongs in basis-core)
- Identity verification or JWT decoding (that belongs in basis-gateway)
- Decision enforcement (that belongs in basis-gateway)
- A standalone proxy server (adapters are libraries, not daemons — for now)
- Any protocol outside the BASIS ecosystem

---

## Example

```python
from basis_adapters.models import AdapterContext, ProtocolOperation
from basis_adapters.rest import RestAdapter, RestMappingConfig

import json

with open("examples/rest/mapping.example.json") as f:
    config = RestMappingConfig.from_dict(json.load(f))

ctx = AdapterContext(adapter_id="rest-primary")
adapter = RestAdapter(mapping=config, context=ctx)

op = ProtocolOperation(
    protocol="rest",
    method="GET",
    path="/devices/ahu-1/points/supply-temp",
)

result = adapter.normalize(op)

if result.success:
    req = result.request
    # Submit req to basis-gateway
    print(f"action={req.action} resource_type={req.resource_type} resource_id={req.resource_id}")
    # action=read resource_type=point resource_id=ahu-1:supply-temp
else:
    print(f"Normalization failed: {result.error}")
    # Fail closed — do not forward the operation
```
