"""
MQTT adapter: normalizes MQTT operations into BASIS authorization requests.

The adapter accepts an MqttOperation representing an MQTT PUBLISH or
SUBSCRIBE intent, applies the configured MqttMappingConfig, and produces a
NormalizedAuthorizationRequest suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- No paho-mqtt. No TCP sockets. No broker connection. No TLS. No packet
  parsing. No live MQTT communication.
- Fail closed: unknown operations and invalid mappings produce failure results.
- Topics are preserved verbatim. MQTT wildcards (``+``, ``#``) are never
  expanded — wildcard authorization policy belongs to policy evaluation,
  not the adapter.
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
from basis_adapters.mqtt.mapping import (
    VALID_MQTT_OPERATIONS,
    VALID_MQTT_PAYLOAD_TYPES,
    VALID_MQTT_QOS_LEVELS,
    MqttMappingConfig,
    MqttOperation,
)

PROTOCOL = "mqtt"


def _validate_operation(operation: MqttOperation) -> None:
    """
    Validate that an MqttOperation is structurally sound before matching.

    These checks are runtime guards: the dataclass types are advisory and the
    operation may have been constructed from untrusted protocol input.

    Note that topics containing MQTT wildcard characters (``+``, ``#``) are
    accepted and preserved verbatim — they are not expanded, matched, or
    rejected here. Whether a wildcard subscription should be authorized is a
    policy question, not a normalization question.

    Raises:
        AdapterError: If the operation is invalid. The adapter converts this
            into a failure result (fail closed).
    """
    if not isinstance(operation.operation, str) or not operation.operation.strip():
        raise AdapterError("Operation must carry a non-empty operation name")
    if operation.operation not in VALID_MQTT_OPERATIONS:
        raise AdapterError(
            f"Unsupported MQTT operation '{operation.operation}'. "
            f"Supported operations: {sorted(VALID_MQTT_OPERATIONS)}"
        )
    if not isinstance(operation.topic, str) or not operation.topic.strip():
        raise AdapterError("Operation topic must be a non-empty string")
    if isinstance(operation.qos, bool) or not isinstance(operation.qos, int):
        raise AdapterError("Operation qos must be an integer (0, 1, or 2)")
    if operation.qos not in VALID_MQTT_QOS_LEVELS:
        raise AdapterError(
            f"Invalid MQTT QoS level {operation.qos!r}. "
            f"Valid levels: {sorted(VALID_MQTT_QOS_LEVELS)}"
        )
    if not isinstance(operation.retain, bool):
        raise AdapterError("Operation retain must be a boolean")
    if operation.operation == "SUBSCRIBE" and operation.retain:
        raise AdapterError(
            "SUBSCRIBE operations must not set retain=True — the retain flag is a PUBLISH concept"
        )
    if (
        not isinstance(operation.payload_type, str)
        or operation.payload_type not in VALID_MQTT_PAYLOAD_TYPES
    ):
        raise AdapterError(
            f"Invalid payload_type {operation.payload_type!r}. "
            f"Valid payload types: {sorted(VALID_MQTT_PAYLOAD_TYPES)}"
        )
    if operation.client_id is not None and (
        not isinstance(operation.client_id, str) or not operation.client_id.strip()
    ):
        raise AdapterError("Operation client_id must be a non-empty string when present")
    if operation.protocol_version is not None and (
        not isinstance(operation.protocol_version, str) or not operation.protocol_version.strip()
    ):
        raise AdapterError("Operation protocol_version must be a non-empty string when present")


class MqttAdapter:
    """
    Normalizes MQTT operations into BASIS authorization requests.

    Usage::

        config = MqttMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="mqtt-primary")
        adapter = MqttAdapter(mapping=config, context=ctx)

        op = MqttOperation(
            operation="PUBLISH",
            topic="building/ahu-1/setpoint",
            client_id="bms-controller-7",
            qos=1,
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

    def __init__(self, mapping: MqttMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: MqttOperation) -> AdapterResult:
        """
        Normalize an MqttOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        Contract:
        - This method never raises — errors are captured into AdapterResult.
        - If result.success is False, the caller MUST NOT forward the operation.
          A normalization failure is not an authorization decision; treat it as
          deny-by-default.
        - The original MqttOperation is converted to a ProtocolOperation and
          always embedded in result.request as protocol_evidence. All MQTT
          fields (including topic, client_id, qos, retain, payload_type,
          protocol_version) are preserved in the protocol_evidence metadata.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: MqttOperation) -> AdapterResult:
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
