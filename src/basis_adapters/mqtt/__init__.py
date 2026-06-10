"""
MQTT adapter for the BASIS ecosystem.

Normalizes MQTT PUBLISH and SUBSCRIBE intents into BASIS authorization
requests. No live MQTT broker communication — pure normalization.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.mqtt import MqttAdapter, MqttMappingConfig, MqttOperation

    import json

    with open("examples/mqtt/mapping.example.json") as f:
        config = MqttMappingConfig.from_dict(json.load(f))

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
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.mqtt.adapter import MqttAdapter
from basis_adapters.mqtt.mapping import (
    VALID_MQTT_OPERATIONS,
    VALID_MQTT_PAYLOAD_TYPES,
    VALID_MQTT_QOS_LEVELS,
    VALID_MQTT_TEMPLATE_FIELDS,
    MqttMappingConfig,
    MqttOperation,
    MqttRouteMapping,
)

__all__ = [
    "MqttAdapter",
    "MqttMappingConfig",
    "MqttOperation",
    "MqttRouteMapping",
    "VALID_MQTT_OPERATIONS",
    "VALID_MQTT_PAYLOAD_TYPES",
    "VALID_MQTT_QOS_LEVELS",
    "VALID_MQTT_TEMPLATE_FIELDS",
]
