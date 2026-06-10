# IEC 61850 Adapter Architecture

## Why IEC 61850 Matters to BASIS

IEC 61850 is the international standard for substation automation and power
utility communication — the protocol family that wires together protection
relays, breakers, merging units, and station controllers in modern electric
substations. It extends BASIS adapter coverage deeper into electric utility,
substation automation, and power systems environments, where the
authorization question is at its sharpest: an OPERATE sent to a switch
controller's `Pos` data object is not a data write, it is a command that may
open a breaker.

IEC 61850 is not simply a register protocol. It has a hierarchical, semantic
object model (IED → logical device → logical node → data object → data
attribute, qualified by functional constraints), dataset-driven reporting
through report control blocks, high-speed peer-to-peer messaging (GOOSE),
streamed measurement (Sampled Values), and — most importantly for
authorization — an explicit control model distinguishing
**select-before-operate** from **direct operate**, with normal and enhanced
security variants. The adapter's job is to normalize those intents into the
same canonical authorization request as every other protocol while preserving
IEC 61850's vocabulary as evidence, without becoming an MMS stack.

## How IEC 61850 Differs from the Other Protocols

| Dimension | Modbus | OPC UA | DNP3 | IEC 61850 |
|---|---|---|---|---|
| Addressing | Unit ID + register address | Node ID | Outstation + group/variation + point index | IED / logical device / logical node / data object / data attribute |
| Operations | Function codes | Services | Function codes | Services (read, write, select, operate, cancel, reporting, GOOSE, SV) |
| Data semantics | Untyped registers | Typed address space | Object-typed points | Standardized semantic model (logical node classes, functional constraints) |
| Control pattern | Write registers | Method call | SBO or direct operate | SBO or direct operate, normal/enhanced security (ctlModel) |
| Eventing | None | Subscriptions | Event classes, unsolicited | Report control blocks + datasets, GOOSE, Sampled Values |
| Identity in request | None | Session/endpoint | Source address / master ID | Origin (orCat/orIdent), association context |

Two consequences for normalization:

1. **IEC 61850 maps onto the existing action vocabulary.** READ is a read,
   WRITE is a write. SELECT, SELECT_WITH_VALUE, OPERATE, DIRECT_OPERATE, and
   CANCEL are commands to equipment and normalize to `execute` (the verb
   added additively in Phase 7 for OPC UA method invocation) — preferred over
   `write` because operating a breaker represents control semantics, not a
   simple data write. ENABLE_REPORTING, ENABLE_GOOSE, and
   ENABLE_SAMPLED_VALUES — authorization to receive ongoing data — normalize
   to `subscribe`. **No new action verbs were needed.**
2. **IEC 61850 carries rich protocol context that must remain evidence.**
   IED/logical device/logical node/data object/data attribute identity,
   functional constraint, dataset, control block names, control model,
   origin, cause of transmission, quality, timestamps, and values are
   preserved under `protocol_evidence` and never promoted to top-level
   normalized request fields.

## How IEC 61850 Operations Normalize into Authorization Semantics

| Operation | Default Action | Typical Resource Type |
|---|---|---|
| READ | read | iec61850_data_attribute / iec61850_data_object |
| WRITE | write | iec61850_data_attribute |
| SELECT | execute | iec61850_data_object |
| SELECT_WITH_VALUE | execute | iec61850_data_object |
| OPERATE | execute | iec61850_data_object |
| DIRECT_OPERATE | execute | iec61850_data_object |
| CANCEL | execute | iec61850_data_object |
| ENABLE_REPORTING | subscribe | iec61850_report_control_block |
| ENABLE_GOOSE | subscribe | iec61850_goose_control_block |
| ENABLE_SAMPLED_VALUES | subscribe | iec61850_sampled_values_control_block |

The mapping config may override the default action per route using existing
canonical actions. Routes match on `(operation, logical_node)`, first match
wins, with `"*"` as a wildcard sentinel.

Resource IDs are assembled from operation fields via a template and stay
deterministic — same operation, same resource ID. Values, quality,
timestamps, origin, and cause are **not** available as template fields; they
belong in evidence, never in resource identity.

```
Data attribute read:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}/da:{data_attribute}
  → iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag

Data object read:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}
  → iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW

Logical node operation:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}
  → iec61850:ied:ied-sub1/ld:PROT/ln:PTOC1

Switch control (select/operate/direct operate):
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}
  → iec61850:ied:ied-sub1/ld:CTRL/ln:CSWI1/do:Pos

Report control block:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/rcb:{report_control_block}
  → iec61850:ied:ied-sub1/ld:MEAS/ln:LLN0/rcb:urcbMX01

GOOSE control block:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/gcb:{goose_control_block}
  → iec61850:ied:ied-sub1/ld:PROT/ln:LLN0/gcb:gcbTrip

Sampled Values control block:
  iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/svcb:{sampled_values_control_block}
  → iec61850:ied:ied-mu1/ld:MU01/ln:LLN0/svcb:MSVCB01
```

Template fields available: `{operation}`, `{ied_name}`, `{logical_device}`,
`{logical_node}`, `{data_object}`, `{data_attribute}`,
`{functional_constraint}`, `{dataset}`, `{report_control_block}`,
`{goose_control_block}`, `{sampled_values_control_block}`. Optional fields
are only substitutable when present on the operation; a template referencing
an absent field fails closed.

## Target Identity

Every IEC 61850 operation must identify its target IED (`ied_name`); an
operation without target identity fails closed. Addressing is hierarchical
and each level requires its parent: a `logical_node` requires a
`logical_device`, a `data_object` requires a `logical_node`, and a
`data_attribute` requires a `data_object`. READ and WRITE require at least a
logical node. Control operations (SELECT, SELECT_WITH_VALUE, OPERATE,
DIRECT_OPERATE, CANCEL) must additionally carry a `data_object`: control
commands are data-object-specific, and a control route's
`resource_id_template` must reference `{data_object}` so a command is never
normalized without identifying the controlled data object. Subscription
operations must carry their control block name, and their routes must
reference the matching control block template field.

## Select-Before-Operate Handling

IEC 61850 control may use a two-step select-before-operate (SBO) pattern —
SELECT (or SELECT_WITH_VALUE) followed by OPERATE, optionally aborted with
CANCEL — or single-step DIRECT_OPERATE, each with normal- or
enhanced-security variants declared by the point's control model
(`ctlModel`). The adapter's position is deliberate and narrow:

- **SELECT, SELECT_WITH_VALUE, OPERATE, CANCEL, and DIRECT_OPERATE are each
  normalized as independent authorization-relevant operations.** All default
  to `execute`. A policy layer can therefore see — and decide on — every
  step of the pattern.
- **The adapter maintains no state between SELECT and OPERATE.** No
  correlation of select/operate pairs, no timeout handling, no command
  sequencing, no device confirmation semantics.
- **The control model is preserved in evidence** (`control_model`:
  `"status_only"`, `"direct_with_normal_security"`,
  `"sbo_with_normal_security"`, `"direct_with_enhanced_security"`, or
  `"sbo_with_enhanced_security"`), so downstream layers know which pattern
  was in use. Inconsistent declarations fail closed: a DIRECT_OPERATE
  claiming an sbo_* model, a SELECT/SELECT_WITH_VALUE/OPERATE/CANCEL claiming
  a direct_* model, or any control operation against a `status_only` point is
  rejected.

Why: the adapter is a stateless normalization component. Stateful control
sequencing — verifying that an OPERATE follows a matching SELECT in time —
belongs to a runtime enforcement boundary, protocol gateway, or a future
IEC 61850-aware runtime layer. Normalization describes what was requested; it
does not arbitrate protocol state machines.

## Reporting Handling

IEC 61850 reporting binds report control blocks (buffered or unbuffered) to
datasets. The adapter normalizes exactly one reporting intent:

- **ENABLE_REPORTING → `subscribe`.** Enabling a report control block is an
  authorization to receive ongoing updates — the same semantics as MQTT
  SUBSCRIBE or DNP3 ENABLE_UNSOLICITED. The report control block and dataset
  identifiers are preserved as evidence and available to resource ID
  templates.

Known limitations, by design: the adapter does **not** implement report
buffering, integrity period behavior, report confirmation, event sequencing,
buffer overflow handling, or RCB attribute lifecycle (setting trigger
options, general interrogation, etc. are WRITE intents if normalized at all).

## GOOSE and Sampled Values Handling

GOOSE (high-speed peer-to-peer event messaging, used for protection trips
and interlocking) and Sampled Values (streamed current/voltage samples from
merging units) are operationally sensitive, multicast, hard-real-time
protocol behaviors. The adapter's position:

- **ENABLE_GOOSE → `subscribe`** and **ENABLE_SAMPLED_VALUES → `subscribe`.**
  Enabling these streams is an authorization-relevant intent; control block
  identifiers are preserved as evidence.
- The adapter implements **no multicast behavior, no frame parsing, no
  timing semantics, no protection-trip behavior, and no Sampled Values
  stream processing.** A GOOSE trip message operates on microsecond budgets
  and never flows through a normalization library — these behaviors must
  remain outside this adapter, in protection hardware and (eventually) an
  IEC 61850-aware runtime layer.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the
`protocol_evidence` field) that preserves all IEC 61850 fields:

```
operation                     - IEC 61850 operation name, e.g. "DIRECT_OPERATE"
ied_name                      - target IED name
logical_device                - logical device name (or None)
logical_node                  - logical node name (or None)
data_object                   - data object name (or None)
data_attribute                - data attribute name (or None)
functional_constraint         - functional constraint, e.g. "ST", "MX", "CO" (or None)
dataset                       - dataset name (or None)
report_control_block          - report control block name (or None)
goose_control_block           - GOOSE control block name (or None)
sampled_values_control_block  - Sampled Values control block name (or None)
control_model                 - ctlModel, e.g. "sbo_with_enhanced_security" (or None)
origin                        - origin context, e.g. orCat/orIdent (or None)
cause                         - cause of transmission (or None)
quality                       - quality descriptor (or None)
timestamp                     - protocol timestamp (or None)
value                         - write/control value, verbatim (or None)
```

The `method` field of the `ProtocolOperation` is the IEC 61850 operation name
and the `path` field is a deterministic IED-rooted address (e.g.
`ied:ied-sub1/ld:CTRL/ln:CSWI1/do:Pos`), giving audit systems a compact
representation of what was addressed.

`origin` deserves emphasis: it is **evidence, not identity**. An IEC 61850
origin (`orCat`/`orIdent`) proves only what the protocol layer reported; the
gateway is responsible for resolving and verifying the actual subject. The
adapter never copies it into `subject_hint`.

Values, quality, timestamps, origin, and cause are preserved verbatim as
evidence and never rendered into resource IDs.

## What the IEC 61850 Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata
  is an unverified hint. The gateway is responsible for identity resolution.
- **Never treat `origin` or association context as verified identity.**
- **Never evaluate policy.**
- **Never maintain select/operate state, sequencing, or timeout handling.**
- **Never transmit, queue, or confirm control commands.**
- **Never process GOOSE frames, Sampled Values streams, or multicast
  traffic.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become an IEC 61850 client, server, MMS stack, GOOSE subscriber,
  Sampled Values processor, or substation gateway** (this adapter models
  intent, not wire format).

## Why This Phase Excludes Live IEC 61850 Communication

The IEC 61850 adapter is **normalization-complete, not a live IEC 61850
client, server, MMS stack, GOOSE subscriber, Sampled Values processor, or
substation gateway.** It models the normalized intent of an IEC 61850 service
request; it does not implement MMS associations, ACSI service mappings, SCL
file parsing, GOOSE/SV multicast handling, time synchronization, or any
TCP/Ethernet transport. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer that
   embeds or calls the adapter.

2. **Protocol state is not authorization semantics.** SBO timeouts, GOOSE
   retransmission curves, and report buffers govern *how* data and commands
   move; they do not decide whether a subject may operate a breaker. The
   control model is preserved as evidence, nothing more.

3. **Operational sensitivity.** GOOSE and Sampled Values carry protection
   functions with hard real-time budgets. A normalization library has no
   business on that path; the adapter normalizes the *enable/subscribe*
   intent and nothing else.

4. **Testability.** A pure normalization model can be fully tested without
   network access, real IEDs, or an IEC 61850 library. This keeps the test
   suite fast, deterministic, and side-effect-free.

5. **Scope.** BASIS adapters are tested against the normalization contract,
   not against IED behavior. Mature IEC 61850 stacks already exist; they are
   not this adapter's responsibility.

When a production IEC 61850 integration is built, it will embed
`Iec61850Adapter` inside an enforcement boundary, feed it `Iec61850Operation`
values derived from real service requests, and pass the resulting
`NormalizedAuthorizationRequest` to `basis-gateway` for decision.

## IEC 61850 Adapter Topology

```
Real IEC 61850 service request (from client, via IED-facing boundary)
    ↓
Enforcement boundary (embeds or calls Iec61850Adapter)
    │
    ├─ Iec61850Operation constructed from service-level fields
    │
    ├─ Iec61850Adapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- DISABLE_REPORTING / disable-GOOSE / disable-SV lifecycle modeling, if clear
  authorization semantics emerge
- Setting group operations (SelectActiveSG, SelectEditSG) as additional
  intents
- File transfer and log retrieval services
- SCL (Substation Configuration Language) context as structured evidence
- Select/operate correlation support in an IEC 61850-aware runtime layer
  (outside this adapter)
