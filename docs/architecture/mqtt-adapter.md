# MQTT Adapter Architecture

## Why MQTT Matters to BASIS

MQTT is the dominant publish/subscribe protocol in IoT and increasingly in
building and industrial telemetry. Sensors publish readings to topics;
dashboards, historians, and controllers subscribe to them; and — critically
for authorization — controllers also accept *commands* via published messages
(setpoints, mode changes, overrides). A publish to
`building/ahu-1/setpoint` is a write to operational equipment, whatever the
transport looks like.

MQTT is also architecturally different from everything BASIS has normalized
so far: it is the first **broker-mediated, topic-addressed** protocol in the
repository. REST, BACnet, Modbus, and OPC UA all address a resource directly;
MQTT addresses a *topic namespace* through an intermediary. The adapter's job
is to prove that publish/subscribe intent collapses into the same canonical
authorization request as the request/response protocols — without the adapter
becoming a broker, a topic router, or a wildcard matcher.

## How MQTT Differs from the Other Protocols

| Dimension | REST | BACnet | Modbus | OPC UA | MQTT |
|---|---|---|---|---|---|
| Addressing | URL path | Object type + instance | Unit ID + register address | Node ID | Topic string |
| Operations | HTTP verbs | Service primitives | Function codes | Services | PUBLISH / SUBSCRIBE |
| Interaction model | Request/response | Request/response | Request/response | Request/response (+ subscriptions) | Broker-mediated pub/sub |
| Data model | Resource-oriented | Object-property model | Raw register memory | Typed address space | Opaque payloads on topics |
| Wildcards | No | No | No | Browse paths | `+`, `#` topic filters |
| Identity in request | Optional (headers) | Optional (metadata) | None | Session/endpoint | client_id (connection-level) |

Two consequences for normalization:

1. **MQTT maps onto the existing action vocabulary.** PUBLISH is a write of
   data to a topic; SUBSCRIBE is a request for ongoing delivery. They
   normalize to the existing canonical actions `write` and `subscribe` —
   no new action verbs were needed (unlike Phase 7, where OPC UA added
   `execute` and `browse`).
2. **MQTT carries connection context that must remain evidence.** `client_id`
   identifies a connection, not a subject. It is preserved under
   `protocol_evidence` for audit but never treated as verified identity —
   exactly like OPC UA's `session_id`.

## How MQTT Operations Normalize into Authorization Semantics

| Operation | Default Action | Typical Resource Type |
|---|---|---|
| PUBLISH | write | mqtt_topic |
| SUBSCRIBE | subscribe | mqtt_topic |

The mapping config may override the default action per route (e.g. a publish
to a command topic could be mapped to `control`). Routes match on operation
and topic, first match wins, with `"*"` as a wildcard sentinel.

The resource ID is assembled from operation fields via a template:

```
operation = PUBLISH
topic     = building/ahu-1/setpoint

resource_id_template = "mqtt:{topic}"
→ resource_id = "mqtt:building/ahu-1/setpoint"
```

```
operation = SUBSCRIBE
topic     = building/ahu-1/telemetry

resource_id_template = "mqtt:{topic}"
→ resource_id = "mqtt:building/ahu-1/telemetry"
```

Template fields available: `{operation}`, `{topic}`, `{client_id}`,
`{qos}`, `{payload_type}`. `{client_id}` is only substitutable when present
on the operation; a template referencing an absent field fails closed.

## Topic Handling and Wildcards

MQTT topic filters support the wildcards `+` (single level) and `#`
(multi-level). The adapter's position is deliberate and narrow:

- **Wildcard topic strings are preserved verbatim.** A subscription to
  `building/+/telemetry` normalizes to
  `resource_id = "mqtt:building/+/telemetry"` — one normalized request, with
  the `+` intact in both the resource ID and the protocol evidence.
- **Wildcards are never expanded.** The adapter does not know the topic
  namespace and does not enumerate the concrete topics a filter covers.
- **No broker-side matching is attempted.** Route matching in the mapping
  config is literal string equality (or the `"*"` route sentinel) — a route
  for `building/ahu-1/telemetry` does not match a `building/+/telemetry`
  filter, and vice versa.
- **Wildcard support is not authorization logic.** Whether a subject may hold
  a wildcard subscription — and what it grants access to — is a policy
  question for the policy evaluation layer above the gateway. The adapter
  only describes faithfully what was requested.

## Protocol Evidence Preserved

Every normalized request carries a `ProtocolOperation` (the
`protocol_evidence` field) that preserves all MQTT fields:

```
operation         - "PUBLISH" or "SUBSCRIBE"
topic             - topic or topic filter, verbatim
client_id         - MQTT client identifier (or None)
qos               - QoS level: 0, 1, or 2
retain            - retain flag (PUBLISH)
payload_type      - declared payload type: json | text | binary | unknown
protocol_version  - MQTT protocol version string, e.g. "3.1.1", "5.0" (or None)
```

The `method` field of the `ProtocolOperation` is the MQTT operation name and
the `path` field is the topic, giving audit systems a compact representation
of what was addressed.

`client_id` deserves emphasis: it is **evidence, not identity**. A client
identifier proves only what the protocol layer reported; the gateway is
responsible for resolving and verifying the actual subject. The adapter never
copies `client_id` into `subject_hint`.

Payloads are never inspected. `payload_type` is a caller-declared label
carried as evidence; the adapter sees no payload bytes.

## What the MQTT Adapter Must Never Do

Following the adapter contract in `docs/contracts/adapter-contract.md`:

- **Never authenticate callers.** The `subject_hint` forwarded from metadata
  is an unverified hint. The gateway is responsible for identity resolution.
- **Never treat `client_id` as verified identity.**
- **Never validate credentials, certificates, or TLS/mTLS material.**
- **Never call identity providers.**
- **Never evaluate policy.**
- **Never expand or match wildcard topic filters.**
- **Never enforce decisions.**
- **Never import `basis-core`.**
- **Never import `basis-gateway` or make gateway HTTP calls.**
- **Never become a broker, proxy, or MQTT client** (this adapter models
  intent, not wire format).

## Why This Phase Excludes Live MQTT Communication

The MQTT adapter is **normalization-complete, not a live MQTT broker, proxy,
or MQTT client implementation.** It models the normalized intent of a PUBLISH
or SUBSCRIBE; it does not implement an MQTT client, broker connectivity,
packet parsing, TLS/mTLS, retained-message behavior, QoS delivery semantics,
or subscription state. The reasons:

1. **Separation of concerns.** The adapter is a normalization library. Live
   communication belongs in an enforcement boundary or integration layer that
   embeds or calls the adapter.

2. **Delivery semantics are not authorization semantics.** QoS levels,
   retained messages, and session persistence govern *how* messages move;
   they do not decide whether a subject may write a setpoint topic. They are
   preserved as evidence, nothing more.

3. **Testability.** A pure normalization model can be fully tested without
   network access, real brokers, or paho-mqtt. This keeps the test suite
   fast, deterministic, and side-effect-free.

4. **Scope.** BASIS adapters are tested against the normalization contract,
   not against broker behavior. Mature MQTT clients and brokers already
   exist; they are not this adapter's responsibility.

When a production MQTT integration is built, it will embed `MqttAdapter`
inside an enforcement boundary, feed it `MqttOperation` values derived from
real MQTT packets, and pass the resulting `NormalizedAuthorizationRequest`
to `basis-gateway` for decision.

## MQTT Adapter Topology

```
Real MQTT packet (from client, via broker-facing boundary)
    ↓
Enforcement boundary (embeds or calls MqttAdapter)
    │
    ├─ MqttOperation constructed from packet-level fields
    │
    ├─ MqttAdapter.normalize(operation) → AdapterResult
    │
    ├─ On success: submit NormalizedAuthorizationRequest to basis-gateway
    │              basis-gateway authenticates subject, calls basis-core
    │              basis-core evaluates, returns decision
    │              enforcement boundary enforces
    │
    └─ On failure: deny-by-default, do not forward
```

## Future Work

- UNSUBSCRIBE modeling (subscription lifecycle beyond the single
  SUBSCRIBE intent)
- Shared subscriptions (`$share/<group>/<topic>`) in evidence
- MQTT 5 properties (user properties, content type) as structured evidence
- Per-QoS or retained-publish route matching, if policy needs emerge
- Topic-namespace validation helpers (e.g. rejecting `$SYS` publishes at the
  mapping level)
