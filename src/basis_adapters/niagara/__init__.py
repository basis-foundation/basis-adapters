"""
Niagara adapter for the BASIS ecosystem.

Normalizes representative Niagara platform operations — component/point/slot/
history/alarm/schedule reads, point and slot writes, schedule updates, alarm
acknowledgements, action invocations, point commands, overrides and releases,
station browsing and ORD resolution, and point/alarm/history subscriptions —
into BASIS authorization requests. No live Niagara communication — pure
normalization. No Fox/Foxs client, no Baja runtime, no Haystack client, no
REST connector, no station/supervisor/JACE connectivity, no packet parsing,
no Niagara permission system.

Usage::

    from basis_adapters.models import AdapterContext
    from basis_adapters.niagara import (
        NiagaraAdapter,
        NiagaraMappingConfig,
        NiagaraOperation,
    )

    import json

    with open("examples/niagara/mapping.example.json") as f:
        config = NiagaraMappingConfig.from_dict(json.load(f))

    ctx = AdapterContext(adapter_id="niagara-primary")
    adapter = NiagaraAdapter(mapping=config, context=ctx)

    op = NiagaraOperation(
        operation="READ_POINT",
        station="station-east",
        point="AHU1-SupplyTemp",
        point_type="NumericPoint",
        baja_type="control:NumericPoint",
    )

    result = adapter.normalize(op)
    if result.success:
        req = result.request
        # Submit req to basis-gateway
    else:
        # Fail closed — do not forward the operation
        pass
"""

from basis_adapters.niagara.adapter import NiagaraAdapter
from basis_adapters.niagara.mapping import (
    VALID_NIAGARA_ACTIONS,
    VALID_NIAGARA_OPERATIONS,
    VALID_NIAGARA_TEMPLATE_FIELDS,
    NiagaraMappingConfig,
    NiagaraOperation,
    NiagaraRouteMapping,
)

__all__ = [
    "NiagaraAdapter",
    "NiagaraMappingConfig",
    "NiagaraOperation",
    "NiagaraRouteMapping",
    "VALID_NIAGARA_ACTIONS",
    "VALID_NIAGARA_OPERATIONS",
    "VALID_NIAGARA_TEMPLATE_FIELDS",
]
