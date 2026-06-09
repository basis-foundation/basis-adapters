# Phase 2 — REST Adapter Contract Hardening

## Scope

Phase 2 hardens the REST adapter normalization model established in Phase 1.
No new protocols are added. The goal is to make the REST adapter's contract
explicit, validated, and stable before BACnet begins.

---

## What Changed

### Mapping Validation (mapping.py)

The following validation was added to `RouteMapping.__post_init__`:

**HTTP method validation**
Methods are validated against a recognized set (`VALID_HTTP_METHODS`). Non-standard
method strings are rejected at config construction time. The wildcard `"*"` remains
valid for catch-all routes.

**Path pattern validation**
- Must not be empty
- Must start with `/`
- Must not contain malformed brace tokens (e.g. `{` without a closing `}`)
- Must not have duplicate capture names within the same pattern

**resource_id_template validation**
- All `{param}` references in the template must correspond to capture parameters
  defined in the same route's path_pattern
- Malformed brace tokens are rejected
- This catches misconfigured templates at startup rather than producing wrong
  resource IDs at runtime

**Action map validation**
- Empty action strings are now explicitly rejected (not just checked against
  `VALID_ACTIONS`)

**Duplicate route name detection** was added to `RestMappingConfig.__post_init__`:
- Named routes (non-empty `name` field) must be unique within a config
- Anonymous routes (empty name) are not subject to this check

### Query String Handling (mapping.py)

Query strings are stripped from the path before matching. This is now explicit
contract behavior:

```
GET /devices/ahu-1/points/supply-temp?format=json
  → stripped to: /devices/ahu-1/points/supply-temp
  → matched against route patterns
```

The original `ProtocolOperation` (including the unstripped path) is always
preserved in `protocol_evidence`. The adapter normalizes for matching; it does
not alter the evidence.

### Trailing Slash Behavior (mapping.py)

Trailing slashes are NOT normalized. `/devices/ahu-1/` and `/devices/ahu-1`
are treated as different paths. Route patterns must match exactly.

This is an explicit design decision. If trailing slash equivalence is needed,
the caller should normalize the path before constructing the `ProtocolOperation`,
or the route config should include both variants.

### Adapter Contract (adapter.py)

The `normalize()` docstring was updated to state the fail-closed caller contract
explicitly:

> If `result.success is False`, the caller MUST NOT forward the operation.
> A normalization failure is not an authorization decision; treat it as deny-by-default.

### New Documentation

- `docs/contracts/adapter-contract.md` — canonical contract for all adapters
- `schemas/rest-mapping.schema.json` — JSON Schema for REST mapping config files

### New Examples

- `examples/rest/mapping-minimal.example.json` — minimal valid single-route config
- `examples/rest/mapping-invalid.example.json` — annotated invalid config for reference

---

## Intentional Non-Changes

**Query string passthrough was not added.**
The adapter normalizes path-only. Query parameters are not forwarded to the
`NormalizedAuthorizationRequest`. If authorization semantics need to depend on
query parameters, that is a design question to resolve in a future phase — it
requires defining whether query parameters map to action qualifiers, resource
attributes, or something else.

**Route priority / conflict detection was not added.**
Multiple routes can match the same (method, path) combination. First-match wins.
Conflict detection (two routes that would both match the same input) is not
validated. The ordering of routes in the config is the operator's responsibility.

**Wildcard method `"*"` counting toward duplicate detection was not changed.**
A config with two wildcard-method routes for the same path is legal (first-match
wins). Conflict detection is out of scope for this phase.

---

## BACnet Preparation Notes

Phase 2 prepares the foundation for the BACnet adapter without implementing it.
The following design decisions were made (or confirmed) with BACnet in mind.

### Normalized Request Model Remains Protocol-Agnostic

`NormalizedAuthorizationRequest` has no REST-specific fields. It uses generic
`action`, `resource_type`, `resource_id`, and `protocol` strings. A BACnet adapter
can produce:

```python
NormalizedAuthorizationRequest(
    action        = "read",
    resource_type = "analog-input",
    resource_id   = "1:present-value",
    protocol      = "bacnet",
    protocol_evidence = <BACnet ProtocolOperation>,
)
```

without any changes to the model.

### Protocol Evidence Must Support Richer Protocol Details

`ProtocolOperation.metadata` is a `dict[str, Any]` — deliberately open-ended.
For BACnet, this will carry object type, instance number, property identifier,
array index, and service type. The REST adapter only uses `subject_hint` today.

No model changes are needed for BACnet to carry richer evidence, but the BACnet
adapter documentation should define which metadata keys it uses.

### BACnet Will Add Object Type, Instance, Property, and Service Semantics

BACnet normalization is fundamentally different from REST:

| REST          | BACnet                          |
|---------------|---------------------------------|
| HTTP method   | BACnet service (`ReadProperty`) |
| URL path      | Object type + instance          |
| —             | Property identifier             |
| —             | Array index                     |

The BACnet adapter will need its own config model (not `RestMappingConfig`) that
maps BACnet object types and service primitives to normalized semantics.

### REST Must Not Introduce Assumptions That Block BACnet

Phase 2 did not add any REST-specific concepts to the shared `models.py`. The
normalization model remains generic. Future adapters are not required to use
path patterns, HTTP methods, or any REST-specific config format.

---

## Recommended Phase 3

Phase 3 should begin the BACnet adapter.

Suggested scope:

1. `BACnetOperation` model or a well-documented `ProtocolOperation` metadata
   convention for BACnet services
2. `BACnetMappingConfig` — object type + service → (action, resource_type, resource_id)
3. `BACnetAdapter` — normalize BACnet read/write/command/subscribe to
   `NormalizedAuthorizationRequest`
4. Documentation: `docs/implementation/phase-3-bacnet-adapter.md`
5. Integration test harness: a fixture that submits normalized requests to a
   local basis-gateway instance and verifies end-to-end behavior

Before Phase 3, consider whether a gateway HTTP client transport layer
(the component that actually submits `NormalizedAuthorizationRequest` to
basis-gateway over HTTP) should land first as a shared utility — both REST
and BACnet adapters would use it.
