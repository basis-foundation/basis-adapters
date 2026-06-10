"""
Modbus adapter for the BASIS ecosystem.

Normalizes Modbus function requests (ReadHoldingRegisters, WriteSingleRegister,
WriteMultipleRegisters, and related functions) into BASIS authorization requests.
No live Modbus TCP communication — pure normalization.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.modbus import ModbusAdapter, ModbusMappingConfig, ModbusOperation

    import json

    with open("examples/modbus/mapping.example.json") as f:
        config = ModbusMappingConfig.from_dict(json.load(f))

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
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.modbus.adapter import ModbusAdapter
from basis_adapters.modbus.mapping import (
    VALID_MODBUS_FUNCTIONS,
    VALID_MODBUS_TEMPLATE_FIELDS,
    ModbusMappingConfig,
    ModbusOperation,
    ModbusRouteMapping,
)

__all__ = [
    "ModbusAdapter",
    "ModbusMappingConfig",
    "ModbusOperation",
    "ModbusRouteMapping",
    "VALID_MODBUS_FUNCTIONS",
    "VALID_MODBUS_TEMPLATE_FIELDS",
]
