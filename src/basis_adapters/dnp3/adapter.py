"""
DNP3 adapter: normalizes DNP3 operations into BASIS authorization requests.

The adapter accepts a Dnp3Operation representing a DNP3 application-layer
request intent, applies the configured Dnp3MappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No DNP3 stack. No master or outstation implementation. No TCP/serial
  transport. No packet parsing. No live DNP3 communication.
- Stateless: SELECT and OPERATE normalize independently. The adapter does not
  correlate select/operate pairs, track sequence numbers, enforce select
  timeouts, or protect against replay. Stateful control sequencing belongs to
  a runtime enforcement boundary or a future DNP3-aware runtime layer, not a
  normalization library.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
- normalize() never raises — all errors are captured into AdapterResult.
"""

from __future__ import annotations

from basis_adapters.dnp3.mapping import (
    DNP3_CONTROL_OPERATIONS,
    VALID_DNP3_CONTROL_MODELS,
    VALID_DNP3_OPERATIONS,
    VALID_DNP3_POINT_TYPES,
    Dnp3MappingConfig,
    Dnp3Operation,
)
from basis_adapters.errors import AdapterError
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
)

PROTOCOL = "dnp3"

# DNP3 link-layer addresses are 16-bit.
_MAX_DNP3_ADDRESS = 0xFFFF

# Object group, variation, function code, qualifier, and control code are
# 8-bit values in DNP3.
_MAX_OCTET = 0xFF

# DNP3 event classes: 0 (static) through 3.
_MAX_EVENT_CLASS = 3


def _require_int_in_range(value: object, low: int, high: int, label: str) -> None:
    """Raise AdapterError unless value is an int (not bool) within [low, high]."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError(f"Operation {label} must be an integer when present")
    if not low <= value <= high:
        raise AdapterError(f"Operation {label} must be between {low} and {high}, got {value}")


def _validate_operation(operation: Dnp3Operation) -> None:
    """
    Validate that a Dnp3Operation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted protocol input.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.operation, str) or not operation.operation.strip():
        raise AdapterError("Operation must carry a non-empty operation name")
    if operation.operation not in VALID_DNP3_OPERATIONS:
        raise AdapterError(
            f"Unsupported DNP3 operation '{operation.operation}'. "
            f"Supported operations: {sorted(VALID_DNP3_OPERATIONS)}"
        )

    # Target identity: an outstation must be identified, either logically
    # (outstation_id) or by link-layer destination address.
    if operation.outstation_id is None and operation.destination_address is None:
        raise AdapterError(
            "Operation must carry target identity: outstation_id or destination_address"
        )
    if operation.outstation_id is not None and (
        not isinstance(operation.outstation_id, str) or not operation.outstation_id.strip()
    ):
        raise AdapterError("Operation outstation_id must be a non-empty string when present")
    if operation.master_id is not None and (
        not isinstance(operation.master_id, str) or not operation.master_id.strip()
    ):
        raise AdapterError("Operation master_id must be a non-empty string when present")

    if operation.source_address is not None:
        _require_int_in_range(operation.source_address, 0, _MAX_DNP3_ADDRESS, "source_address")
    if operation.destination_address is not None:
        _require_int_in_range(
            operation.destination_address, 0, _MAX_DNP3_ADDRESS, "destination_address"
        )

    if operation.object_group is not None:
        _require_int_in_range(operation.object_group, 0, _MAX_OCTET, "object_group")
    if operation.variation is not None:
        _require_int_in_range(operation.variation, 0, _MAX_OCTET, "variation")
        if operation.object_group is None:
            raise AdapterError("Operation variation requires object_group to be present")
    if operation.point_index is not None:
        if isinstance(operation.point_index, bool) or not isinstance(operation.point_index, int):
            raise AdapterError("Operation point_index must be an integer when present")
        if operation.point_index < 0:
            raise AdapterError(
                f"Operation point_index must be non-negative, got {operation.point_index}"
            )
    if operation.point_type is not None and operation.point_type not in VALID_DNP3_POINT_TYPES:
        raise AdapterError(
            f"Invalid DNP3 point type '{operation.point_type}'. "
            f"Valid point types: {sorted(VALID_DNP3_POINT_TYPES)}"
        )

    if operation.function_code is not None:
        _require_int_in_range(operation.function_code, 0, _MAX_OCTET, "function_code")
    if operation.qualifier is not None:
        _require_int_in_range(operation.qualifier, 0, _MAX_OCTET, "qualifier")
    if operation.control_code is not None:
        _require_int_in_range(operation.control_code, 0, _MAX_OCTET, "control_code")
    if operation.event_class is not None:
        _require_int_in_range(operation.event_class, 0, _MAX_EVENT_CLASS, "event_class")

    if operation.control_model is not None:
        if operation.control_model not in VALID_DNP3_CONTROL_MODELS:
            raise AdapterError(
                f"Invalid DNP3 control model '{operation.control_model}'. "
                f"Valid control models: {sorted(VALID_DNP3_CONTROL_MODELS)}"
            )
        # Control model must be consistent with the operation — no silent
        # reinterpretation of select-before-operate vs direct-operate intent.
        if operation.operation == "DIRECT_OPERATE" and (
            operation.control_model == "select_before_operate"
        ):
            raise AdapterError(
                "DIRECT_OPERATE operations must not declare control_model 'select_before_operate'"
            )
        if operation.operation in {"SELECT", "OPERATE"} and (
            operation.control_model == "direct_operate"
        ):
            raise AdapterError(
                f"{operation.operation} operations must not declare control_model 'direct_operate'"
            )

    # Control commands target a specific point: a control operation without a
    # point index cannot be normalized into a point-addressed resource.
    if operation.operation in DNP3_CONTROL_OPERATIONS and operation.point_index is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a point_index — control "
            "commands are point-specific"
        )


class Dnp3Adapter:
    """
    Normalizes DNP3 operations into BASIS authorization requests.

    Usage::

        config = Dnp3MappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="dnp3-primary")
        adapter = Dnp3Adapter(mapping=config, context=ctx)

        op = Dnp3Operation(
            operation="DIRECT_OPERATE",
            outstation_id="os-14",
            point_type="binary_output",
            point_index=7,
            control_model="direct_operate",
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

    Select-before-operate note: SELECT and OPERATE are each normalized as
    independent authorization-relevant operations. The adapter keeps no state
    between them — no correlation, no timeout handling, no sequencing, no
    replay protection. Those belong to a runtime enforcement boundary, not a
    stateless normalization component. The control model is preserved in
    protocol evidence so downstream layers can reason about the pattern.
    """

    def __init__(self, mapping: Dnp3MappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: Dnp3Operation) -> AdapterResult:
        """
        Normalize a Dnp3Operation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the operation.
          A normalization failure is not an authorization decision; treat it as
          deny-by-default.
        - The original Dnp3Operation is converted to a ProtocolOperation and
          always embedded in result.request as protocol_evidence. All DNP3
          fields (addresses, object group/variation, point identity, function
          code, qualifier, control code, control model, event class, value)
          are preserved in the protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: Dnp3Operation) -> AdapterResult:
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
