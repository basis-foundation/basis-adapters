"""
OPC UA adapter: normalizes OPC UA operations into BASIS authorization requests.

The adapter accepts an OpcuaOperation representing an OPC UA service request,
applies the configured OpcuaMappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No asyncua. No TCP sockets. No endpoint discovery. No certificate handling.
  No secure channel. No sessions. No live OPC UA communication.
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
from basis_adapters.opcua.mapping import (
    VALID_OPCUA_IDENTIFIER_TYPES,
    VALID_OPCUA_SERVICES,
    OpcuaMappingConfig,
    OpcuaOperation,
)

PROTOCOL = "opcua"


def _validate_operation(operation: OpcuaOperation) -> None:
    """
    Validate that an OpcuaOperation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted protocol input.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.service, str) or not operation.service.strip():
        raise AdapterError("Operation service must be a non-empty string")
    if operation.service not in VALID_OPCUA_SERVICES:
        raise AdapterError(
            f"Unsupported OPC UA service '{operation.service}'. "
            f"Supported services: {sorted(VALID_OPCUA_SERVICES)}"
        )
    if not isinstance(operation.node_id, str) or not operation.node_id.strip():
        raise AdapterError("Operation node_id must be a non-empty string")
    if operation.namespace_index is not None and (
        isinstance(operation.namespace_index, bool)
        or not isinstance(operation.namespace_index, int)
    ):
        raise AdapterError("Operation namespace_index must be an integer when present")
    if operation.attribute_id is not None and (
        not isinstance(operation.attribute_id, str) or not operation.attribute_id.strip()
    ):
        raise AdapterError("Operation attribute_id must be a non-empty string when present")
    if operation.identifier_type is not None and (
        operation.identifier_type not in VALID_OPCUA_IDENTIFIER_TYPES
    ):
        raise AdapterError(
            f"Operation identifier_type '{operation.identifier_type}' is not valid. "
            f"Valid identifier types: {sorted(VALID_OPCUA_IDENTIFIER_TYPES)}"
        )
    if operation.service == "Call" and (
        not isinstance(operation.method_id, str) or not operation.method_id.strip()
    ):
        raise AdapterError("Call operations must carry a non-empty method_id")


class OpcuaAdapter:
    """
    Normalizes OPC UA operations into BASIS authorization requests.

    Usage::

        config = OpcuaMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="opcua-primary")
        adapter = OpcuaAdapter(mapping=config, context=ctx)

        op = OpcuaOperation(
            service="Read",
            node_id="ns=2;s=Building.AHU1.SupplyTemp",
            attribute_id="Value",
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
    """

    def __init__(self, mapping: OpcuaMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: OpcuaOperation) -> AdapterResult:
        """
        Normalize an OpcuaOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the operation.
          A normalization failure is not an authorization decision; treat it as
          deny-by-default.
        - The original OpcuaOperation is converted to a ProtocolOperation and
          always embedded in result.request as protocol_evidence. All OPC UA
          fields (including node_id, namespace_index, attribute_id, method_id,
          endpoint_url, session_id) are preserved in the protocol_evidence
          metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: OpcuaOperation) -> AdapterResult:
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
