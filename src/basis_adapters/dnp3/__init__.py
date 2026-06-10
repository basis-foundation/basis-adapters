"""
DNP3 adapter for the BASIS ecosystem.

Normalizes DNP3 read and control intents into BASIS authorization requests.
No live DNP3 communication — pure normalization. No master, no outstation,
no protocol stack.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.dnp3 import Dnp3Adapter, Dnp3MappingConfig, Dnp3Operation

    import json

    with open("examples/dnp3/mapping.example.json") as f:
        config = Dnp3MappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="dnp3-primary")
    adapter = Dnp3Adapter(mapping=config, context=ctx)

    op = Dnp3Operation(
        operation="READ",
        outstation_id="os-14",
        point_type="analog_input",
        point_index=3,
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.dnp3.adapter import Dnp3Adapter
from basis_adapters.dnp3.mapping import (
    DNP3_CONTROL_OPERATIONS,
    VALID_DNP3_ACTIONS,
    VALID_DNP3_CONTROL_MODELS,
    VALID_DNP3_OPERATIONS,
    VALID_DNP3_POINT_TYPES,
    VALID_DNP3_TEMPLATE_FIELDS,
    Dnp3MappingConfig,
    Dnp3Operation,
    Dnp3RouteMapping,
)

__all__ = [
    "Dnp3Adapter",
    "Dnp3MappingConfig",
    "Dnp3Operation",
    "Dnp3RouteMapping",
    "DNP3_CONTROL_OPERATIONS",
    "VALID_DNP3_ACTIONS",
    "VALID_DNP3_CONTROL_MODELS",
    "VALID_DNP3_OPERATIONS",
    "VALID_DNP3_POINT_TYPES",
    "VALID_DNP3_TEMPLATE_FIELDS",
]
