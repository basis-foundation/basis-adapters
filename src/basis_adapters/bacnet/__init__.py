"""
BACnet adapter for the BASIS ecosystem.

Normalizes BACnet service primitives (ReadProperty, WriteProperty, SubscribeCOV,
CommandValue) into BASIS authorization requests.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.bacnet import BacnetAdapter, BacnetMappingConfig, BacnetOperation

    import json

    with open("examples/bacnet/mapping.example.json") as f:
        config = BacnetMappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="bacnet-primary")
    adapter = BacnetAdapter(mapping=config, context=ctx)

    op = BacnetOperation(
        service="ReadProperty",
        object_type="analogInput",
        object_instance=1,
        property_identifier="presentValue",
        device_id="device-42",
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import (
    VALID_BACNET_SERVICES,
    VALID_BACNET_TEMPLATE_FIELDS,
    BacnetMappingConfig,
    BacnetOperation,
    BacnetRouteMapping,
)

__all__ = [
    "BacnetAdapter",
    "BacnetMappingConfig",
    "BacnetOperation",
    "BacnetRouteMapping",
    "VALID_BACNET_SERVICES",
    "VALID_BACNET_TEMPLATE_FIELDS",
]
