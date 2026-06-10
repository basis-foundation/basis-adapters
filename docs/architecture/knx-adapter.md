# KNX Adapter Architecture

## Why KNX Matters to BASIS

KNX is the dominant open standard for building automation in Europe and is
widely deployed worldwide — lighting, HVAC, shading, scenes, and metering in
commercial and residential buildings ride on KNX group communication. It
expands BASIS adapter coverage beyond BACnet and Niagara-style systems into
group-address based building automation environments, where the authorization
question is concrete: a group value write to `1/2/3` may switch every light
on a floor, drive a blind, or recall a scene across an entire building.

KNX communication is organized around **group addresses**: shared, broadcast
identifiers that bind communication objects on many devices to one logical
function. A device sends a group value write to a group address; every device
whose communication object is bound to that address reacts. Value
interpretation is defined by **datapoint types** (DPTs, e.g. `1.001` for
switching, `9.001` for temperature). The adapter's job is to normalize those
group-communication intents into the same canonical authorization request as
every other protocol while preserving KNX's vocabulary as evidence, without
becoming a KNX/IP stack.

## How KNX Differs from the Other Protocols

| Dimension | BACnet | MQTT | IEC 61850 | KNX |
|---|---|---|---|---|
| Addressing | Device + object + property | Topic | IED / logical device / logical node / data object | Group address (shared) + individual address (per device) |
| Operations | Services | PUBLISH/SUBSCRIBE | Services | Group value read / write / response |
| Data semantics | Object properties | Opaque payloads | Standardized semantic model | Datapoint types (DPTs) |
| Fan-out | Point-to-point | Broker-mediated | Multicast (GOOSE/SV) | Group address binds many devices at once |
| Identity in request | Device instance | Client ID | Origin (orCat/orIdent) | Individual (physical) address |

Two consequences for normalization:

1. **KNX maps onto the existing action vocabulary.** GROUP_VALUE_READ is a
   read. GROUP_VALUE_WRITE is a write. GROUP_VALUE_RESPONSE — data flowing
   back to a reader — normalizes to `read`. OBSERVE — an explicit intent to
   monitor a group address for updates — normalizes to `subscribe`, the same
   semantics as MQTT SUBSCRIBE or DNP3 ENABLE_UNSOLICITED. **No new action
   verbs were needed.**
2. **KNX carries protocol context that must remain evidence.** Group
   address, individual/device address, communication object, datapoint type,
   payload type, value, priority, and topology (area/line/device) are
   preserved under `protocol_evidence` and never promoted to top-level
   normalized request fields.

## How KNX Operations Normalize into Authorization Semantics

| Operation | Default Action | Typical Resource Type |
|---|---|---|
| GROUP_VALUE_READ | read | knx_group_address |
| GROUP_VALUE_WRITE | write | knx_group_address |
| GROUP_VALUE_RESPONSE | read | knx_group_address |
| OBSERVE | subscribe | knx_group_address |

The mapping config may override the default action per route using existing
canonical actions. Routes match on `(operation, group_address)`, first match
wins, with `"*"` as a wildcard sentinel. Group addresses are matched
verbatim — exact string comparison, no topology expansion, no range matching.

Resource IDs are assembled from operation fields via a template and stay
deterministic — same operation, same resource ID. Values, payloads, payload
types, priority, and datapoint types are **not** available as template
fields; they belong in evidence, never in resource identity.

```
Group address:
  knx:group:{group_address}
  → knx:group:1/2/3

Group address with communication object:
  knx:group:{group_address}/object:{communication_object}
  → knx:group:1/2/3/object:4

Device-specific resource:
  knx:device:{device_address}/object:{communication_object}
  → knx:device:1.1.7/object:4
```

Template fields available: `{operation}`, `{group_address}`,
`{individual_address}`, `{device_address}`, `{communication_object}`,
`{area}`, `{line}`, `{device}`. Optional fields are only substitutable when
present on the operation; a template referencing an absent field fails
closed.

## Group Address Handling

Group addresses are the heart of KNX and the adapter treats them with
deliberate restraint:

- **Preserved exactly.** Three-level (`1/2/3`), two-level (`1/200`), and
  free-style (`2563`) notations are accepted and kept verbatim, validated
  only for format and KNX range limits (three-level 0-31/0-7/0-255,
  two-level 0-31/0-2047, free 0-65535).
- **No topology expansion.** The adapter never enumerates which devices a
  group address reaches.
- **No semantic inference.** No room, floor, equipment, or functional
  meaning is inferred from an address unless mapping metadata explicitly
  provides it.
- **No group-address authorization logic.** Whether a subject may write to
  `1/2/3` is a policy question. Authorization semantics belong above the
  adapter.

## Datapoint Type Handling

KNX datapoint types define value interpretation (e.g. `1.001` switching,
`9.001` temperature). The adapter's position:

- **DPT is preserved as evidence** in `protocol_evidence` metadata.
- **Only a basic shape check is performed** (`major.minor` notation, e.g.
  `1.001`). Full DPT payload semantics are not parsed or validated.
- **Payload values are never coerced into operational meaning.** A value is
  evidence, verbatim.
- **No policy decisions are made based on DPT.** Distinguishing a switching
  write from a setpoint write is a policy concern.

## Bus Monitoring Handling

KNX networks can be monitored for bus events. The adapter normalizes exactly
one monitoring-shaped intent:

- **OBSERVE → `subscribe`.** An explicit, declared intent to monitor a group
  address for datapoint updates is authorization-relevant, with the group
  address and DPT context preserved as evidence.

Known limitations, by design: the adapter implements **no bus sniffing, no
multicast monitoring, no KNX/IP routing or tunneling, and retains no bus
state.** Normalizing the declared intent is the entire behavior.
GROUP_VALUE_RESPONSE is normalized as a read-semantics event-style update —
the adapter does not correlate responses with prior reads and keeps no state
between operations.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the
`protocol_evidence` field) that preserves all KNX fields:

```
operation             - KNX operation name, e.g. "GROUP_VALUE_WRITE"
group_address         - group address, verbatim
individual_address    - individual (physical) address (or None)
device_address        - device address (or None)
communication_object  - communication object number (or None)
datapoint_type        - DPT, e.g. "1.001" (or None)
payload_type          - payload type descriptor (or None)
value                 - payload value, verbatim (or None)
priority              - frame priority: system/urgent/normal/low (or None)
area                  - topology area number (or None)
line                  - topology line number (or None)
device                - topology device number (or None)
```

The `method` field of the `ProtocolOperation` is the KNX operation name and
the `path` field is a deterministic group-rooted address (e.g.
`group:1/2/3/object:4`), giving audit systems a compact representation of
what was addressed.

The `individual_address` deserves emphasis: it is **evidence, not identity**.
A KNX individual address proves only what the protocol layer reported; the
gateway is responsible for resolving and verifying the actual subject. The
adapter never copies it into `subject_hint`.

Values, payloads, payload types, priority, and datapoint types are preserved
verbatim as evidence and never rendered into resource IDs.

## What the KNX Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata
  is an unverified hint. The gateway is responsible for identity resolution.
- **Never treat an individual address as verified identity.**
- **Never evaluate policy.**
- **Never expand group-address topology or infer semantic meaning.**
- **Never transmit, queue, or confirm group telegrams.**
- **Never sniff the bus, monitor multicast, or retain bus state.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a KNX/IP client, router, tunnel, multicast listener, bus
  monitor, or building automation controller** (this adapter models intent,
  not wire format).

## Why This Phase Excludes Live KNX Communication

The KNX adapter is **normalization-complete, not a live KNX/IP client,
router, tunnel, multicast listener, bus monitor, or building automation
controller.** It models the normalized intent of a KNX group operation; it
does not implement KNXnet/IP tunneling or routing, TP1/RF/powerline media,
telegram framing, multicast handling, or any transport. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer
   that embeds or calls the adapter.

2. **Protocol state is not authorization semantics.** Telegram
   acknowledgements, repetition flags, and routing counters govern *how*
   telegrams move; they do not decide whether a subject may write to a group
   address.

3. **Fan-out sensitivity.** A single group write can actuate many devices at
   once. The adapter normalizes the intent so a policy layer can decide on
   it — it never performs or relays the actuation.

4. **Testability.** A pure normalization model can be fully tested without
   network access, real devices, or a KNX library. This keeps the test suite
   fast, deterministic, and side-effect-free.

5. **Scope.** BASIS adapters are tested against the normalization contract,
   not against device behavior. Mature KNX stacks already exist; they are
   not this adapter's responsibility.

When a production KNX integration is built, it will embed `KnxAdapter`
inside an enforcement boundary, feed it `KnxOperation` values derived from
real group telegrams or client requests, and pass the resulting
`NormalizedAuthorizationRequest` to `basis-gateway` for decision.

## KNX Adapter Topology

```
Real KNX group operation (from client or device-facing boundary)
    ↓
Enforcement boundary (embeds or calls KnxAdapter)
    │
    ├─ KnxOperation constructed from application-layer fields
    │
    ├─ KnxAdapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- Property read/write services (device management) as additional intents, if
  clear authorization semantics emerge
- Scene and configuration services as structured intents
- Group-address project metadata (ETS exports) as structured evidence
  provided by mapping configuration — never inferred
- Bus-event correlation support in a KNX-aware runtime layer (outside this
  adapter)
