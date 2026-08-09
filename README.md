# basis-adapters

Protocol adapters for the BASIS ecosystem.

Adapters normalize protocol-specific operations into BASIS authorization semantics.
They do not evaluate policy. They do not enforce decisions. They translate.

> **Status: v0.1.0 released.** The initial planned adapter set (nine
> adapters) is complete and normalization-complete. Pure normalization library —
> no live protocol communication, no network I/O. Not audited, no production
> claims. See [docs/release-readiness.md](docs/release-readiness.md) for the
> release gate this release satisfied.

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

| Protocol | Adapter | Domain | Status |
|---|---|---|---|
| REST | `basis_adapters.rest` | Web/API operations | Normalization-complete |
| BACnet | `basis_adapters.bacnet` | Building automation object/property operations | Normalization-complete |
| Modbus | `basis_adapters.modbus` | Register/function operations | Normalization-complete |
| OPC UA | `basis_adapters.opcua` | Industrial nodes, methods, browsing, subscriptions | Normalization-complete |
| MQTT | `basis_adapters.mqtt` | Topic publish/subscribe operations | Normalization-complete |
| DNP3 | `basis_adapters.dnp3` | Utility SCADA reads, controls, unsolicited enablement | Normalization-complete |
| IEC 61850 | `basis_adapters.iec61850` | Substation/power systems logical nodes, controls, reporting | Normalization-complete |
| KNX | `basis_adapters.knx` | Building automation group-address operations | Normalization-complete |
| Niagara | `basis_adapters.niagara` | BAS platform operations (stations, ORDs, points, alarms) | Normalization-complete |

**Normalization-complete** means the adapter's normalization model and
architecture are implemented, contract-tested, and stable: it accepts typed
protocol operations and emits the canonical normalized request shape. It does
**not** mean a full wire-protocol implementation — there is no BACnet/IP stack,
no Modbus TCP parser, no OPC UA secure channel, no MQTT broker or client, no
DNP3 master or outstation, no IEC 61850 MMS stack or GOOSE/Sampled Values
processor, no KNX/IP tunnel or bus monitor, no Niagara Fox/Foxs client or
station integration, no live networking of any kind. Adapters model protocol
intent, not wire format.

All nine adapters emit the same canonical normalized request shape, defined in
[`schemas/normalized-authorization-request.schema.json`](schemas/normalized-authorization-request.schema.json)
and proven by cross-protocol contract tests.

### The Normalization Contract

basis-adapters demonstrates that diverse OT protocol and platform operations
can normalize into a shared authorization request model while preserving
protocol evidence for auditability.

Protocols do not converge. Outputs converge.

REST stays resource-oriented, BACnet stays object-oriented, Modbus stays
register-oriented, OPC UA keeps its typed address space, MQTT stays
topic-addressed pub/sub, DNP3 keeps its master/outstation object model,
IEC 61850 keeps its hierarchical IED/logical-node semantic model, KNX stays
group-address oriented, Niagara keeps its station/ORD/component platform
model — adapters do not paper over those differences on the input side. What converges is the output: every
adapter emits the same Normalized Authorization Request, and that normalized
request is the architectural invariant the rest of BASIS builds on. See
[docs/contracts/normalization-contract.md](docs/contracts/normalization-contract.md).

## Roadmap

Completed adapters (normalization-complete):

- REST
- BACnet
- Modbus
- OPC UA
- MQTT
- DNP3
- IEC 61850
- KNX
- Niagara

**The initial planned adapter set is complete.** Every adapter on the original
roadmap is normalization-complete. No further protocols are planned. Future
work, if any, falls into three categories: optional protocol expansion (one at
a time, conforming to the canonical normalized request shape — see
[CONTRIBUTING.md](CONTRIBUTING.md)), runtime integrations (a separate decision,
outside this library's scope), and release hardening.

**Operation-aware handoff alignment is planned, not implemented.** A future,
not-yet-implemented, authenticated operation-producer runtime may consume this
library's output to construct a `basis-schemas` `adapter-evidence-reference`
and submit to `basis-gateway`'s operation-aware path. No such runtime exists
yet, `basis-adapters` still does not authenticate callers, establish producer
trust, call `basis-gateway`, call `basis-core`, or produce execution
evidence, and `v0.1.0` remains the current released behavior. See
[docs/operation-aware-handoff-alignment-plan.md](docs/operation-aware-handoff-alignment-plan.md)
for the discovery-and-assessment plan.

## What Adapters Do

- Translate protocol operations (HTTP requests, BACnet service primitives, Modbus
  function requests, OPC UA service requests, MQTT publish/subscribe intents, DNP3
  read/control intents, IEC 61850 read/write/control/reporting intents, KNX group
  value read/write/response and observe intents, Niagara platform read/write/
  invoke/browse/subscribe intents) into protocol-agnostic
  authorization requests via declarative, validated mapping configs.
- Preserve the original operation verbatim as `protocol_evidence` for audit.
- **Fail closed**: if normalization fails (`result.success is False`), the caller
  must not forward the operation. A normalization failure is not an authorization
  decision — treat it as deny-by-default.
- Validate mapping configs fail-fast at load time (`InvalidMappingError`), and
  refuse unmatched operations (`UnknownRouteError`).

## What Adapters Do Not Do

Adapters are normalization libraries. They are not:

- **Protocol gateways or proxy servers** — no sockets, no packet parsing, no
  protocol stacks, no live protocol communication. Adapters are libraries, not
  daemons.
- **Policy engines** — no policy evaluation or decisions (basis-core's job)
- **Identity providers** — no authentication, identity resolution, or JWT
  validation (basis-gateway's job)
- **Runtime enforcement systems** — no enforcement, and no reinterpretation of
  decisions
- **Device controllers** — adapters never command, actuate, or communicate with
  devices

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

BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, KNX, and Niagara follow the
identical pattern — see the package docstrings (`basis_adapters.bacnet`,
`basis_adapters.modbus`, `basis_adapters.opcua`, `basis_adapters.mqtt`,
`basis_adapters.dnp3`, `basis_adapters.iec61850`, `basis_adapters.knx`,
`basis_adapters.niagara`) and [docs/examples.md](docs/examples.md).

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

The same four gates run automatically in GitHub Actions
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) on every pull request
and on pushes to `main`. CI type-checks `src` only — the configured gate.

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
| Release readiness (historical v0.1.0 release-readiness record) | [docs/release-readiness.md](docs/release-readiness.md) |
| Operation-aware handoff alignment plan (planning only) | [docs/operation-aware-handoff-alignment-plan.md](docs/operation-aware-handoff-alignment-plan.md) |
| Implementation history (Phases 1–14) | [docs/implementation/](docs/implementation/) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Security policy | [SECURITY.md](SECURITY.md) |

---

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md), especially the
architectural guardrails. New protocol adapters must conform to the canonical
handoff shape. Security issues: see [SECURITY.md](SECURITY.md) (please report
privately).

## License

Apache License 2.0
