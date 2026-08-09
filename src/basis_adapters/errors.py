"""
Exception hierarchy for basis-adapters.

Adapters fail closed: any mapping ambiguity or configuration error must raise
rather than silently producing an incorrect normalized request.
"""


class AdapterError(Exception):
    """
    Base exception for all adapter errors.

    Callers should catch this when they want to handle any adapter failure
    without distinguishing between subtypes.
    """


class InvalidMappingError(AdapterError):
    """
    Raised when a mapping configuration is structurally invalid.

    Examples:
    - A route entry is missing required fields.
    - An action value is not a recognized normalized verb.
    - A resource_type value is empty or malformed.

    Adapters must raise this during configuration validation, not at
    normalization time, so misconfigured adapters fail fast on startup.
    """


class UnknownRouteError(AdapterError):
    """
    Raised when an incoming operation does not match any configured route.

    Adapters fail closed: an operation with no matching route must not
    produce a normalized request. The caller is responsible for deciding
    how to handle the refusal (e.g. return 403, log, alert).
    """


# ---------------------------------------------------------------------------
# Adapter evidence construction errors (ADR-0007)
#
# Raised by basis_adapters.evidence.construct_adapter_evidence() and its
# helpers. Centralized here, alongside the rest of the package's exception
# hierarchy, rather than defined in evidence.py itself.
# ---------------------------------------------------------------------------


class EvidenceConstructionError(AdapterError):
    """
    Base exception for all adapter-evidence construction failures.

    Per `basis-architecture`'s adapter evidence construction semantics
    document §11, an evidence-construction failure is never a kernel
    `DENY`, a gateway response, or an authorization result — it happens
    entirely upstream of `basis-gateway` and `basis-core`, before any
    request carrying this evidence is ever assembled. This library's role
    stops at reporting the construction failure; it does not itself decide
    what happens to the underlying operation.

    The library reports the construction failure but does not decide
    whether a deployment may continue without evidence. A future
    operation-producer runtime applies its preselected evidence mode:
    `required` blocks submission, while `optional` may omit evidence only
    when deployment policy explicitly permits omission and records the
    reason auditably. A failure must never silently downgrade required
    evidence into optional omission.
    """


class UnsupportedEvidenceProtocolError(EvidenceConstructionError):
    """
    Raised when the normalized request's protocol has no governed
    `basis-adapter-evidence-v1` metadata projection.

    Today this covers only the nine released protocols
    (`rest`, `bacnet`, `modbus`, `opcua`, `mqtt`, `dnp3`, `iec61850`, `knx`,
    `niagara`); any other protocol label is unsupported by this profile
    version.
    """


class UnexpectedEvidenceFieldError(EvidenceConstructionError):
    """
    Raised when `protocol_evidence.metadata` contains a key that is not on
    the approved projection list for the request's protocol (architecture
    document §4). Unknown keys are rejected, never silently discarded and
    never passed through unexamined.
    """


class ProhibitedEvidenceValueError(EvidenceConstructionError):
    """
    Raised when a field name matching a closed, internal, deterministic
    prohibited-name list is present anywhere in the material being
    constructed, regardless of whether it would otherwise be an approved
    key. Checked, and raised, before any unapproved-key check for the same
    key — a name that is both prohibited and unapproved always raises this,
    never `UnexpectedEvidenceFieldError`. Defense in depth per the
    architecture document §4; not currently reachable via any top-level
    approved key on any of the nine protocols, but reachable through a
    nested object value under an approved key (for example, a nested
    object inside DNP3's or KNX's `value` field).
    """


class EvidenceCanonicalizationError(EvidenceConstructionError):
    """
    Raised when the evidence material violates an RFC 8785 / I-JSON-specific
    constraint — a non-finite float (`NaN`, `+Infinity`, `-Infinity`), an
    integer outside the safe IEEE 754 double-precision domain, a non-string
    object key, invalid Unicode, or any other value the `rfc8785` dependency
    itself rejects. Raised both as a preflight check during evidence-material
    construction (before `rfc8785.dumps()` is ever called) and when
    `rfc8785.dumps()` itself raises — in the latter case, wrapping the
    dependency's own exception so callers depend on a stable
    `basis-adapters` error type rather than a third-party one. A value that
    is simply not a JSON value at all (`bytes`, a `set`, a custom class
    instance) is a different, more general failure — see
    `EvidenceConstructionError`.
    """


class UnsupportedDigestAlgorithmError(EvidenceConstructionError):
    """
    Raised when a caller requests a digest algorithm other than
    `basis_adapters.evidence.DIGEST_ALGORITHM_SHA256`. This module never
    silently falls back to SHA-256 after an unsupported algorithm is
    requested.
    """
