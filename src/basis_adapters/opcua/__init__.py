"""
OPC UA adapter for the BASIS ecosystem.

Normalizes OPC UA service requests (Read, Write, Call, Subscribe, Browse)
into BASIS authorization requests. No live OPC UA communication — pure
normalization. No asyncua, no secure channel, no sessions.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.opcua import OpcuaAdapter, OpcuaMappingConfig, OpcuaOperation

    import json

    with open("examples/opcua/mapping.example.json") as f:
        config = OpcuaMappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="opcua-primary")
    adapter = OpcuaAdapter(mapping=config, context=ctx)

    op = OpcuaOperation(
        service="Read",
        node_id="ns=2;s=Building.AHU1.SupplyTemp",
        attribute_id="Value",
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.opcua.adapter import OpcuaAdapter
from basis_adapters.opcua.mapping import (
    VALID_OPCUA_ACTIONS,
    VALID_OPCUA_IDENTIFIER_TYPES,
    VALID_OPCUA_SERVICES,
    VALID_OPCUA_TEMPLATE_FIELDS,
    OpcuaMappingConfig,
    OpcuaOperation,
    OpcuaRouteMapping,
)

__all__ = [
    "OpcuaAdapter",
    "OpcuaMappingConfig",
    "OpcuaOperation",
    "OpcuaRouteMapping",
    "VALID_OPCUA_ACTIONS",
    "VALID_OPCUA_IDENTIFIER_TYPES",
    "VALID_OPCUA_SERVICES",
    "VALID_OPCUA_TEMPLATE_FIELDS",
]
