"""
Modbus adapter: normalizes Modbus operations into BASIS authorization requests.

The adapter accepts a ModbusOperation representing a Modbus function request,
applies the configured ModbusMappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No pymodbus. No TCP sockets. No live Modbus communication.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
- normalize() never raises — all errors are captured into AdapterResult.
"""

from __future__ import annotations

from basis_adapters.errors import AdapterError
from basis_adapters.modbus.mapping import ModbusMappingConfig, ModbusOperation
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
)

PROTOCOL = "modbus"


class ModbusAdapter:
    """
    Normalizes Modbus operations into BASIS authorization requests.

    Usage::

        config = ModbusMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="modbus-primary")
        adapter = ModbusAdapter(mapping=config, context=ctx)

        op = ModbusOperation(
            function="ReadHoldingRegisters",
            unit_id=1,
            address=40001,
            quantity=1,
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

    def __init__(self, mapping: ModbusMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: ModbusOperation) -> AdapterResult:
        """
        Normalize a ModbusOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the operation.
          A normalization failure is not an authorization decision; treat it as
          deny-by-default.
        - The original ModbusOperation is converted to a ProtocolOperation and
          always embedded in result.request as protocol_evidence. All Modbus
          fields (including unit_id, address, quantity, value_present) are
          preserved in the protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: ModbusOperation) -> AdapterResult:
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
