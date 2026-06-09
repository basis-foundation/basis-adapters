# Phase 1 — REST Adapter

## Scope

Phase 1 establishes the repository foundation and implements the first adapter:
a REST (HTTP) normalization layer.

The goal is to define the adapter boundary, prove the normalization model with a
concrete protocol, and provide a reference implementation for future adapters.

No running proxy server, no gateway integration, and no additional protocols are
included in Phase 1.

---

## What Was Built

```
src/basis_adapters/
  __init__.py          — public API exports
  models.py            — ProtocolOperation, NormalizedAuthorizationRequest,
                         AdapterContext, AdapterResult
  errors.py            — AdapterError, InvalidMappingError, UnknownRouteError
  rest/
    __init__.py
    adapter.py         — RestAdapter: accepts a ProtocolOperation, returns AdapterResult
    mapping.py         — RestMappingConfig, RouteMapping: configuration + matching logic
```

---

## REST Adapter Assumptions

1. Inputs are HTTP-like: a method string (e.g. `"GET"`) and a path string
   (e.g. `"/devices/ahu-1/points/supply-temp"`).
2. Mapping configuration is provided externally (from a JSON file, environment config,
   or test fixture). The adapter does not hard-code any routes.
3. Path patterns use `{param}` capture syntax. Patterns are anchored: a pattern must
   match the entire path.
4. Method matching is case-insensitive.
5. Routes are evaluated in declaration order. First match wins.
6. The adapter does not perform network I/O. It does not contact basis-gateway.

---

## Example Normalization Flow

**Input operation:**

```
ProtocolOperation(
    protocol = "rest",
    method   = "GET",
    path     = "/devices/ahu-1/points/supply-temp",
)
```

**Mapping rule:**

```json
{
  "methods": ["GET", "HEAD"],
  "path_pattern": "/devices/{device_id}/points/{point_id}",
  "resource_type": "point",
  "resource_id_template": "{device_id}:{point_id}",
  "name": "read-point"
}
```

**Normalization steps:**

1. Match `GET /devices/ahu-1/points/supply-temp` against the route's pattern
   `/devices/{device_id}/points/{point_id}` → captures: `{device_id: "ahu-1", point_id: "supply-temp"}`
2. Resolve action: `GET` is not in the route's `action_map`, so the default map applies → `"read"`
3. Render resource ID: `"{device_id}:{point_id}".format(device_id="ahu-1", point_id="supply-temp")`
   → `"ahu-1:supply-temp"`
4. Attach protocol evidence: the original `ProtocolOperation` is embedded in the result

**Output:**

```python
NormalizedAuthorizationRequest(
    action            = "read",
    resource_type     = "point",
    resource_id       = "ahu-1:supply-temp",
    protocol          = "rest",
    protocol_evidence = <original ProtocolOperation>,
    subject_hint      = None,
)
```

This value is ready to submit to basis-gateway. The adapter's job is done.

---

## Failure Modes

**Unknown route — fail closed:**

```python
op = ProtocolOperation(protocol="rest", method="DELETE", path="/devices/ahu-1/points/x")
result = adapter.normalize(op)
# result.success is False
# result.error   == "No route matched: DELETE /devices/ahu-1/points/x"
# result.request is None
```

The adapter never raises from `normalize()`. Errors are captured into `AdapterResult.fail(...)`.

**Invalid mapping — fail at construction time:**

```python
RouteMapping(
    methods=["POST"],
    path_pattern="/devices",
    resource_type="device",
    resource_id_template="*",
    action_map={"POST": "launch"},  # "launch" is not a valid action
)
# raises: InvalidMappingError: invalid action 'launch' ...
```

Misconfigured adapters fail on startup, not mid-operation.

---

## Non-Goals for Phase 1

- No running HTTP proxy server. The adapter is a library, not a process.
- No JWT validation or OIDC integration.
- No direct HTTP calls to basis-gateway.
- No basis-core imports.
- No BACnet, Modbus, Niagara, or MQTT support.
- No Docker, Kubernetes, or CI/CD configuration.

---

## Phase 2 Direction

Phase 2 should introduce the BACnet adapter. Key decisions for that work:

1. **Object model mapping.** BACnet operations reference objects by type + instance
   (`analog-input:1`). The normalized model should represent these as stable resource IDs.
2. **Service-to-action mapping.** BACnet services (`ReadProperty`, `WriteProperty`,
   `CommandValue`, `SubscribeCOV`) map naturally to `read`, `write`, `control`,
   `subscribe`.
3. **Shared mapping infrastructure.** `RestMappingConfig` and `RouteMapping` are
   REST-specific. Phase 2 should define a BACnet-specific config model, but both
   adapters should produce the same `NormalizedAuthorizationRequest` output type.
4. **Integration test harness.** Phase 1 has no network I/O, so unit tests suffice.
   Phase 2 should introduce an integration test fixture that submits normalized requests
   to a local basis-gateway instance and verifies that the gateway receives and evaluates
   them correctly.
5. **Gateway HTTP client.** Phase 2 is where a gateway client (or SDK wrapper) belongs.
   It does not belong in the adapter itself — the adapter produces the request object,
   and a separate transport layer submits it.
