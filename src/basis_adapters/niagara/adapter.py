"""
Niagara adapter: normalizes Niagara platform operations into BASIS
authorization requests.

The adapter accepts a NiagaraOperation representing a Niagara platform
operation intent, applies the configured NiagaraMappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No Fox/Foxs client. No Baja runtime. No Haystack client. No REST
  connector. No station, supervisor, or JACE connectivity. No packet
  parsing. No live Niagara communication.
- ORDs are preserved exactly as supplied. No ORD grammar parsing, no ORD
  resolution, no ORD link following, no component-meaning inference.
- Niagara users and roles are evidence only — never BASIS identity, never
  copied into subject_hint, never interpreted. No role mapping, no station
  permission interpretation. Identity belongs to basis-gateway.
- Overrides normalize as execute intents. No priority-array behavior, no
  override state, no release semantics, no command state.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
- normalize() never raises — all errors are captured into AdapterResult.
"""

from __future__ import annotations

from basis_adapters.errors import AdapterError
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
)
from basis_adapters.niagara.mapping import (
    VALID_NIAGARA_OPERATIONS,
    NiagaraMappingConfig,
    NiagaraOperation,
    required_any_of_target_fields,
    required_target_field,
)

PROTOCOL = "niagara"

# Optional string fields that must be non-empty strings when present.
_OPTIONAL_STRING_FIELDS = (
    "host",
    "ord",
    "component",
    "slot",
    "point",
    "point_type",
    "facet",
    "schedule",
    "alarm",
    "history",
    "category",
    "baja_type",
    "nav_path",
    "niagara_user",
    "niagara_role",
)


def _validate_operation(operation: NiagaraOperation) -> None:
    """
    Validate that a NiagaraOperation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted platform input.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.operation, str) or not operation.operation.strip():
        raise AdapterError("Operation must carry a non-empty operation name")
    if operation.operation not in VALID_NIAGARA_OPERATIONS:
        raise AdapterError(
            f"Unsupported Niagara operation '{operation.operation}'. "
            f"Supported operations: {sorted(VALID_NIAGARA_OPERATIONS)}"
        )

    # Target identity: resource IDs are station-rooted, so a station is
    # always required.
    if operation.station is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a station — "
            "Niagara resource IDs are station-rooted"
        )
    if not isinstance(operation.station, str) or not operation.station.strip():
        raise AdapterError("Operation station must be a non-empty string")

    # Optional string fields must be non-empty strings when present. ORDs
    # are preserved exactly as supplied — beyond this presence check, no ORD
    # grammar parsing or resolution is performed.
    for label in _OPTIONAL_STRING_FIELDS:
        target = getattr(operation, label)
        if target is not None and (not isinstance(target, str) or not target.strip()):
            raise AdapterError(f"Operation {label} must be a non-empty string when present")

    # Target-specific operations require their target field.
    required = required_target_field(operation.operation)
    if required is not None and getattr(operation, required) is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a {required} — "
            "target-specific operations require their target field"
        )

    # Operations with one-of-several targets require at least one.
    any_of = required_any_of_target_fields(operation.operation)
    if any_of is not None and all(getattr(operation, label) is None for label in any_of):
        raise AdapterError(
            f"{operation.operation} operations must carry at least one of: {', '.join(any_of)}"
        )


class NiagaraAdapter:
    """
    Normalizes Niagara platform operations into BASIS authorization requests.

    Usage::

        config = NiagaraMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="niagara-primary")
        adapter = NiagaraAdapter(mapping=config, context=ctx)

        op = NiagaraOperation(
            operation="OVERRIDE_POINT",
            station="station-east",
            point="AHU1-SupplyTempSetpoint",
            value=68.0,
        )
        result = adapter.normalize(op)
        if result.success:
            # submit result.request to basis-gateway
            ...
        else:
            # fail closed — do not forward the operation
            ...

    The adapter does not raise on normalization failure; it returns
    AdapterResult.fail(...) so callers can decide how to handle the outcome.

    Identity note: Niagara has its own users, roles, permissions, and
    station authentication model. The adapter preserves ``niagara_user`` and
    ``niagara_role`` as protocol evidence only. They are never copied into
    ``subject_hint``, never treated as BASIS identity, never interpreted,
    and never role-mapped. Identity resolution belongs to basis-gateway —
    the adapter only normalizes Niagara operation semantics.

    ORD note: ORD strings are preserved exactly as supplied. The adapter
    performs no ORD grammar parsing, no ORD resolution, no ORD link
    following, and infers no component meaning from ORD structure. An ORD is
    an opaque verbatim identifier that may participate in deterministic
    resource IDs.

    Override note: OVERRIDE_POINT and RELEASE_OVERRIDE normalize operational
    command intents to ``execute``. The adapter implements no priority-array
    behavior, no override state, no release semantics, and retains no
    command state — override metadata (duration, level) supplied in
    ``metadata`` is preserved as evidence.
    """

    def __init__(self, mapping: NiagaraMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: NiagaraOperation) -> AdapterResult:
        """
        Normalize a NiagaraOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the
          operation. A normalization failure is not an authorization
          decision; treat it as deny-by-default.
        - The original NiagaraOperation is converted to a ProtocolOperation
          and always embedded in result.request as protocol_evidence. All
          Niagara fields (station, host, ord, component, slot, point, point
          type, value, facet, schedule, alarm, history, category, baja type,
          nav path, niagara_user, niagara_role) are preserved in the
          protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: NiagaraOperation) -> AdapterResult:
        _validate_operation(operation)
        route = self._mapping.match(operation)
        action = self._mapping.resolve_action(route, operation)
        resource_id = self._mapping.resolve_resource_id(route, operation)
        protocol_evidence = operation.to_protocol_operation()

        request = NormalizedAuthorizationRequest(
            action=action,
            resource_type=route.resource_type,
            resource_id=resource_id,
            protocol=PROTOCOL,
            protocol_evidence=protocol_evidence,
            subject_hint=operation.metadata.get("subject_hint"),
        )
        return AdapterResult.ok(request)
