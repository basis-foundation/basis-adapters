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

**Phase 2 — REST Adapter Contract Hardening (current)**

The REST adapter contract is now stable and explicitly documented.

What exists:

- Core models: `ProtocolOperation`, `NormalizedAuthorizationRequest`, `AdapterContext`, `AdapterResult`
- Error hierarchy: `AdapterError`, `InvalidMappingError`, `UnknownRouteError`
- REST adapter: HTTP method + path → normalized authorization request
- Mapping config: JSON-loadable route definitions with path pattern capture and action overrides
- JSON Schema for REST mapping config (`schemas/rest-mapping.schema.json`)
- Canonical adapter contract documentation (`docs/contracts/adapter-contract.md`)
- Full test suite (Phase 1 + Phase 2 contract/edge-case tests), ruff, mypy strict

**Fail-closed contract:** if `result.success is False`, the caller must not forward
the operation. A normalization failure is not an authorization decision — treat it
as deny-by-default.

What does not exist yet:

- BACnet adapter
- Running proxy server
- Gateway HTTP client
- Docker / Kubernetes / CI configuration
- Integration tests against a live gateway

---

## Why REST First?

REST is the simplest protocol to normalize: HTTP methods map cleanly to action verbs,
URL paths encode resource identity, and there are no protocol-specific object models
to reason about. Starting with REST lets us validate the normalization model before
introducing protocol complexity.

---

## Why BACnet Later?

BACnet uses object types, instance numbers, property identifiers, and service primitives
(`ReadProperty`, `WriteProperty`, `CommandValue`, `SubscribeCOV`). Normalizing BACnet
correctly requires understanding this model in depth. Phase 2 hardens the normalization
contract on REST so BACnet can be built on a proven foundation rather than alongside one.

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
