"""
basis-adapters: Protocol adapters that normalize operations into BASIS authorization semantics.

Adapters normalize. Gateway enforces. Kernel evaluates.
"""

from basis_adapters.errors import (
    AdapterError,
    EvidenceCanonicalizationError,
    EvidenceConstructionError,
    InvalidMappingError,
    ProhibitedEvidenceValueError,
    UnexpectedEvidenceFieldError,
    UnknownRouteError,
    UnsupportedDigestAlgorithmError,
    UnsupportedEvidenceProtocolError,
)
from basis_adapters.evidence import (
    CANONICALIZATION_PROFILE,
    DIGEST_ALGORITHM_SHA256,
    EVIDENCE_PROFILE,
    AdapterEvidenceMaterial,
    ConstructedAdapterEvidence,
    EvidenceDigest,
    construct_adapter_evidence,
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
    "EvidenceConstructionError",
    "UnsupportedEvidenceProtocolError",
    "UnexpectedEvidenceFieldError",
    "ProhibitedEvidenceValueError",
    "EvidenceCanonicalizationError",
    "UnsupportedDigestAlgorithmError",
    # Adapter evidence construction (ADR-0007)
    "EVIDENCE_PROFILE",
    "CANONICALIZATION_PROFILE",
    "DIGEST_ALGORITHM_SHA256",
    "AdapterEvidenceMaterial",
    "EvidenceDigest",
    "ConstructedAdapterEvidence",
    "construct_adapter_evidence",
]
