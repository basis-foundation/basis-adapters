# DNP3 Adapter Architecture

## Why DNP3 Matters to BASIS

DNP3 (Distributed Network Protocol 3) is the dominant SCADA protocol in North
American electric and water utilities — substations, feeder devices, pump
stations, and the masters that poll and command them. It extends BASIS
adapter coverage into utility and critical infrastructure environments, where
the authorization question is at its sharpest: a control relay output block
sent to a breaker is not a data write, it is a command to physical equipment.

DNP3 is not just another register protocol. It has an explicit master/
outstation roles model, an object-typed data model (object groups and
variations addressing typed points), event classes with unsolicited
reporting, and — most importantly for authorization — a two-step
**select-before-operate** control pattern alongside single-step
**direct operate**. The adapter's job is to normalize those intents into the
same canonical authorization request as every other protocol while preserving
DNP3's vocabulary as evidence, without becoming a DNP3 stack.

## How DNP3 Differs from the Other Protocols

| Dimension | Modbus | OPC UA | MQTT | DNP3 |
|---|---|---|---|---|
| Addressing | Unit ID + register address | Node ID | Topic string | Outstation + object group/variation + point index |
| Operations | Function codes | Services | PUBLISH / SUBSCRIBE | Function codes (READ, SELECT, OPERATE, DIRECT_OPERATE, …) |
| Roles | Client/server | Client/server | Broker-mediated | Master/outstation |
| Control pattern | Write registers | Method call | Publish to command topic | Select-before-operate or direct operate |
| Eventing | None | Subscriptions | Pub/sub | Event classes 1-3, unsolicited responses |
| Identity in request | None | Session/endpoint | client_id | Source address / master ID (link-level) |

Two consequences for normalization:

1. **DNP3 maps onto the existing action vocabulary.** READ is a read.
   SELECT, OPERATE, DIRECT_OPERATE, and generic CONTROL are commands to
   equipment and normalize to `execute` (the verb added additively in Phase 7
   for OPC UA method invocation) — preferred over `write` because a CROB or
   analog output command represents control semantics, not a simple data
   write. ENABLE_UNSOLICITED — authorization to receive event reporting —
   normalizes to `subscribe`. **No new action verbs were needed.**
2. **DNP3 carries rich protocol context that must remain evidence.** Source/
   destination addresses, master ID, object group, variation, function code,
   qualifier, control code, control model, event class, and command values
   are preserved under `protocol_evidence` and never promoted to top-level
   normalized request fields.

## How DNP3 Operations Normalize into Authorization Semantics

| Operation | Default Action | Typical Resource Type |
|---|---|---|
| READ | read | dnp3_point / dnp3_object_group |
| SELECT | execute | dnp3_point |
| OPERATE | execute | dnp3_point |
| DIRECT_OPERATE | execute | dnp3_point |
| CONTROL | execute | dnp3_point |
| ENABLE_UNSOLICITED | subscribe | dnp3_event_class |

The mapping config may override the default action per route using existing
canonical actions (e.g. a site could map CONTROL to `write` where the command
genuinely is a value write). Routes match on `(operation, point_type)`, first
match wins, with `"*"` as a wildcard sentinel.

Resource IDs are assembled from operation fields via a template and stay
deterministic — same operation, same resource ID. Command values are **not**
available as template fields; values belong in evidence, never in resource
identity.

```
Point-specific read:
  dnp3:outstation:{outstation_id}/analog_input/{point_index}
  → dnp3:outstation:os-14/analog_input/3

Object group/variation read:
  dnp3:outstation:{outstation_id}/group/{object_group}/variation/{variation}
  → dnp3:outstation:os-14/group/30/variation/5

Binary output control:
  dnp3:outstation:{outstation_id}/binary_output/{point_index}
  → dnp3:outstation:os-14/binary_output/7

Analog output command:
  dnp3:outstation:{outstation_id}/analog_output/{point_index}
  → dnp3:outstation:os-14/analog_output/2
```

Template fields available: `{operation}`, `{outstation_id}`, `{master_id}`,
`{source_address}`, `{destination_address}`, `{object_group}`, `{variation}`,
`{point_index}`, `{point_type}`, `{event_class}`. Optional fields are only
substitutable when present on the operation; a template referencing an absent
field fails closed.

## Target Identity

Every DNP3 operation must identify its target outstation — either logically
(`outstation_id`) or by link-layer `destination_address`. An operation with
neither fails closed. Control operations (SELECT, OPERATE, DIRECT_OPERATE,
CONTROL) must additionally carry a `point_index`: control commands are
point-specific, and a control route's `resource_id_template` must reference
`{point_index}` so a command is never normalized without identifying the
controlled point.

## Select-Before-Operate Handling

DNP3 control may use a two-step select-before-operate (SBO) pattern: the
master first SELECTs a point, then OPERATEs it within a timeout. The
adapter's position is deliberate and narrow:

- **SELECT and OPERATE are each normalized as independent
  authorization-relevant operations.** Both default to `execute`. A policy
  layer can therefore see — and decide on — both steps of the pattern.
- **The adapter maintains no state between SELECT and OPERATE.** No
  correlation of select/operate pairs, no timeout handling, no sequence
  numbers, no replay protection, no command queueing.
- **The control model is preserved in evidence** (`control_model`:
  `"select_before_operate"` or `"direct_operate"`), so downstream layers know
  which pattern was in use. Inconsistent declarations fail closed (a
  DIRECT_OPERATE claiming `select_before_operate`, or a SELECT/OPERATE
  claiming `direct_operate`, is rejected).

Why: the adapter is a stateless normalization component. Stateful control
sequencing — verifying that an OPERATE follows a matching SELECT in time —
belongs to a runtime enforcement boundary, protocol gateway, or a future
DNP3-aware runtime layer. Normalization describes what was requested; it does
not arbitrate protocol state machines.

## Direct Operate Handling

DIRECT_OPERATE (single-step control without prior SELECT) normalizes to
`execute` with `control_model = "direct_operate"` preserved in evidence. The
adapter does not transmit commands, await device confirmations, or model
DIRECT_OPERATE_NO_ACK delivery semantics — those are wire-protocol concerns.

## Event and Unsolicited Response Handling

DNP3 supports event classes (1-3) and unsolicited responses from outstations.
The adapter normalizes exactly one event-related intent:

- **ENABLE_UNSOLICITED → `subscribe`.** Enabling unsolicited reporting is an
  authorization to receive ongoing updates — the same semantics as MQTT
  SUBSCRIBE or OPC UA Subscribe. The event class is preserved in evidence and
  available to resource ID templates.
- **Class-based reads** (e.g. polling group 60 for class 1/2/3 events) are
  ordinary READ operations; `event_class` and the object group are preserved
  as evidence.

Known limitations, by design: the adapter does **not** model unsolicited
response delivery, event buffering, confirmations, DISABLE_UNSOLICITED
lifecycle, or master/outstation session behavior. Those require a runtime
model the adapter deliberately does not have. If richer event authorization
semantics are needed, they belong in a DNP3-aware runtime layer, and this
limitation is documented rather than papered over.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the
`protocol_evidence` field) that preserves all DNP3 fields:

```
operation            - DNP3 operation name, e.g. "DIRECT_OPERATE"
source_address       - link-layer source address (or None)
destination_address  - link-layer destination address (or None)
outstation_id        - logical outstation identifier (or None)
master_id            - logical master identifier (or None)
object_group         - DNP3 object group number (or None)
variation            - object variation number (or None)
point_index          - point index (or None)
point_type           - point type, e.g. "binary_output" (or None)
function_code        - application-layer function code (or None)
qualifier            - qualifier code (or None)
control_code         - control code, e.g. CROB code (or None)
control_model        - "select_before_operate" | "direct_operate" (or None)
event_class          - event class 0-3 (or None)
value                - command/write value, verbatim (or None)
```

The `method` field of the `ProtocolOperation` is the DNP3 operation name and
the `path` field is a deterministic outstation-rooted address (e.g.
`outstation:os-14/binary_output/7`), giving audit systems a compact
representation of what was addressed.

`master_id`, `source_address`, and link-layer addressing deserve emphasis:
they are **evidence, not identity**. A DNP3 address proves only what the
protocol layer reported; the gateway is responsible for resolving and
verifying the actual subject. The adapter never copies them into
`subject_hint`.

Command values (`value`, `control_code`) are preserved verbatim as evidence
and never rendered into resource IDs.

## What the DNP3 Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata
  is an unverified hint. The gateway is responsible for identity resolution.
- **Never treat addresses or `master_id` as verified identity.**
- **Never evaluate policy.**
- **Never maintain select/operate state, sequencing, or replay protection.**
- **Never transmit, queue, or confirm control commands.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a DNP3 master, outstation, proxy, or protocol stack** (this
  adapter models intent, not wire format).

## Why This Phase Excludes Live DNP3 Communication

The DNP3 adapter is **normalization-complete, not a live DNP3 master,
outstation, proxy, or protocol stack.** It models the normalized intent of a
DNP3 application-layer request; it does not implement link/transport/
application layer framing, CRC handling, sequence numbers, confirmations,
session keepalives, secure authentication (DNP3-SA), or any TCP/serial
transport. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer that
   embeds or calls the adapter.

2. **Protocol state is not authorization semantics.** SBO timeouts, sequence
   numbers, and confirmations govern *how* commands move; they do not decide
   whether a subject may operate a breaker. The control model is preserved as
   evidence, nothing more.

3. **Testability.** A pure normalization model can be fully tested without
   network access, real outstations, or a DNP3 library. This keeps the test
   suite fast, deterministic, and side-effect-free.

4. **Scope.** BASIS adapters are tested against the normalization contract,
   not against outstation behavior. Mature DNP3 stacks already exist; they
   are not this adapter's responsibility.

When a production DNP3 integration is built, it will embed `Dnp3Adapter`
inside an enforcement boundary, feed it `Dnp3Operation` values derived from
real DNP3 frames, and pass the resulting `NormalizedAuthorizationRequest`
to `basis-gateway` for decision.

## DNP3 Adapter Topology

```
Real DNP3 frame (from master, via outstation-facing boundary)
    ↓
Enforcement boundary (embeds or calls Dnp3Adapter)
    │
    ├─ Dnp3Operation constructed from frame-level fields
    │
    ├─ Dnp3Adapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- DISABLE_UNSOLICITED and unsolicited-response lifecycle modeling, if clear
  authorization semantics emerge
- Freeze operations (IMMEDIATE_FREEZE, FREEZE_CLEAR) as additional control
  intents
- DNP3 Secure Authentication (SA) context as structured evidence
- File transfer (group 70) operations
- Select/operate correlation support in a DNP3-aware runtime layer (outside
  this adapter)
