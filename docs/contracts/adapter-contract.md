# Adapter Contract

This document defines the engineering contract that every adapter in the
basis-adapters repository must satisfy. It applies to the REST adapter now and
to every future adapter (BACnet, Modbus, etc.).

---

## Input

An adapter accepts a `ProtocolOperation`:

```python
@dataclass(frozen=True)
class ProtocolOperation:
    protocol: str          # e.g. "rest", "bacnet"
    method:   str          # e.g. "GET", "ReadProperty"
    path:     str          # e.g. "/devices/ahu-1/points/supply-temp"
    metadata: dict         # protocol-specific extras
```

The `ProtocolOperation` represents an operation as received from the wire,
before any interpretation. Adapters must not modify it.

---

## Output

An adapter returns an `AdapterResult`:

```python
@dataclass(frozen=True)
class AdapterResult:
    request: NormalizedAuthorizationRequest | None
    error:   str | None
    success: bool
```

Exactly one of `request` (success) or `error` (failure) will be set.
`success` is always `True` when `request` is set and `False` when `error` is set.

---

## What `AdapterResult.success` Means

`success = True` means:

> The adapter successfully normalized the protocol operation into a
> `NormalizedAuthorizationRequest`. The request is structurally valid and
> ready to be submitted to basis-gateway.

It does NOT mean the operation is authorized. Authorization is the gateway's
responsibility.

`success = False` means:

> The adapter could not normalize the operation. The `error` field contains
> a human-readable reason (e.g. "No route matched: DELETE /devices/ahu-1").

---

## What Failure Means — Fail-Closed Contract

**Adapter failure is not an authorization decision.**

When `result.success is False`, the caller MUST NOT forward the operation to
basis-gateway or treat it as allowed. The correct response is to deny the
operation at the enforcement boundary.

This is the fail-closed contract:

```
if not result.success:
    # Normalization failed — deny the operation.
    # Do not forward to gateway.
    # Log result.error for diagnostics.
    return deny()
```

Common reasons for normalization failure:

- No configured route matches the operation (`UnknownRouteError`)
- The operation method is not covered by any route
- A mapping configuration error was not caught at startup

The adapter itself must never raise from `normalize()`. All errors must be
captured and returned as `AdapterResult.fail(...)`.

---

## Protocol Evidence

Every successful `NormalizedAuthorizationRequest` must carry the original
`ProtocolOperation` as `protocol_evidence`:

```python
@dataclass(frozen=True)
class NormalizedAuthorizationRequest:
    ...
    protocol_evidence: ProtocolOperation
```

This is mandatory and non-negotiable. Protocol evidence enables:

- Audit trails that record what wire-level operation triggered an authorization request
- Debugging and incident investigation
- Future adapters that need to inspect the original operation for enrichment

Adapters must not strip, replace, or summarize protocol evidence.

---

## What Adapters Must Never Do

**Adapters must not authenticate.**
Identity resolution belongs to basis-gateway. Adapters may forward a
`subject_hint` from protocol metadata, but they do not verify, decode, or
trust it.

**Adapters must not evaluate policy.**
Whether an operation is allowed is determined by basis-core, invoked through
basis-gateway. Adapters produce the input to that decision; they do not make it.

**Adapters must not enforce decisions.**
Adapters produce `NormalizedAuthorizationRequest` objects. They do not receive
or act on authorization outcomes.

**Adapters must not call basis-core.**
No direct import or invocation of the authorization kernel.

**Adapters must not call basis-gateway during normalization.**
Normalization is a pure, in-process transformation. No network calls.

**Adapters must not guess on invalid input.**
When mapping is ambiguous or a route is unknown, the adapter raises
(`UnknownRouteError`, `InvalidMappingError`) or returns a failure result.
Silent partial normalization is not permitted.

---

## Mapping Configuration Contract

Adapter mapping configuration must be validated eagerly — at construction time,
not at normalization time. A misconfigured adapter must fail on startup, not
on the first real operation.

Mapping errors must raise `InvalidMappingError`. Route matching failures must
raise `UnknownRouteError`. Both are subtypes of `AdapterError`.

---

## Compatibility Expectations for Future Adapters

All future adapters (BACnet, Modbus, etc.) must:

1. Accept protocol-specific input and return `AdapterResult`.
2. Produce `NormalizedAuthorizationRequest` using the same frozen model.
3. Always attach `protocol_evidence` to the normalized request.
4. Never call basis-core or basis-gateway during normalization.
5. Fail closed on unknown operations.
6. Validate configuration eagerly and raise `InvalidMappingError` on bad config.

The `NormalizedAuthorizationRequest` model is the stable interface between
all adapters and basis-gateway. Adapters diverge on input; they converge on output.

---

## Summary Table

| Responsibility              | Adapter | Gateway | basis-core |
|-----------------------------|---------|---------|------------|
| Parse protocol operation    | ✓       |         |            |
| Normalize to auth request   | ✓       |         |            |
| Preserve protocol evidence  | ✓       |         |            |
| Resolve subject identity    |         | ✓       |            |
| Evaluate policy             |         |         | ✓          |
| Enforce decision            |         | ✓       |            |
| Fail closed on unknown ops  | ✓       |         |            |
