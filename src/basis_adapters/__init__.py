"""
basis-adapters: Protocol adapters that normalize operations into BASIS authorization semantics.

Adapters normalize. Gateway enforces. Kernel evaluates.
"""

from basis_adapters.errors import (
    AdapterError,
    InvalidMappingError,
    UnknownRouteError,
)
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)

__all__ = [
    # Models
    "ProtocolOperation",
    "NormalizedAuthorizationRequest",
    "AdapterContext",
    "AdapterResult",
    # Errors
    "AdapterError",
    "InvalidMappingError",
    "UnknownRouteError",
]
