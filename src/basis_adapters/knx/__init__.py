"""
KNX adapter for the BASIS ecosystem.

Normalizes KNX group value read, group value write, group value response, and
observe/monitor intents into BASIS authorization requests. No live KNX
communication — pure normalization. No KNX/IP tunneling, no routing, no
multicast, no bus monitoring, no packet parsing.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.knx import (
        KnxAdapter,
        KnxMappingConfig,
        KnxOperation,
    )

    import json

    with open("examples/knx/mapping.example.json") as f:
        config = KnxMappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="knx-primary")
    adapter = KnxAdapter(mapping=config, context=ctx)

    op = KnxOperation(
        operation="GROUP_VALUE_WRITE",
        group_address="1/2/3",
        individual_address="1.1.5",
        datapoint_type="1.001",
        value=True,
        priority="normal",
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.knx.adapter import KnxAdapter
from basis_adapters.knx.mapping import (
    VALID_KNX_ACTIONS,
    VALID_KNX_OPERATIONS,
    VALID_KNX_PRIORITIES,
    VALID_KNX_TEMPLATE_FIELDS,
    KnxMappingConfig,
    KnxOperation,
    KnxRouteMapping,
)

__all__ = [
    "KnxAdapter",
    "KnxMappingConfig",
    "KnxOperation",
    "KnxRouteMapping",
    "VALID_KNX_ACTIONS",
    "VALID_KNX_OPERATIONS",
    "VALID_KNX_PRIORITIES",
    "VALID_KNX_TEMPLATE_FIELDS",
]
