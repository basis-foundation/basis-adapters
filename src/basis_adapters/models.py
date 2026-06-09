"""
Core domain models for basis-adapters.

These models represent the boundary between protocol-specific operations
and the normalized authorization semantics consumed by basis-gateway.

Design invariants:
- Models are immutable (frozen dataclasses).
- No gateway calls, no policy evaluation, no authorization logic here.
- Protocol evidence is always preserved so downstream systems can audit the
  original operation that triggered the authorization request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProtocolOperation:
    """
    A raw operation as received from the wire protocol.

    This is the un-normalized input to an adapter — exactly what the
    protocol delivered, before any interpretation.

    Attributes:
        protocol: Protocol identifier, e.g. "rest", "bacnet", "modbus".
        method: Protocol method or command, e.g. "GET", "read-property".
        path: Resource path or address, e.g. "/devices/ahu-1/points/supply-temp".
        metadata: Additional protocol-specific fields (headers, qualifiers, etc.).
    """

    protocol: str
    method: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedAuthorizationRequest:
    """
    A protocol-agnostic authorization request suitable for submission to basis-gateway.

    Adapters produce this. Gateway consumes it. The adapter must not evaluate
    whether the request should be allowed — that is the gateway's responsibility.

    Attributes:
        action: Normalized action verb, e.g. "read", "write", "control", "discover".
        resource_type: Logical resource category, e.g. "point", "device", "schedule".
        resource_id: Stable identifier for the target resource.
        protocol: Originating protocol, carried through for audit purposes.
        protocol_evidence: The original ProtocolOperation that produced this request.
        subject_hint: Optional identity hint forwarded from the protocol layer.
            The gateway is responsible for resolving and verifying identity.
    """

    action: str
    resource_type: str
    resource_id: str
    protocol: str
    protocol_evidence: ProtocolOperation
    subject_hint: str | None = None


@dataclass(frozen=True)
class AdapterContext:
    """
    Execution context provided to an adapter at normalization time.

    Attributes:
        adapter_id: Logical name of the adapter instance.
        config: Adapter-level configuration (connection settings, defaults, etc.).
    """

    adapter_id: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    """
    The outcome of an adapter normalization attempt.

    Exactly one of `request` or `error` will be set.

    Attributes:
        request: The normalized authorization request, if normalization succeeded.
        error: A human-readable error message, if normalization failed.
        success: True when `request` is set and normalization succeeded.
    """

    request: NormalizedAuthorizationRequest | None
    error: str | None
    success: bool

    @classmethod
    def ok(cls, request: NormalizedAuthorizationRequest) -> AdapterResult:
        """Construct a successful result."""
        return cls(request=request, error=None, success=True)

    @classmethod
    def fail(cls, error: str) -> AdapterResult:
        """Construct a failed result."""
        return cls(request=None, error=error, success=False)
