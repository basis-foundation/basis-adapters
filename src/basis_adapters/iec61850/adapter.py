"""
IEC 61850 adapter: normalizes IEC 61850 operations into BASIS authorization
requests.

The adapter accepts an Iec61850Operation representing an IEC 61850 service
request intent, applies the configured Iec61850MappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No MMS stack. No GOOSE subscriber. No Sampled Values processor. No
  multicast handling. No client/server association. No packet parsing. No
  live IEC 61850 communication.
- Stateless: SELECT and OPERATE normalize independently. The adapter does not
  correlate select/operate pairs, track control sequences, enforce select
  timeouts, or model device confirmations. Stateful control sequencing
  belongs to a runtime enforcement boundary, protocol gateway, or a future
  IEC 61850-aware runtime layer, not a normalization library.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
- normalize() never raises — all errors are captured into AdapterResult.
"""

from __future__ import annotations

from basis_adapters.errors import AdapterError
from basis_adapters.iec61850.mapping import (
    IEC61850_CONTROL_OPERATIONS,
    IEC61850_DIRECT_CONTROL_MODELS,
    IEC61850_SBO_CONTROL_MODELS,
    IEC61850_SUBSCRIPTION_OPERATIONS,
    VALID_IEC61850_CONTROL_MODELS,
    VALID_IEC61850_FUNCTIONAL_CONSTRAINTS,
    VALID_IEC61850_OPERATIONS,
    Iec61850MappingConfig,
    Iec61850Operation,
)
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
)

PROTOCOL = "iec61850"

# Subscription operations and the control block field each requires.
_REQUIRED_CONTROL_BLOCK_FIELD: dict[str, str] = {
    "ENABLE_REPORTING": "report_control_block",
    "ENABLE_GOOSE": "goose_control_block",
    "ENABLE_SAMPLED_VALUES": "sampled_values_control_block",
}


def _require_str_when_present(value: object, label: str) -> None:
    """Raise AdapterError unless value is a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"Operation {label} must be a non-empty string when present")


def _validate_operation(operation: Iec61850Operation) -> None:
    """
    Validate that an Iec61850Operation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted protocol input.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.operation, str) or not operation.operation.strip():
        raise AdapterError("Operation must carry a non-empty operation name")
    if operation.operation not in VALID_IEC61850_OPERATIONS:
        raise AdapterError(
            f"Unsupported IEC 61850 operation '{operation.operation}'. "
            f"Supported operations: {sorted(VALID_IEC61850_OPERATIONS)}"
        )

    # Target identity: every IEC 61850 operation must identify its IED.
    if operation.ied_name is None:
        raise AdapterError("Operation must carry target identity: ied_name is required")
    _require_str_when_present(operation.ied_name, "ied_name")

    # Optional string fields must be non-empty when present.
    for label in (
        "logical_device",
        "logical_node",
        "data_object",
        "data_attribute",
        "dataset",
        "report_control_block",
        "goose_control_block",
        "sampled_values_control_block",
        "cause",
        "quality",
        "timestamp",
    ):
        value = getattr(operation, label)
        if value is not None:
            _require_str_when_present(value, label)

    if operation.origin is not None and not isinstance(operation.origin, dict):
        raise AdapterError("Operation origin must be a dict when present")

    # Hierarchical addressing: each level requires its parent. A data
    # attribute without a data object (or a logical node without a logical
    # device) is not a deterministic IEC 61850 address.
    if operation.logical_node is not None and operation.logical_device is None:
        raise AdapterError("Operation logical_node requires logical_device to be present")
    if operation.data_object is not None and operation.logical_node is None:
        raise AdapterError("Operation data_object requires logical_node to be present")
    if operation.data_attribute is not None and operation.data_object is None:
        raise AdapterError("Operation data_attribute requires data_object to be present")

    if (
        operation.functional_constraint is not None
        and operation.functional_constraint not in VALID_IEC61850_FUNCTIONAL_CONSTRAINTS
    ):
        raise AdapterError(
            f"Invalid IEC 61850 functional constraint '{operation.functional_constraint}'. "
            f"Valid functional constraints: {sorted(VALID_IEC61850_FUNCTIONAL_CONSTRAINTS)}"
        )

    # Read/write operations address logical-node-level (or deeper) targets.
    if operation.operation in {"READ", "WRITE"} and operation.logical_node is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a logical_node — "
            "read/write targets are addressed within a logical node"
        )

    # Control commands target a specific data object: a control operation
    # without one cannot be normalized into a data-object-addressed resource.
    if operation.operation in IEC61850_CONTROL_OPERATIONS and operation.data_object is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a data_object — control "
            "commands are data-object-specific"
        )

    # Subscription operations must identify their control block.
    if operation.operation in IEC61850_SUBSCRIPTION_OPERATIONS:
        if operation.logical_node is None:
            raise AdapterError(
                f"{operation.operation} operations must carry a logical_node — "
                "control blocks live within a logical node"
            )
        required_field = _REQUIRED_CONTROL_BLOCK_FIELD[operation.operation]
        if getattr(operation, required_field) is None:
            raise AdapterError(f"{operation.operation} operations must carry a {required_field}")

    if operation.control_model is not None:
        if operation.control_model not in VALID_IEC61850_CONTROL_MODELS:
            raise AdapterError(
                f"Invalid IEC 61850 control model '{operation.control_model}'. "
                f"Valid control models: {sorted(VALID_IEC61850_CONTROL_MODELS)}"
            )
        # Control model must be consistent with the operation — no silent
        # reinterpretation of select-before-operate vs direct-operate intent.
        if operation.operation in IEC61850_CONTROL_OPERATIONS:
            if operation.control_model == "status_only":
                raise AdapterError(
                    f"{operation.operation} operations must not declare control_model "
                    "'status_only' — status-only points cannot be controlled"
                )
            if operation.operation == "DIRECT_OPERATE" and (
                operation.control_model in IEC61850_SBO_CONTROL_MODELS
            ):
                raise AdapterError(
                    "DIRECT_OPERATE operations must not declare a select-before-operate "
                    f"control model ('{operation.control_model}')"
                )
            if operation.operation in {"SELECT", "SELECT_WITH_VALUE", "OPERATE", "CANCEL"} and (
                operation.control_model in IEC61850_DIRECT_CONTROL_MODELS
            ):
                raise AdapterError(
                    f"{operation.operation} operations must not declare a direct-operate "
                    f"control model ('{operation.control_model}')"
                )


class Iec61850Adapter:
    """
    Normalizes IEC 61850 operations into BASIS authorization requests.

    Usage::

        config = Iec61850MappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="iec61850-primary")
        adapter = Iec61850Adapter(mapping=config, context=ctx)

        op = Iec61850Operation(
            operation="DIRECT_OPERATE",
            ied_name="ied-sub1",
            logical_device="CTRL",
            logical_node="CSWI1",
            data_object="Pos",
            control_model="direct_with_normal_security",
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

    Select-before-operate note: SELECT, SELECT_WITH_VALUE, OPERATE, CANCEL,
    and DIRECT_OPERATE are each normalized as independent
    authorization-relevant operations. The adapter keeps no state between
    them — no correlation, no timeout handling, no command sequencing, no
    device confirmation semantics. Those belong to a runtime enforcement
    boundary, protocol gateway, or a future IEC 61850-aware runtime layer,
    not a stateless normalization component. The control model is preserved
    in protocol evidence so downstream layers can reason about the pattern.

    GOOSE and Sampled Values note: enable-style intents normalize to
    ``subscribe`` with control block identity preserved as evidence. The
    adapter implements no multicast behavior, no frame parsing, no timing
    semantics, no protection-trip behavior, and no stream processing — those
    are operationally sensitive wire-protocol behaviors and remain outside
    this normalization adapter.
    """

    def __init__(self, mapping: Iec61850MappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: Iec61850Operation) -> AdapterResult:
        """
        Normalize an Iec61850Operation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the
          operation. A normalization failure is not an authorization
          decision; treat it as deny-by-default.
        - The original Iec61850Operation is converted to a ProtocolOperation
          and always embedded in result.request as protocol_evidence. All
          IEC 61850 fields (IED/logical device/logical node/data object/data
          attribute identity, functional constraint, dataset, control block
          names, control model, origin, cause, quality, timestamp, value)
          are preserved in the protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: Iec61850Operation) -> AdapterResult:
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
