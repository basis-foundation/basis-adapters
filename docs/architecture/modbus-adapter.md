# Modbus Adapter Architecture

## Why Modbus Matters to BASIS

Modbus is the oldest and most widely deployed industrial protocol. It is present
in HVAC controllers, power meters, PLCs, variable-frequency drives, building
automation panels, and industrial sensors across virtually every sector that
BASIS targets. Any authorization framework for industrial environments must be
able to normalize Modbus access control intent.

REST and BACnet use object-oriented or resource-oriented semantics: they carry
named resources, typed properties, and semantic service primitives. Modbus does
not. Modbus is purely register-oriented: it addresses raw memory locations
(coils, discrete inputs, input registers, holding registers) by numeric
address within a numeric unit. There are no object names. There is no
property vocabulary. There is only: "read these N registers at address X on
unit Y."

This makes Modbus the sharpest test of the normalization contract. If the
contract works for Modbus — a protocol with almost no semantic content — it
works for register-oriented industrial protocols in general.

## How Modbus Differs from REST and BACnet

| Dimension | REST | BACnet | Modbus |
|---|---|---|---|
| Addressing | URL path | Object type + instance | Unit ID + register address |
| Operations | HTTP verbs | Service primitives | Function codes |
| Data model | Resource-oriented | Object-property model | Raw register memory |
| Semantic richness | High | Medium | Minimal |
| Identity in request | Optional (headers) | Optional (metadata) | None (network-layer only) |
| Authorization hook | Natural (per-resource) | Natural (per-object) | Requires mapping config |

Modbus function codes carry write/read semantics but no resource names. The
adapter's job is to supply the missing semantics via its mapping configuration.

## How Modbus Functions Normalize into Authorization Semantics

Modbus function codes divide cleanly into reads and writes:

| Function | Default Action | Register Type |
|---|---|---|
| ReadCoils | read | coil |
| ReadDiscreteInputs | read | discrete_input |
| ReadHoldingRegisters | read | holding_register |
| ReadInputRegisters | read | input_register |
| WriteSingleCoil | write | coil |
| WriteSingleRegister | write | holding_register |
| WriteMultipleCoils | write | coil |
| WriteMultipleRegisters | write | holding_register |

The mapping config may override the default action per route. The register type
is inferred from the function code unless the operation carries an explicit
`register_type` override.

The resource ID is assembled from operation fields via a template:

```
resource_id_template = "unit:{unit_id}:{register_type}:{address}"

→ resource_id = "unit:1:holding_register:40001"
```

Template fields available: `{function}`, `{unit_id}`, `{address}`,
`{quantity}`, `{register_type}`.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the `protocol_evidence`
field) that preserves all Modbus fields:

```
function          - function code name
unit_id           - Modbus unit identifier
address           - starting register address
quantity          - number of registers/coils requested
value_present     - True if write data was included
register_type     - explicit register type override (or None)
source_address    - source IP/address if available (or None)
transaction_id    - Modbus TCP transaction ID (or None)
```

The `path` field of the `ProtocolOperation` encodes unit and address as
`unit:{unit_id}:addr:{address}`, giving audit systems a compact, human-readable
representation of what was addressed.

## What the Modbus Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata is
  an unverified hint. The gateway is responsible for identity resolution.
- **Never validate JWTs or credentials.**
- **Never call identity providers.**
- **Never evaluate policy.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a proxy server or Modbus gateway.**
- **Never parse raw Modbus TCP bytes or packets** (this adapter models intent, not
  wire format).

## Why This Phase Excludes Live Modbus TCP Communication

This adapter models the *normalized intent* of a Modbus request. It does not
implement a Modbus TCP stack, device driver, or protocol parser. There are
several reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer that
   embeds or calls the adapter.

2. **Testability.** A pure normalization model can be fully tested without
   network access, real devices, or pymodbus. This keeps the test suite fast,
   deterministic, and side-effect-free.

3. **Scope.** BASIS adapters are tested against the normalization contract, not
   against Modbus device behavior. Protocol libraries already exist for live
   communication; they are not this adapter's responsibility.

When a production Modbus integration is built, it will embed `ModbusAdapter`
inside an enforcement boundary, feed it `ModbusOperation` values derived from
real Modbus requests, and pass the resulting `NormalizedAuthorizationRequest`
to `basis-gateway` for decision.

## Modbus Adapter Topology

```
Real Modbus request (from client device)
    ↓
Enforcement boundary (embeds or calls ModbusAdapter)
    │
    ├─ ModbusOperation constructed from wire fields
    │
    ├─ ModbusAdapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- Unit address range validation (1–247 for standard Modbus)
- Exception code modeling (Modbus exception responses)
- Broadcast address handling (unit 0)
- Modbus RTU vs TCP distinction in evidence metadata
- Per-register-range authorization granularity
