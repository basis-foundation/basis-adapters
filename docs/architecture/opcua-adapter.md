# OPC UA Adapter Architecture

## Why OPC UA Matters to BASIS

OPC UA (OPC Unified Architecture, IEC 62541) is the dominant modern
interoperability standard for industrial automation. Where BACnet and Modbus
represent legacy protocol families, OPC UA is what new industrial equipment,
SCADA systems, MES platforms, and IIoT gateways speak today. PLCs, building
management heads, energy systems, and process control servers increasingly
expose their data and behavior through OPC UA address spaces.

OPC UA is also architecturally different from everything BASIS has normalized
so far. It has a structured, typed, hierarchical address space: nodes with
identities, namespaces, browse names, attributes, methods, and subscriptions.
And unlike BACnet and Modbus, OPC UA ships with built-in security concepts —
endpoints, secure channels, sessions, and certificates.

That built-in security is exactly why OPC UA matters as a normalization test.
OPC UA security authenticates *connections*; it does not express *policy* about
which subject may invoke which method on which node. BASIS supplies that layer.
The adapter's job is to prove that OPC UA service intent collapses into the
same canonical authorization request as REST, BACnet, and Modbus — without the
adapter absorbing any of OPC UA's transport-security machinery.

## How OPC UA Differs from REST, BACnet, and Modbus

| Dimension | REST | BACnet | Modbus | OPC UA |
|---|---|---|---|---|
| Addressing | URL path | Object type + instance | Unit ID + register address | Node ID (namespace + identifier) |
| Operations | HTTP verbs | Service primitives | Function codes | Services (Read, Write, Call, Subscribe, Browse) |
| Data model | Resource-oriented | Object-property model | Raw register memory | Typed, hierarchical address space |
| Semantic richness | High | Medium | Minimal | High (structured + typed) |
| Methods/RPC | Modeled via routes | No | No | First-class (Call service) |
| Subscriptions | No | COV (not yet modeled) | No | First-class (monitored items) |
| Identity in request | Optional (headers) | Optional (metadata) | None | Session/endpoint (connection-level) |
| Built-in security | TLS (external) | Minimal | None | Endpoints, secure channels, certificates |

Two consequences for normalization:

1. **OPC UA introduces operations that have no legacy equivalent.** Method
   invocation (`Call`) and address-space traversal (`Browse`) are first-class
   services. They normalize to the action verbs `execute` and `browse`, which
   were added (additively) to the canonical action vocabulary in Phase 7.
2. **OPC UA carries connection-security context that must remain evidence.**
   `endpoint_url` and `session_id` are preserved under `protocol_evidence` for
   audit, but the adapter never interprets them as verified identity.

## Why Structured Address-Space Protocols Test the Normalization Contract

Modbus tested the contract from below: a protocol with almost no semantics.
OPC UA tests it from above: a protocol with *more* structure than the
canonical shape — namespaces, typed identifiers, attributes, methods,
subscriptions. The question Phase 7 answers is whether that richness flattens
into `protocol / action / resource_type / resource_id` without protocol detail
leaking into the canonical fields.

It does, because the canonical shape was designed to absorb structure into two
places: the `resource_id` template (which can encode node, attribute, and
method identity) and `protocol_evidence.metadata` (which preserves everything
else verbatim). If the contract holds for both the semantically poorest
protocol (Modbus) and the semantically richest (OPC UA), it holds for the
protocols in between.

## How OPC UA Services Normalize into Authorization Semantics

| Service | Default Action | Typical Resource Type |
|---|---|---|
| Read | read | opcua_node |
| Write | write | opcua_node |
| Call | execute | opcua_method |
| Subscribe | subscribe | opcua_node |
| Browse | browse | opcua_node |

The mapping config may override the default action per route. Routes match on
service and attribute, first match wins, with `"*"` as a wildcard.

The resource ID is assembled from operation fields via a template:

```
service = Read
node_id = ns=2;s=Building.AHU1.SupplyTemp
attribute_id = Value

resource_id_template = "{node_id}:{attribute_id}"
→ resource_id = "ns=2;s=Building.AHU1.SupplyTemp:Value"
```

Method invocation identifies both the owning node and the method:

```
service = Call
node_id = ns=2;s=Building.AHU1
method_id = ns=2;s=Building.AHU1.Reset

resource_id_template = "{node_id}:method:{method_id}"
→ resource_id = "ns=2;s=Building.AHU1:method:ns=2;s=Building.AHU1.Reset"
```

Call routes are required to reference `{method_id}` in their template, so a
method invocation can never be normalized without identifying which method is
being invoked.

Template fields available: `{service}`, `{node_id}`, `{attribute_id}`,
`{method_id}`, `{namespace_index}`, `{browse_name}`, `{parent_node_id}`.
Optional fields are only available when present on the operation; a template
referencing an absent field fails closed.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the `protocol_evidence`
field) that preserves all OPC UA fields:

```
service            - OPC UA service name
node_id            - target node identifier
attribute_id       - attribute identifier (or None)
method_id          - method node identifier (or None)
namespace_index    - namespace index (or None)
identifier         - bare identifier portion of the node ID (or None)
identifier_type    - numeric | string | guid | opaque (or None)
browse_name        - browse name (or None)
parent_node_id     - parent node identifier (or None)
subscription_id    - subscription identifier (or None)
monitored_item_id  - monitored item identifier (or None)
value_present      - True if write data was included
endpoint_url       - endpoint the request was addressed to (or None)
session_id         - OPC UA session identifier (or None)
```

The `method` field of the `ProtocolOperation` is the OPC UA service name and
the `path` field is the target node identifier, giving audit systems a compact
representation of what was addressed.

`session_id` and `endpoint_url` deserve emphasis: they are **evidence, not
identity**. A session identifier proves only that the protocol layer reported
a session; the gateway is responsible for resolving and verifying the actual
subject.

## What the OPC UA Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata is
  an unverified hint. The gateway is responsible for identity resolution.
- **Never treat `session_id` or `endpoint_url` as verified identity.**
- **Never validate JWTs, certificates, or credentials.**
- **Never call identity providers.**
- **Never evaluate policy.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a proxy server or OPC UA gateway.**
- **Never open a secure channel, create a session, or speak OPC UA TCP** (this
  adapter models intent, not wire format).

## Why This Phase Excludes Live OPC UA Networking and Security Channels

This adapter models the *normalized intent* of an OPC UA service request. It
does not implement an OPC UA stack, endpoint discovery, certificate handling,
secure channel setup, session management, or subscription runtime. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer that
   embeds or calls the adapter.

2. **Security machinery is not authorization semantics.** OPC UA secure
   channels and certificates secure the transport; they do not decide whether
   a subject may write a setpoint. Implementing them here would blur the
   boundary the architecture exists to keep sharp: adapters normalize, the
   gateway authenticates and enforces, the kernel evaluates.

3. **Testability.** A pure normalization model can be fully tested without
   network access, real servers, or asyncua. This keeps the test suite fast,
   deterministic, and side-effect-free.

4. **Scope.** BASIS adapters are tested against the normalization contract,
   not against OPC UA server behavior. Mature OPC UA stacks already exist;
   they are not this adapter's responsibility.

When a production OPC UA integration is built, it will embed `OpcuaAdapter`
inside an enforcement boundary, feed it `OpcuaOperation` values derived from
real OPC UA service requests, and pass the resulting
`NormalizedAuthorizationRequest` to `basis-gateway` for decision.

## OPC UA Adapter Topology

```
Real OPC UA service request (from client)
    ↓
Enforcement boundary (embeds or calls OpcuaAdapter)
    │
    ├─ OpcuaOperation constructed from service-level fields
    │
    ├─ OpcuaAdapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- Per-attribute granularity beyond `Value` (e.g. authorization on
  `Description`, `Historizing`)
- Browse path / relative path modeling for `Browse` and
  `TranslateBrowsePathsToNodeIds`
- HistoryRead / HistoryUpdate services
- Subscription lifecycle modeling (CreateMonitoredItems, ModifySubscription,
  DeleteSubscription) beyond the single `Subscribe` intent
- Structured NodeId parsing/validation (`ns=<idx>;<type>=<id>` grammar)
- Namespace URI (vs. index) resolution in evidence
