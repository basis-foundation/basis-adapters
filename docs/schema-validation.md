# Schema and Example Validation

Every example in `examples/` is validated against its JSON Schema in `schemas/` by
automated tests, so examples and schemas cannot silently drift apart.

## What Is Validated

`tests/test_schema_examples.py` checks, using the `jsonschema` dev dependency
(Draft 2020-12 validator):

| Example | Schema |
|---|---|
| `examples/rest/mapping.example.json` | `schemas/rest-mapping.schema.json` |
| `examples/rest/mapping-minimal.example.json` | `schemas/rest-mapping.schema.json` |
| `examples/rest/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/bacnet/mapping.example.json` | `schemas/bacnet-mapping.schema.json` |
| `examples/bacnet/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/modbus/mapping.example.json` | `schemas/modbus-mapping.schema.json` |
| `examples/modbus/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/opcua/mapping.example.json` | `schemas/opcua-mapping.schema.json` |
| `examples/opcua/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/mqtt/mapping.example.json` | `schemas/mqtt-mapping.schema.json` |
| `examples/mqtt/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/dnp3/mapping.example.json` | `schemas/dnp3-mapping.schema.json` |
| `examples/dnp3/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/iec61850/mapping.example.json` | `schemas/iec61850-mapping.schema.json` |
| `examples/iec61850/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/knx/mapping.example.json` | `schemas/knx-mapping.schema.json` |
| `examples/knx/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/niagara/mapping.example.json` | `schemas/niagara-mapping.schema.json` |
| `examples/niagara/mapping-invalid.example.json` | must **fail** validation (negative case) |
| `examples/handoff/rest-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/bacnet-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/modbus-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/opcua-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/mqtt-publish-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/mqtt-subscribe-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/dnp3-read-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/dnp3-direct-operate-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/iec61850-read-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/iec61850-direct-operate-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/iec61850-enable-reporting-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/knx-group-value-read-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/knx-group-value-write-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/knx-observe-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/niagara-point-read-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/niagara-override-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/niagara-resolve-ord-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |
| `examples/handoff/niagara-ack-alarm-normalized-request.example.json` | `schemas/normalized-authorization-request.schema.json` |

In addition, the tests verify that **live adapter output matches the schema**: each
adapter (REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, Niagara) is loaded with its example mapping,
normalizes a representative operation, and the resulting `to_dict()` output is
validated against the normalized request schema. This keeps the schemas honest against the
implementation, not just against static example files.

The schemas themselves are also checked against the Draft 2020-12 meta-schema.

## Annotation Keys (`_comment`, `_error`)

Example files embed documentation in keys beginning with `_` (e.g. `_comment` at
the top level, `_error` on invalid routes). These are **annotations, not contract
fields**: the adapters' `from_dict()` constructors ignore them, and the schemas are
intentionally strict (`additionalProperties: false`) to catch typos. The validation
tests therefore strip `_`-prefixed keys recursively before validating. Do the same
for any manual validation.

## Running

The validation tests run as part of the normal suite:

```bash
python -m pytest tests/test_schema_examples.py
```

## Manual Validation

If you need to check a file by hand (e.g. a new example before writing tests):

```python
import json
from jsonschema import Draft202012Validator


def strip_annotations(v):
    if isinstance(v, dict):
        return {k: strip_annotations(x) for k, x in v.items() if not k.startswith("_")}
    if isinstance(v, list):
        return [strip_annotations(x) for x in v]
    return v


schema = json.load(open("schemas/rest-mapping.schema.json"))
instance = strip_annotations(json.load(open("examples/rest/mapping.example.json")))
Draft202012Validator(schema).validate(instance)  # raises on failure
```

## Adding a New Example or Schema

1. Add the example under `examples/<protocol>/` (or `examples/handoff/`).
2. Add or update the schema under `schemas/`.
3. Register the pair in `tests/test_schema_examples.py`.
4. Run the suite.
