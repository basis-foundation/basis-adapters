"""
KNX adapter: normalizes KNX operations into BASIS authorization requests.

The adapter accepts a KnxOperation representing a KNX group-communication
intent, applies the configured KnxMappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No KNX/IP tunneling. No routing. No multicast. No bus communication. No
  bus monitoring. No packet parsing. No live KNX communication.
- Group addresses are preserved verbatim. No topology expansion, no
  room/floor/equipment inference, no group-address authorization logic —
  authorization semantics belong above the adapter.
- Datapoint types are preserved as evidence. DPT payload semantics are not
  parsed or validated beyond a basic shape check, and payload values are
  never coerced into operational meaning.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
- normalize() never raises — all errors are captured into AdapterResult.
"""

from __future__ import annotations

from basis_adapters.errors import AdapterError
from basis_adapters.knx.mapping import (
    VALID_KNX_OPERATIONS,
    VALID_KNX_PRIORITIES,
    KnxMappingConfig,
    KnxOperation,
    is_valid_datapoint_type,
    is_valid_group_address,
    is_valid_individual_address,
)
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
)

PROTOCOL = "knx"


def _validate_operation(operation: KnxOperation) -> None:
    """
    Validate that a KnxOperation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted protocol input.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.operation, str) or not operation.operation.strip():
        raise AdapterError("Operation must carry a non-empty operation name")
    if operation.operation not in VALID_KNX_OPERATIONS:
        raise AdapterError(
            f"Unsupported KNX operation '{operation.operation}'. "
            f"Supported operations: {sorted(VALID_KNX_OPERATIONS)}"
        )

    # Target identity: every supported KNX operation is a group-address
    # operation, so a group address is always required.
    if operation.group_address is None:
        raise AdapterError(
            f"{operation.operation} operations must carry a group_address — "
            "all supported KNX operations are group-address operations"
        )
    if not isinstance(operation.group_address, str) or not operation.group_address.strip():
        raise AdapterError("Operation group_address must be a non-empty string")
    if not is_valid_group_address(operation.group_address):
        raise AdapterError(
            f"Invalid KNX group address '{operation.group_address}'. Expected "
            "three-level 'main/middle/sub' (0-31/0-7/0-255), two-level "
            "'main/sub' (0-31/0-2047), or free-style (0-65535) notation"
        )

    # Individual and device addresses are optional evidence but must be
    # well-formed KNX individual-address notation when present.
    for label in ("individual_address", "device_address"):
        addr = getattr(operation, label)
        if addr is not None:
            if not isinstance(addr, str) or not addr.strip():
                raise AdapterError(f"Operation {label} must be a non-empty string when present")
            if not is_valid_individual_address(addr):
                raise AdapterError(
                    f"Invalid KNX {label} '{addr}'. Expected 'area.line.device' "
                    "notation (0-15.0-15.0-255)"
                )

    if operation.communication_object is not None:
        if isinstance(operation.communication_object, bool) or not isinstance(
            operation.communication_object, int
        ):
            raise AdapterError("Operation communication_object must be an integer when present")
        if operation.communication_object < 0:
            raise AdapterError("Operation communication_object must be non-negative")

    if operation.datapoint_type is not None:
        if not isinstance(operation.datapoint_type, str) or not operation.datapoint_type.strip():
            raise AdapterError("Operation datapoint_type must be a non-empty string when present")
        if not is_valid_datapoint_type(operation.datapoint_type):
            raise AdapterError(
                f"Malformed KNX datapoint type '{operation.datapoint_type}'. "
                "Expected DPT notation such as '1.001' (basic shape check only)"
            )

    if operation.payload_type is not None and (
        not isinstance(operation.payload_type, str) or not operation.payload_type.strip()
    ):
        raise AdapterError("Operation payload_type must be a non-empty string when present")

    if operation.priority is not None and operation.priority not in VALID_KNX_PRIORITIES:
        raise AdapterError(
            f"Invalid KNX priority {operation.priority!r}. "
            f"Valid priorities: {sorted(VALID_KNX_PRIORITIES)}"
        )

    # Topology evidence fields must be integers within KNX ranges when present.
    for label, upper in (("area", 15), ("line", 15), ("device", 255)):
        value = getattr(operation, label)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int):
                raise AdapterError(f"Operation {label} must be an integer when present")
            if not 0 <= value <= upper:
                raise AdapterError(f"Operation {label} must be between 0 and {upper}")


class KnxAdapter:
    """
    Normalizes KNX operations into BASIS authorization requests.

    Usage::

        config = KnxMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="knx-primary")
        adapter = KnxAdapter(mapping=config, context=ctx)

        op = KnxOperation(
            operation="GROUP_VALUE_WRITE",
            group_address="1/2/3",
            datapoint_type="1.001",
            value=True,
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

    Group address note: group addresses are matched and preserved verbatim.
    The adapter performs no topology expansion and infers no room, floor,
    equipment, or semantic meaning — a group address is an opaque identifier
    unless mapping metadata explicitly provides more. KNX group-address
    authorization logic belongs above the adapter.

    Observe note: OBSERVE normalizes an explicit intent to monitor a group
    address to ``subscribe``. The adapter implements no bus sniffing, no
    multicast monitoring, no KNX/IP routing or tunneling, and retains no bus
    state — normalizing the intent is the entire behavior.
    """

    def __init__(self, mapping: KnxMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: KnxOperation) -> AdapterResult:
        """
        Normalize a KnxOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the
          operation. A normalization failure is not an authorization
          decision; treat it as deny-by-default.
        - The original KnxOperation is converted to a ProtocolOperation and
          always embedded in result.request as protocol_evidence. All KNX
          fields (group address, individual/device address, communication
          object, datapoint type, payload type, value, priority, topology
          area/line/device) are preserved in the protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: KnxOperation) -> AdapterResult:
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
