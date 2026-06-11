# Niagara Adapter Architecture

## Why Niagara Matters to BASIS

Niagara (Tridium's Niagara Framework) is one of the most widely deployed
building automation platforms in the world — supervisors and JACE controllers
running Niagara stations integrate BACnet, Modbus, KNX, and proprietary
devices behind a single component model. Niagara is important to BASIS for a
reason the device protocols are not: **it is a platform, not a wire
protocol.** A Niagara station has components, ords, points, histories,
schedules, alarms, users, roles, categories, and supervisory workflows. The
authorization question is operationally concrete: an operator override of a
setpoint, an alarm acknowledgement, or a schedule update is a platform
operation with building-wide consequences.

This adapter treats Niagara as a **platform-operation normalization
adapter**, not a Niagara driver. It proves that platform operations — not
just device-protocol operations — normalize into the same canonical
authorization request as every other adapter, while preserving Niagara's
vocabulary as evidence.

## How Niagara Differs from the Other Protocols

| Dimension | BACnet | OPC UA | KNX | Niagara |
|---|---|---|---|---|
| Nature | Device protocol | Device/server protocol | Bus protocol | Automation **platform** |
| Addressing | Device + object + property | Node ID | Group address | Station + ORD / component / slot / point |
| Operations | Services | Services | Group value ops | Platform operations (read/write/invoke/browse/subscribe across points, histories, alarms, schedules) |
| Identity in request | Device instance | Session/user token | Individual address | Niagara users and roles (platform accounts) |
| Hierarchy | Flat object space | Address space | Group topology | Station component tree navigated by ORDs and nav paths |

Two consequences for normalization:

1. **Niagara maps onto the existing action vocabulary.** Reads of
   components, points, slots, histories, alarms, and schedules are `read`.
   Point/slot writes and schedule updates are `write`. Action invocation,
   point commands, overrides, releases, and alarm acknowledgement are
   `execute`. Browsing, ORD resolution, and child listing are `browse`.
   Point/alarm/history subscriptions are `subscribe`. **No new action verbs
   were needed** — `execute` and `browse` already existed (introduced for
   OPC UA).
2. **Niagara carries platform context that must remain evidence.** Station,
   host, ord, component, slot, point, point type, value, facet, schedule,
   alarm, history, category, baja type, nav path, and — critically —
   Niagara user and role are preserved under `protocol_evidence` and never
   promoted to top-level normalized request fields.

## How Niagara Operations Normalize into Authorization Semantics

| Operation | Default Action | Typical Resource Type |
|---|---|---|
| READ_COMPONENT | read | niagara_component |
| READ_POINT | read | niagara_point |
| READ_SLOT | read | niagara_slot |
| READ_HISTORY | read | niagara_history |
| READ_ALARM | read | niagara_alarm |
| READ_SCHEDULE | read | niagara_schedule |
| WRITE_POINT | write | niagara_point |
| WRITE_SLOT | write | niagara_slot |
| UPDATE_SCHEDULE | write | niagara_schedule |
| ACK_ALARM | execute | niagara_alarm |
| INVOKE_ACTION | execute | niagara_component |
| COMMAND_POINT | execute | niagara_point |
| OVERRIDE_POINT | execute | niagara_point |
| RELEASE_OVERRIDE | execute | niagara_point |
| BROWSE | browse | niagara_station |
| RESOLVE_ORD | browse | niagara_ord |
| LIST_CHILDREN | browse | niagara_component |
| SUBSCRIBE_POINT | subscribe | niagara_point |
| SUBSCRIBE_ALARM | subscribe | niagara_alarm |
| SUBSCRIBE_HISTORY | subscribe | niagara_history |

The mapping config may override the default action per route using existing
canonical actions. Routes match on `(operation, station)`, first match wins,
with `"*"` as a wildcard sentinel. Station names are matched verbatim — no
host resolution, no supervisor topology inference.

Resource IDs are assembled from operation fields via a template and stay
deterministic — same operation, same resource ID. Values, facets, point
types, baja types, nav paths, categories, Niagara users, and Niagara roles
are **not** available as template fields; they belong in evidence, never in
resource identity.

```
ORD-based resource:
  niagara:station:{station}/ord:{ord}
  → niagara:station:station-east/ord:station:|slot:/Drivers/BacnetNetwork/AHU1

Point resource:
  niagara:station:{station}/point:{point}
  → niagara:station:station-east/point:AHU1-SupplyTemp

Component slot resource:
  niagara:station:{station}/component:{component}/slot:{slot}
  → niagara:station:station-east/component:AHU1/slot:status

History resource:
  niagara:station:{station}/history:{history}

Alarm resource:
  niagara:station:{station}/alarm:{alarm}

Schedule resource:
  niagara:station:{station}/schedule:{schedule}
```

Template fields available: `{operation}`, `{station}`, `{ord}`,
`{component}`, `{slot}`, `{point}`, `{schedule}`, `{alarm}`, `{history}`.
Optional fields are only substitutable when present on the operation; a
template referencing an absent field fails closed.

## The Niagara Identity Boundary

This boundary deserves special emphasis for Niagara, because Niagara has its
own users, roles, permissions, categories, and station authentication model
— and it would be tempting to treat them as identity. The adapter does not:

- **`niagara_user` and `niagara_role` are evidence only.** They are
  preserved verbatim in `protocol_evidence.metadata` and never copied into
  `subject_hint`.
- **They are never BASIS identity.** A Niagara user name proves only what
  the platform layer reported; the gateway is responsible for resolving and
  verifying the actual subject.
- **No identity normalization happens inside the adapter.** No role
  mapping, no station-permission interpretation, no category-permission
  interpretation.
- **They may never appear in resource IDs.** Resource identity is what is
  acted on, not who the platform thinks is acting.

Identity belongs to `basis-gateway`. The adapter only normalizes Niagara
operation semantics.

## ORD Handling

Niagara ORDs are the platform's universal object addressing scheme and have
a rich grammar (`station:|slot:/...`, `bql:`, `history:` and more). The
adapter treats them with deliberate restraint:

- **Preserved exactly.** ORD strings are kept verbatim, validated only for
  being non-empty when present.
- **No ORD grammar parsing.** The adapter does not tokenize or interpret
  ORD schemes.
- **No ORD resolution and no link following.** Resolving an ORD is a
  station capability; the adapter only normalizes the *intent* to resolve
  (`RESOLVE_ORD` → `browse`).
- **No component-meaning inference.** Nothing is inferred from ORD
  structure.
- **ORDs may participate in deterministic resource IDs** via the `{ord}`
  template field, verbatim.

## Point Override Handling

Point override and release are among the most operationally significant
Niagara actions — an override pins a point at a priority level regardless of
control logic. The adapter's position:

- **OVERRIDE_POINT → `execute` and RELEASE_OVERRIDE → `execute`.** These
  are operational commands, not data writes.
- **Override metadata is evidence.** Point, value, duration, level, and any
  override context supplied in `metadata` are preserved verbatim.
- **No priority-array behavior.** The adapter does not model Niagara
  priority levels or emergency/operator precedence.
- **No override state and no release semantics.** The adapter retains no
  command state — normalizing the intent is the entire behavior.

## Alarm Handling

Alarm acknowledgement may be modeled as state mutation or command execution.
This adapter models it as command execution:

- **ACK_ALARM → `execute`.** Acknowledgement is an action/event on the
  alarm, not a data write. A route may override to `write` using the
  existing vocabulary if a deployment prefers state-mutation semantics.
- **Alarm identifier and acknowledgement metadata are evidence.**
- **No alarm lifecycle behavior, no alarm routing, no notification
  behavior.**

## History and Schedule Handling

- READ_HISTORY → `read`; SUBSCRIBE_HISTORY → `subscribe`.
- READ_SCHEDULE → `read`; UPDATE_SCHEDULE → `write`.

Known limitations, by design: the adapter implements **no history queries,
no schedule calculations, no recurrence parsing, and no runtime
scheduling.** History and schedule identifiers are opaque verbatim
identifiers used for resource identity and evidence.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the
`protocol_evidence` field) that preserves all Niagara fields:

```
operation     - Niagara operation name, e.g. "OVERRIDE_POINT"
station       - station name
host          - platform host (or None)
ord           - ORD, verbatim (or None)
component     - component name (or None)
slot          - slot/property name (or None)
point         - point name (or None)
point_type    - point type descriptor (or None)
value         - operation value, verbatim (or None)
facet         - facet descriptor (or None)
schedule      - schedule name (or None)
alarm         - alarm identifier (or None)
history       - history identifier (or None)
category      - Niagara category (or None)
baja_type     - Baja type spec (or None)
nav_path      - nav path (or None)
niagara_user  - platform user, evidence only (or None)
niagara_role  - platform role, evidence only (or None)
```

The `method` field of the `ProtocolOperation` is the Niagara operation name
and the `path` field is a deterministic station-rooted address (e.g.
`station:station-east/point:AHU1-SupplyTemp`), giving audit systems a
compact representation of what was addressed.

Values, facets, point types, baja types, nav paths, categories, Niagara
users, and Niagara roles are preserved verbatim as evidence and never
rendered into resource IDs.

## What the Niagara Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from
  metadata is an unverified hint. The gateway is responsible for identity
  resolution.
- **Never treat a Niagara user or role as verified identity.**
- **Never interpret Niagara station permissions or perform role mapping.**
- **Never evaluate policy.**
- **Never parse, resolve, or follow ORDs.**
- **Never implement override, priority-array, or alarm lifecycle state.**
- **Never transmit, queue, or confirm platform operations.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a Fox/Foxs client, Baja runtime participant, Haystack
  client, REST connector, station driver, supervisor integration, or JACE
  integration** (this adapter models intent, not platform connectivity).

## Why This Phase Excludes Live Niagara Communication

The Niagara adapter is **normalization-complete, not a live Niagara station
integration, Fox/Foxs client, Baja runtime, Haystack client, REST connector,
station driver, supervisor integration, JACE integration, or Niagara
permission system.** It models the normalized intent of a Niagara platform
operation; it does not implement Fox/Foxs transport, station authentication,
component-model runtime, or any connectivity. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer
   that embeds or calls the adapter.

2. **Platform state is not authorization semantics.** Station sessions,
   subscriptions, lease timers, and component lifecycles govern *how* a
   station operates; they do not decide whether a subject may override a
   setpoint.

3. **Platform identity is not BASIS identity.** Embedding Niagara's user/
   role/permission model in the adapter would put identity resolution on
   the wrong side of the architecture. The gateway owns identity.

4. **Testability.** A pure normalization model can be fully tested without
   a station, a supervisor, or a Niagara license. This keeps the test suite
   fast, deterministic, and side-effect-free.

5. **Scope.** BASIS adapters are tested against the normalization contract,
   not against platform behavior. Niagara itself already provides the
   platform; that is not this adapter's responsibility.

When a production Niagara integration is built, it will embed
`NiagaraAdapter` inside an enforcement boundary, feed it `NiagaraOperation`
values derived from real station requests, and pass the resulting
`NormalizedAuthorizationRequest` to `basis-gateway` for decision.

## Niagara Adapter Topology

```
Real Niagara platform operation (from client or station-facing boundary)
    ↓
Enforcement boundary (embeds or calls NiagaraAdapter)
    │
    ├─ NiagaraOperation constructed from platform-operation fields
    │
    ├─ NiagaraAdapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- Additional platform operations (component lifecycle, user/role
  administration intents) if clear authorization semantics emerge
- Station metadata (categories, tag dictionaries) as structured evidence
  provided by mapping configuration — never inferred
- Hierarchical station/supervisor context in a Niagara-aware runtime layer
  (outside this adapter)
