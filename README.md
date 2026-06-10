# basis-adapters

Protocol adapters for the BASIS ecosystem.

Adapters normalize protocol-specific operations into BASIS authorization semantics.
They do not evaluate policy. They do not enforce decisions. They translate.

> **Status: early-stage, pre-v1.** Pure normalization library — no live protocol
> communication, no network I/O. Not audited, no production claims. See
> [docs/release-readiness.md](docs/release-readiness.md) for what a `v0.1.0`
> release will require.

---

## Where This Fits in BASIS

BASIS is an open-source architecture for identity-aware authorization in
operational technology (OT) environments.

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
basis-gateway, which resolves the subject's identity and consults basis-core for a
decision.

Adapters never see the decision. They do not allow or deny anything.

---

## Protocol Support

| Protocol | Adapter | Status |
|---|---|---|
| REST | `basis_adapters.rest` | Skeleton + contract hardening |
| BACnet | `basis_adapters.bacnet` | Skeleton |
| Modbus | `basis_adapters.modbus` | Skeleton |
| OPC UA | `basis_adapters.opcua` | Skeleton |

All four adapters emit the same canonical normalized request shape, defined in
[`schemas/normalized-authorization-request.schema.json`](schemas/normalized-authorization-request.schema.json)
and proven by cross-protocol contract tests.

### Phase 7: OPC UA

Phase 7 added OPC UA as the fourth protocol family. The OPC UA adapter
normalizes `Read`, `Write`, `Call`, `Subscribe`, and `Browse` service intent
into the canonical handoff shape, introducing the additive action verbs
`execute` (method invocation) and `browse` (address-space traversal). Like the
other adapters, it is pure normalization: no live OPC UA networking, no
endpoint discovery, no certificates, no secure channels, no sessions. Session
and endpoint context is preserved as audit evidence only. See
[docs/architecture/opcua-adapter.md](docs/architecture/opcua-adapter.md) and
[docs/implementation/phase-7-opcua-adapter.md](docs/implementation/phase-7-opcua-adapter.md).

## What Adapters Do

- Translate protocol operations (HTTP requests, BACnet service primitives, Modbus
  function requests, OPC UA service requests) into protocol-agnostic authorization
  requests via declarative, validated mapping configs.
- Preserve the original operation verbatim as `protocol_evidence` for audit.
- **Fail closed**: if normalization fails (`result.success is False`), the caller
  must not forward the operation. A normalization failure is not an authorization
  decision — treat it as deny-by-default.
- Validate mapping configs fail-fast at load time (`InvalidMappingError`), and
  refuse unmatched operations (`UnknownRouteError`).

## What Adapters Do Not Do

- No authentication, identity resolution, or JWT validation (basis-gateway's job)
- No policy evaluation or decisions (basis-core's job)
- No enforcement, and no reinterpretation of decisions
- No live protocol communication — no sockets, no packet parsing, no protocol stacks
- No proxy server — adapters are libraries, not daemons

---

## Quick Example

```python
import json

from basis_adapters.models import AdapterContext, ProtocolOperation
from basis_adapters.rest import RestAdapter, RestMappingConfig

with open("examples/rest/mapping.example.json") as f:
    config = RestMappingConfig.from_dict(json.load(f))

adapter = RestAdapter(mapping=config, context=AdapterContext(adapter_id="rest-primary"))

op = ProtocolOperation(
    protocol="rest",
    method="GET",
    path="/devices/ahu-1/points/supply-temp",
)

result = adapter.normalize(op)

if result.success:
    req = result.request
    # Submit req to basis-gateway
    # action=read resource_type=point resource_id=ahu-1:supply-temp
else:
    # Fail closed — do not forward the operation
    print(f"Normalization failed: {result.error}")
```

BACnet, Modbus, and OPC UA follow the identical pattern — see the package
docstrings (`basis_adapters.bacnet`, `basis_adapters.modbus`,
`basis_adapters.opcua`) and [docs/examples.md](docs/examples.md).

---

## Setup and Commands

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```bash
python -m pytest          # tests (includes schema/example validation)
ruff check .              # lint
ruff format --check .     # formatting
mypy src                  # strict type checking
```

---

## Documentation

| Topic | Where |
|---|---|
| Architecture | [docs/architecture/](docs/architecture/) |
| Adapter contract (fail-closed, evidence, boundaries) | [docs/contracts/adapter-contract.md](docs/contracts/adapter-contract.md) |
| Cross-protocol normalization contract | [docs/contracts/normalization-contract.md](docs/contracts/normalization-contract.md) |
| Public API surface | [docs/public-api.md](docs/public-api.md) |
| Compatibility expectations | [docs/compatibility.md](docs/compatibility.md) |
| Examples guide | [docs/examples.md](docs/examples.md) |
| Schema/example validation | [docs/schema-validation.md](docs/schema-validation.md) |
| Development workflow | [docs/development-workflow.md](docs/development-workflow.md) |
| Release readiness (v0.1.0 gate) | [docs/release-readiness.md](docs/release-readiness.md) |
| Implementation history (Phases 1–7) | [docs/implementation/](docs/implementation/) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security policy | [SECURITY.md](SECURITY.md) |

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), especially the
architectural guardrails. New protocol adapters must conform to the canonical
handoff shape. Security issues: see [SECURITY.md](SECURITY.md) (please report
privately).

## License

MIT
