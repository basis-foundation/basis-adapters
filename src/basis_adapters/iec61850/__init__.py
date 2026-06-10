"""
IEC 61850 adapter for the BASIS ecosystem.

Normalizes IEC 61850 read, write, control, and reporting/GOOSE/Sampled Values
intents into BASIS authorization requests. No live IEC 61850 communication —
pure normalization. No MMS stack, no GOOSE subscriber, no Sampled Values
processor, no client/server association.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.iec61850 import (
        Iec61850Adapter,
        Iec61850MappingConfig,
        Iec61850Operation,
    )

    import json

    with open("examples/iec61850/mapping.example.json") as f:
        config = Iec61850MappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="iec61850-primary")
    adapter = Iec61850Adapter(mapping=config, context=ctx)

    op = Iec61850Operation(
        operation="READ",
        ied_name="ied-sub1",
        logical_device="PROT",
        logical_node="MMXU1",
        data_object="TotW",
        data_attribute="mag",
        functional_constraint="MX",
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.iec61850.adapter import Iec61850Adapter
from basis_adapters.iec61850.mapping import (
    IEC61850_CONTROL_OPERATIONS,
    IEC61850_DIRECT_CONTROL_MODELS,
    IEC61850_SBO_CONTROL_MODELS,
    IEC61850_SUBSCRIPTION_OPERATIONS,
    VALID_IEC61850_ACTIONS,
    VALID_IEC61850_CONTROL_MODELS,
    VALID_IEC61850_FUNCTIONAL_CONSTRAINTS,
    VALID_IEC61850_OPERATIONS,
    VALID_IEC61850_TEMPLATE_FIELDS,
    Iec61850MappingConfig,
    Iec61850Operation,
    Iec61850RouteMapping,
)

__all__ = [
    "Iec61850Adapter",
    "Iec61850MappingConfig",
    "Iec61850Operation",
    "Iec61850RouteMapping",
    "IEC61850_CONTROL_OPERATIONS",
    "IEC61850_DIRECT_CONTROL_MODELS",
    "IEC61850_SBO_CONTROL_MODELS",
    "IEC61850_SUBSCRIPTION_OPERATIONS",
    "VALID_IEC61850_ACTIONS",
    "VALID_IEC61850_CONTROL_MODELS",
    "VALID_IEC61850_FUNCTIONAL_CONSTRAINTS",
    "VALID_IEC61850_OPERATIONS",
    "VALID_IEC61850_TEMPLATE_FIELDS",
]
