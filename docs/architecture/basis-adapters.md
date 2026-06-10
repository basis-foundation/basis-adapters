# basis-adapters Architecture

## What is an Adapter?

An adapter is a translation layer between an operational technology (OT) protocol
and the BASIS authorization model. Adapters speak the language of their protocol on the
inbound side, and produce normalized authorization requests on the outbound side.

An adapter answers one question: **given this protocol operation, what authorization
request should be submitted to basis-gateway?**

Adapters do not answer whether the request should be allowed.

---

## What Adapters Own

- Protocol-specific parsing: understanding HTTP methods and paths, BACnet object
  identifiers and property references, Modbus function codes and register addresses,
  OPC UA node identifiers and service requests.
- Normalization: mapping protocol operations to a stable, protocol-agnostic
  authorization request shape (`NormalizedAuthorizationRequest`).
- Mapping configuration: rules that describe which protocol operations correspond to
  which resource types, resource IDs, and action verbs.
- Protocol evidence: preserving the original protocol operation so downstream systems
  can audit what triggered an authorization request.
- Fail-closed behavior: refusing to produce a normalized request when no mapping matches
  or when a mapping is structurally invalid.

---

## What Adapters Do Not Own

**Authorization semantics.** Adapters do not evaluate policies. They do not inspect
subject claims. They do not decide allow or deny. An adapter produces a request; the
gateway evaluates it.

**Identity verification.** Adapters may forward a `subject_hint` extracted from
protocol metadata, but they do not verify, decode, or trust identity claims. The
gateway is responsible for resolving and verifying identity.

**Decision enforcement.** Adapters do not act on authorization outcomes. They normalize
an operation and stop. Enforcement is the gateway's responsibility.

**Direct basis-core access.** Adapters do not call basis-core. The authorization kernel
is invoked by the gateway after the adapter has submitted a normalized request.

---

## How Adapters Interact with basis-gateway

```
Protocol Client
      │
      ▼ (protocol-native request)
  Adapter
      │ normalize()
      ▼
NormalizedAuthorizationRequest
      │
      ▼ (HTTP POST or SDK call)
  basis-gateway
      │ evaluates
      ▼
  basis-core
      │
      ▼
  Decision (ALLOW / DENY)
      │
      ▼
  basis-gateway (enforces)
```

The adapter's output is the gateway's input. The adapter never sees the decision.

---

## Why Adapters Must Not Evaluate Policy

Policy evaluation requires the full authorization context: the subject's identity,
the active policy rules, the resource hierarchy, and the current environment. Adapters
operate at the protocol boundary, where this context is either unavailable or
unverified.

Allowing adapters to evaluate policy would:

1. Distribute trust decisions across protocol-specific code that is hard to audit.
2. Create opportunities for protocol-layer assumptions to silently override policy.
3. Make it impossible to centrally audit or reason about what was allowed and why.

The gateway is the single point of enforcement. Adapters feed it; they do not compete
with it.

---

## Why Adapters Must Not Reinterpret Decisions

Once the gateway makes a decision, the adapter's job is done. An adapter that receives
a DENY and then silently allows the operation anyway — even with good intentions — is a
security bypass. Adapters must not receive, inspect, or act on authorization decisions.

---

## Current Protocol Support

Four adapters are implemented and normalization-complete: REST, BACnet, Modbus,
and OPC UA. All four emit the canonical Normalized Authorization Request shape
and participate in the cross-protocol contract tests. Planned protocols (MQTT,
DNP3, IEC 61850, KNX, Niagara) are tracked in the README roadmap.

### REST

The REST adapter normalizes HTTP method + path into BASIS authorization semantics.
It is configured by a `RestMappingConfig` that maps `(method, path_pattern)` pairs
to `(action, resource_type, resource_id_template)` triples.

Example:

```
GET /devices/ahu-1/points/supply-temp
  → action=read, resource_type=point, resource_id=ahu-1:supply-temp, protocol=rest
```

### BACnet

BACnet uses object identifiers, property references, and service primitives
(`ReadProperty`, `WriteProperty`, `CommandValue`, `SubscribeCOV`). The BACnet
adapter maps these to the same normalized model as REST. See
[bacnet-adapter.md](bacnet-adapter.md).

### Modbus

Modbus is register-oriented: function codes addressing coils and registers by
numeric address within a unit. The mapping configuration supplies the resource
semantics the protocol itself lacks. See [modbus-adapter.md](modbus-adapter.md).

### OPC UA

OPC UA exposes a typed, hierarchical address space with first-class methods and
subscriptions. Its `Read`, `Write`, `Call`, `Subscribe`, and `Browse` services
normalize to the canonical action vocabulary, including the `execute` and
`browse` verbs. See [opcua-adapter.md](opcua-adapter.md).

---

## Design Invariants

These invariants apply to every adapter in the repository, regardless of protocol.

1. **Adapters normalize. They do not evaluate.** No authorization logic belongs in an adapter.
2. **Adapters fail closed.** An operation with no matching mapping must not produce a
   normalized request. Silence is not safe.
3. **Protocol evidence is always attached.** Every `NormalizedAuthorizationRequest`
   carries the original `ProtocolOperation` that produced it.
4. **No gateway calls.** Adapters do not make HTTP calls to basis-gateway. They produce
   normalized request objects.
5. **No basis-core imports.** Adapters do not depend on the authorization kernel.
6. **Mapping validation is eager.** Invalid configurations raise at construction time,
   not at normalization time. A misconfigured adapter fails on startup, not on the
   first real operation.
7. **Models are immutable.** `ProtocolOperation`, `NormalizedAuthorizationRequest`,
   `AdapterContext`, and `AdapterResult` are frozen dataclasses. Normalization produces
   new values; it does not mutate state.
