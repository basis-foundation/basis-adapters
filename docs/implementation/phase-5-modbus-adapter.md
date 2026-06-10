# Phase 5 — Modbus Adapter Skeleton

## Status

Complete.

## Objective

Add the Modbus adapter as the third protocol in `basis-adapters`. The primary
goal is to validate that the cross-protocol normalization contract established
in Phase 4 holds for a register-oriented industrial protocol with minimal
semantic content.

## Scope

This phase implements:

- `ModbusOperation` — typed operation model representing a Modbus function request
- `ModbusRouteMapping` — frozen dataclass mapping function + register type to
  normalized authorization semantics
- `ModbusMappingConfig` — validated route collection with first-match-wins semantics
- `ModbusAdapter` — normalization adapter following the same pattern as REST and BACnet
- JSON Schema for Modbus mapping configuration
- Example mapping configuration
- Example handoff payload (serialized `NormalizedAuthorizationRequest`)
- Three test files covering mapping, adapter behavior, and contract preservation

## Supported Modbus Functions

All eight standard read/write function codes are modeled:

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

## Operation Model

`ModbusOperation` fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `function` | str | yes | Modbus function code name |
| `unit_id` | int | yes | Modbus unit identifier (device address) |
| `address` | int | yes | Starting register or coil address |
| `quantity` | int | no (default 1) | Number of registers/coils |
| `value_present` | bool | no (default False) | True if write data present |
| `register_type` | str \| None | no | Explicit register type override |
| `source_address` | str \| None | no | Source network address |
| `transaction_id` | int \| None | no | Modbus TCP transaction ID |
| `metadata` | dict | no | Additional fields |

## Mapping Model

Routes match on `function` and `register_type`. Wildcards (`"*"`) match any
value. Routes are evaluated in order; the first match wins.

Resource ID template fields: `{function}`, `{unit_id}`, `{address}`,
`{quantity}`, `{register_type}`.

Example mapping:

```json
{
  "routes": [
    {
      "name": "read-holding-registers",
      "function": "ReadHoldingRegisters",
      "register_type": "holding_register",
      "action": "read",
      "resource_type": "modbus_register",
      "resource_id_template": "unit:{unit_id}:{register_type}:{address}"
    },
    {
      "name": "write-single-register",
      "function": "WriteSingleRegister",
      "register_type": "holding_register",
      "action": "write",
      "resource_type": "modbus_register",
      "resource_id_template": "unit:{unit_id}:{register_type}:{address}"
    }
  ]
}
```

## Example Normalization

Input:
```
function = ReadHoldingRegisters
unit_id = 1
address = 40001
quantity = 1
```

Output:
```
protocol      = modbus
action        = read
resource_type = modbus_register
resource_id   = unit:1:holding_register:40001
```

Input:
```
function = WriteSingleRegister
unit_id = 1
address = 40010
value_present = true
```

Output:
```
protocol      = modbus
action        = write
resource_type = modbus_register
resource_id   = unit:1:holding_register:40010
```

## Non-Goals

This phase deliberately does not implement:

- Live Modbus TCP communication
- Modbus packet parsing or byte-level protocol handling
- Modbus RTU framing
- pymodbus or any Modbus library dependency
- Device discovery
- Unit address range validation (future work)
- Exception code modeling (future work)
- Broadcast address handling (unit 0)
- Gateway HTTP client
- basis-core integration
- Authentication, policy evaluation, or enforcement
- Docker, Kubernetes, or CI configuration

## Tests Added

| File | Tests | What Is Covered |
|---|---|---|
| `tests/test_modbus_mapping.py` | ~40 | Validation, matching, action resolution, template substitution, from_dict |
| `tests/test_modbus_adapter.py` | ~35 | All 8 functions, evidence, subject_hint, failures, result shape |
| `tests/test_modbus_contract.py` | ~18 | Canonical shape, isolation, determinism, forbidden fields |

## Recommended Phase 6

Phase 6 should harden the Modbus mapping contract (analogous to Phase 2 for
REST and Phase 3 for BACnet). Suggested scope:

- Unit ID range validation (1–247)
- Address and quantity range validation (0–65535)
- Register-range conflict detection in mapping config
- Per-range authorization granularity in templates (e.g. `{address_range}`)
- Modbus exception code modeling for evidence enrichment
- `docs/contracts/modbus-contract.md` — Modbus-specific contract document
- Additional contract tests for Modbus-specific failure modes
- Update `docs/contracts/normalization-contract.md` with Modbus-specific nuances
