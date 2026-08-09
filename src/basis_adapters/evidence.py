"""
Adapter evidence material construction, canonicalization, and digesting.

This module implements the `basis-adapters`-owned portion of
`basis-architecture`'s ADR-0007 ("Adapter Evidence Construction") and its
companion specification,
`docs/architecture/adapter-evidence-construction-semantics.md`. It
constructs the governed `basis-adapter-evidence-v1` evidence material from a
successful normalization result, canonicalizes that material under RFC 8785
(the JSON Canonicalization Scheme), and computes a deterministic digest over
the resulting canonical bytes.

Design invariants (restated from the architecture document's governing
invariants, §2):

- **Normalization invariant.** The same valid `AdapterResult` always
  produces the same evidence material, the same canonical bytes, and the
  same digest.
- **Purity invariant.** Construction is deterministic, synchronous, and
  side-effect free: no clocks, no randomness, no UUID generation, no
  environment-variable reads, no network calls, no filesystem access, no
  persistence, and no global mutable state.
- **Ownership invariant.** This module constructs only the facts
  `basis-adapters` itself observed and produced during normalization. It
  does not mint `reference_id`, does not assemble the final
  `AdapterEvidenceReference`, does not select `adapter_source`, does not
  assign `redaction_classification`, does not create request or correlation
  identifiers, does not call `basis-gateway`, does not authenticate a
  producer, and does not execute a protocol operation. Those responsibilities
  belong to the future operation-producer runtime and to `basis-gateway`,
  per the architecture document's construction-ownership matrix (§7).

What a successful result proves, and what it does not prove, are stated
explicitly in the architecture document (§1, §6) and repeated here so a
caller does not have to cross-reference it: a digest proves only
byte-for-byte correspondence between the evidence material and its declared
canonical form under the profile the material itself declares. It does not
prove truthfulness, producer authenticity, authorization, or execution.

See also:
- `docs/contracts/normalization-contract.md` — the per-protocol
  `protocol_evidence.metadata` shapes this module's projection table is
  derived from.
- `docs/contracts/adapter-contract.md` — the `AdapterResult` fail-closed
  contract this module's entry point respects.
- `docs/public-api.md` — the public surface this module's exports are
  documented in.
- `basis_adapters.errors` — this module's exception hierarchy
  (`EvidenceConstructionError` and its subclasses) is defined there,
  alongside the rest of the package's exceptions, and imported here.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

import rfc8785

from basis_adapters.errors import (
    EvidenceCanonicalizationError,
    EvidenceConstructionError,
    ProhibitedEvidenceValueError,
    UnexpectedEvidenceFieldError,
    UnsupportedDigestAlgorithmError,
    UnsupportedEvidenceProtocolError,
)
from basis_adapters.models import AdapterResult, NormalizedAuthorizationRequest, ProtocolOperation

# The exact, closed public surface of this module. No additional public name
# may be added without a corresponding update to docs/public-api.md.
# `_PROHIBITED_METADATA_KEYS` is deliberately not exported — it is an
# implementation detail of the prohibited-field-name check, not a
# compatibility-supported public constant.
__all__ = [
    "EVIDENCE_PROFILE",
    "CANONICALIZATION_PROFILE",
    "DIGEST_ALGORITHM_SHA256",
    "AdapterEvidenceMaterial",
    "EvidenceDigest",
    "ConstructedAdapterEvidence",
    "construct_adapter_evidence",
    # Exceptions re-exported for convenience; canonically defined in
    # basis_adapters.errors.
    "EvidenceConstructionError",
    "UnsupportedEvidenceProtocolError",
    "UnexpectedEvidenceFieldError",
    "ProhibitedEvidenceValueError",
    "EvidenceCanonicalizationError",
    "UnsupportedDigestAlgorithmError",
]

# ---------------------------------------------------------------------------
# Fixed profile constants
# ---------------------------------------------------------------------------

#: The fixed, governed evidence-material profile identifier for this
#: implementation. Carried inside the digested material itself (never
#: derived from the package version, an adapter class name, or any runtime
#: configuration) per the architecture document §4, §9.
EVIDENCE_PROFILE: Final[str] = "basis-adapter-evidence-v1"

#: The fixed, governed canonicalization-profile identifier. RFC 8785 (the
#: JSON Canonicalization Scheme) is adopted exactly, per the architecture
#: document §5 — not a candidate awaiting a future technology evaluation.
CANONICALIZATION_PROFILE: Final[str] = "rfc8785"

#: The recommended initial digest algorithm label, per the architecture
#: document §6. The `evidence_digest_shape` vocabulary this label belongs to
#: is open (an algorithm label plus a lowercase-hexadecimal value); this
#: module supports only this one algorithm today and rejects any other
#: requested label explicitly rather than silently falling back to it.
DIGEST_ALGORITHM_SHA256: Final[str] = "sha-256"

# ---------------------------------------------------------------------------
# Governed per-protocol metadata projection
# ---------------------------------------------------------------------------
#
# This table reproduces, exactly, the approved `protocol_evidence.metadata`
# key sets documented in `basis-architecture`'s
# `docs/architecture/adapter-evidence-construction-semantics.md` §4, which
# themselves reproduce, exactly, the per-protocol metadata fields already
# documented in `docs/contracts/normalization-contract.md`. It does not
# invent a new key for any protocol. Only keys in this table may be
# projected into digested evidence material for a given protocol; every
# other metadata key present on a `ProtocolOperation` causes construction to
# fail (see `_project_protocol_evidence`).
#
# REST is the deliberate, documented exception: its `metadata` shape is
# open-ended (`docs/contracts/normalization-contract.md`: "may include
# `subject_hint` and any other HTTP-level fields"), so no closed key
# vocabulary can be honestly declared for it under this profile version.
# Rather than fail evidence construction for every real REST operation, the
# REST projection carries `protocol`, `method`, and `path` only — its
# `metadata` projection is always the empty object, regardless of what the
# source `ProtocolOperation.metadata` contains. This is a known, honest
# limitation of the first profile (architecture document §4), not a defect
# to route around silently.
_APPROVED_METADATA_KEYS: Final[dict[str, frozenset[str]]] = {
    "rest": frozenset(),
    "bacnet": frozenset(
        {
            "service",
            "object_type",
            "object_instance",
            "property_identifier",
            "device_id",
            "priority",
            "value_present",
        }
    ),
    "modbus": frozenset(
        {
            "function",
            "unit_id",
            "address",
            "quantity",
            "value_present",
            "register_type",
            "source_address",
            "transaction_id",
        }
    ),
    "opcua": frozenset(
        {
            "service",
            "node_id",
            "attribute_id",
            "method_id",
            "namespace_index",
            "identifier",
            "identifier_type",
            "browse_name",
            "parent_node_id",
            "subscription_id",
            "monitored_item_id",
            "value_present",
            "endpoint_url",
            "session_id",
        }
    ),
    "mqtt": frozenset(
        {
            "operation",
            "topic",
            "client_id",
            "qos",
            "retain",
            "payload_type",
            "protocol_version",
        }
    ),
    "dnp3": frozenset(
        {
            "operation",
            "source_address",
            "destination_address",
            "outstation_id",
            "master_id",
            "object_group",
            "variation",
            "point_index",
            "point_type",
            "function_code",
            "qualifier",
            "control_code",
            "control_model",
            "event_class",
            "value",
        }
    ),
    "iec61850": frozenset(
        {
            "operation",
            "ied_name",
            "logical_device",
            "logical_node",
            "data_object",
            "data_attribute",
            "functional_constraint",
            "dataset",
            "report_control_block",
            "goose_control_block",
            "sampled_values_control_block",
            "control_model",
            "origin",
            "cause",
            "quality",
            "timestamp",
            "value",
        }
    ),
    "knx": frozenset(
        {
            "operation",
            "group_address",
            "individual_address",
            "device_address",
            "communication_object",
            "datapoint_type",
            "payload_type",
            "value",
            "priority",
            "area",
            "line",
            "device",
        }
    ),
    "niagara": frozenset(
        {
            "operation",
            "station",
            "host",
            "ord",
            "component",
            "slot",
            "point",
            "point_type",
            "value",
            "facet",
            "schedule",
            "alarm",
            "history",
            "category",
            "baja_type",
            "nav_path",
            "niagara_user",
            "niagara_role",
        }
    ),
}

# A closed, deterministic set of field names that are never permitted to
# appear anywhere in projected evidence material, regardless of whether they
# would otherwise be an approved key for the given protocol. No currently
# documented approved key uses any of these names (confirmed against
# `_APPROVED_METADATA_KEYS` above) — this is defense in depth against a
# future mapping error, per the architecture document §4, not a response to
# a known present defect. This is a deterministic, name-based rule, not
# heuristic content scanning: the architecture document is explicit that a
# "secret-shaped value" is not a deterministic, implementable rule beyond
# the closed approved-key projection above, and this module does not invent
# one. The approved-key projection remains the primary safety boundary.
#
# This is an implementation detail, not a compatibility-supported public
# constant: it is intentionally not exported in `__all__` or from the
# package root. A caller who needs to know whether a given field name is
# prohibited should rely on `construct_adapter_evidence` raising
# `ProhibitedEvidenceValueError`, not on introspecting this set directly.
_PROHIBITED_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "passwords",
        "credential",
        "credentials",
        "authorization",
        "authorization_header",
        "auth_header",
        "access_token",
        "access_tokens",
        "refresh_token",
        "refresh_tokens",
        "api_key",
        "api_keys",
        "apikey",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "client_secret",
        "session_secret",
        "device_secret",
        "unredacted_device_secret",
        "token",
        "tokens",
        "bearer_token",
    }
)

# The safe-integer domain RFC 8785 requires (every number representable
# exactly as an IEEE 754 double). Mirrors rfc8785's own internal bound so
# integers outside this range fail evidence-material construction (a
# construction-time failure) rather than surfacing only as a later,
# harder-to-diagnose canonicalization failure.
_SAFE_INT_MAX: Final[int] = 2**53 - 1
_SAFE_INT_MIN: Final[int] = -_SAFE_INT_MAX


# ---------------------------------------------------------------------------
# Public models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceDigest:
    """
    A digest computed over the canonical bytes of an `AdapterEvidenceMaterial`.

    Structurally identical to the published `evidence-digest` shape
    (an open, lowercase, kebab-case algorithm label plus a lowercase
    hexadecimal value) both `adapter-evidence-reference` and
    `identity-evidence-reference` already use — this module does not
    redefine that representation.

    Attributes:
        algorithm: The digest algorithm label, e.g. `"sha-256"`.
        value: The lowercase hexadecimal digest value.
    """

    algorithm: str
    value: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to the plain `evidence_digest_shape`-compatible dict."""
        return {"algorithm": self.algorithm, "value": self.value}


@dataclass(frozen=True)
class AdapterEvidenceMaterial:
    """
    The governed `basis-adapter-evidence-v1` evidence material.

    This is the exact structure that is canonicalized and digested — never
    a superset, never a partial subset chosen ad hoc. It carries only the
    concepts the architecture document approves for this profile: its own
    profile identity, selected normalized facts, and a governed projection
    of protocol evidence. It deliberately excludes `subject_hint`,
    `reference_id`, `adapter_source`, `redaction_classification`,
    `request_id`, `correlation_id`, timestamps, random values, and any
    gateway-, kernel-, or execution-owned fact — see the architecture
    document §4 for the full exclusion list this shape honors.

    `protocol_evidence` is retained as a **recursively immutable**
    structure: the top-level mapping, its `metadata` mapping, every nested
    mapping, and every nested array are read-only (`types.MappingProxyType`
    and `tuple`, respectively). No caller can mutate any part of the
    retained material through any reference to it. `to_dict()` returns a
    fresh, ordinary, mutable `dict`/`list` structure on every call — mutating
    that returned structure can never affect this material, its canonical
    bytes, or its digest.

    Attributes:
        evidence_profile: Always `EVIDENCE_PROFILE`.
        canonicalization_profile: Always `CANONICALIZATION_PROFILE`.
        protocol: The originating protocol label, from
            `NormalizedAuthorizationRequest.protocol`.
        action: The normalized action verb, from
            `NormalizedAuthorizationRequest.action`.
        resource_type: The local resource category, from
            `NormalizedAuthorizationRequest.resource_type`.
        resource_id: The local resource identifier, from
            `NormalizedAuthorizationRequest.resource_id`.
        protocol_evidence: The governed protocol-evidence projection — an
            immutable mapping with exactly `protocol`, `method`, `path`, and
            `metadata` keys, where `metadata` contains only the approved
            keys for `protocol` (see `_APPROVED_METADATA_KEYS`), recursively
            immutable throughout.
    """

    evidence_profile: str
    canonicalization_profile: str
    protocol: str
    action: str
    resource_type: str
    resource_id: str
    protocol_evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to a fresh, ordinary, JSON-compatible dict (using `dict`
        and `list`, never `MappingProxyType` or `tuple`) that is
        canonicalized and digested. Returns a fresh deep copy on every
        call — mutating the returned structure never affects this material,
        its canonical bytes, or its digest.
        """
        return {
            "evidence_profile": self.evidence_profile,
            "canonicalization_profile": self.canonicalization_profile,
            "protocol": self.protocol,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "protocol_evidence": _deep_copy_plain(self.protocol_evidence),
        }


@dataclass(frozen=True)
class ConstructedAdapterEvidence:
    """
    The deterministic result of `construct_adapter_evidence`.

    Attributes:
        material: The governed `AdapterEvidenceMaterial`.
        canonical_bytes: The exact RFC 8785 canonical bytes produced from
            `material.to_dict()`. This is what `digest` was computed over.
        digest: The `EvidenceDigest` computed over `canonical_bytes`.
    """

    material: AdapterEvidenceMaterial
    canonical_bytes: bytes
    digest: EvidenceDigest


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def construct_adapter_evidence(
    result: AdapterResult,
    *,
    digest_algorithm: str = DIGEST_ALGORITHM_SHA256,
) -> ConstructedAdapterEvidence:
    """
    Construct governed adapter evidence material, canonicalize it under RFC
    8785, and compute its digest.

    This is a pure, deterministic, side-effect-free function: the same
    accepted `result` and `digest_algorithm` always produce the same
    `AdapterEvidenceMaterial`, the same canonical bytes, and the same
    digest, across repeated calls and process restarts. It reads no clock,
    generates no random or UUID value, reads no environment variable,
    performs no network or filesystem access, and mutates neither `result`
    nor anything reachable from it.

    This function does not mint `reference_id`, does not select
    `adapter_source`, does not assign `redaction_classification`, does not
    create request or correlation identifiers, does not call
    `basis-gateway`, does not authenticate a producer, and does not
    assemble a final `AdapterEvidenceReference`. Those remain
    operation-producer-runtime responsibilities per
    `basis-architecture`'s ADR-0007.

    Args:
        result: A normalization outcome from any of this package's nine
            adapters. Must satisfy `result.success` with a non-`None`
            `result.request`.
        digest_algorithm: The digest algorithm label to compute. Only
            `DIGEST_ALGORITHM_SHA256` ("sha-256") is supported today; any
            other value raises `UnsupportedDigestAlgorithmError` rather than
            silently falling back to SHA-256.

    Returns:
        A `ConstructedAdapterEvidence` carrying the governed material, its
        canonical bytes, and its digest.

    Raises:
        UnsupportedDigestAlgorithmError: `digest_algorithm` is not
            `DIGEST_ALGORITHM_SHA256`.
        EvidenceConstructionError: `result` is absent, was not successful,
            carries no request, or the request is otherwise structurally
            invalid (a non-string or empty `action`/`resource_type`/
            `resource_id`, a `protocol` that disagrees with
            `protocol_evidence.protocol`, a non-`ProtocolOperation`
            `protocol_evidence`, a non-`dict` `protocol_evidence.metadata`,
            or a value of an unsupported Python type that is not a JSON
            value at all — for example `bytes`, a `set`, or a custom class
            instance).
        UnsupportedEvidenceProtocolError: the request's protocol has no
            governed metadata projection.
        UnexpectedEvidenceFieldError: `protocol_evidence.metadata` contains
            a key outside the approved projection list for the protocol.
        ProhibitedEvidenceValueError: a prohibited field name is present
            anywhere in the material being constructed — checked, and
            raised, before any unapproved-key check for the same key.
        EvidenceCanonicalizationError: an RFC 8785 / I-JSON-specific
            constraint is violated — a non-finite float, an integer outside
            the safe double-precision domain, a non-string object key,
            invalid Unicode, or any other constraint the `rfc8785`
            dependency itself rejects. Raised both as a preflight check
            during material construction and when `rfc8785.dumps()` itself
            rejects the material.
    """
    if digest_algorithm != DIGEST_ALGORITHM_SHA256:
        raise UnsupportedDigestAlgorithmError(
            f"unsupported digest algorithm {digest_algorithm!r}; "
            f"only {DIGEST_ALGORITHM_SHA256!r} is supported"
        )

    normalized = _require_successful_request(result)
    material = _build_material(normalized)
    canonical_bytes = _canonicalize(material.to_dict())
    digest = EvidenceDigest(
        algorithm=digest_algorithm,
        value=hashlib.sha256(canonical_bytes).hexdigest(),
    )
    return ConstructedAdapterEvidence(
        material=material,
        canonical_bytes=canonical_bytes,
        digest=digest,
    )


def _require_successful_request(result: AdapterResult) -> NormalizedAuthorizationRequest:
    """Validate that `result` represents a successful normalization outcome."""
    if not isinstance(result, AdapterResult):
        raise EvidenceConstructionError(f"expected an AdapterResult, got {type(result).__name__}")
    if not result.success or result.request is None:
        raise EvidenceConstructionError(
            "cannot construct adapter evidence from an unsuccessful normalization result; "
            "the caller must fail closed instead of forwarding this operation"
        )
    normalized = result.request
    if not isinstance(normalized, NormalizedAuthorizationRequest):
        raise EvidenceConstructionError(
            f"expected a NormalizedAuthorizationRequest, got {type(normalized).__name__}"
        )
    if not isinstance(normalized.protocol_evidence, ProtocolOperation):
        raise EvidenceConstructionError(
            "normalized request carries no protocol_evidence; "
            "adapter evidence cannot be constructed without it"
        )
    return normalized


def _build_material(normalized: NormalizedAuthorizationRequest) -> AdapterEvidenceMaterial:
    """Build the governed `AdapterEvidenceMaterial` from a normalized request."""
    protocol = _require_nonempty_str(normalized.protocol, field_name="protocol")
    action = _require_nonempty_str(normalized.action, field_name="action")
    resource_type = _require_nonempty_str(normalized.resource_type, field_name="resource_type")
    resource_id = _require_nonempty_str(normalized.resource_id, field_name="resource_id")

    evidence = normalized.protocol_evidence
    evidence_protocol = _require_nonempty_str(
        evidence.protocol, field_name="protocol_evidence.protocol"
    )
    if evidence_protocol != protocol:
        raise EvidenceConstructionError(
            f"structurally invalid request: protocol {protocol!r} disagrees with "
            f"protocol_evidence.protocol {evidence_protocol!r}"
        )
    method = _require_nonempty_str(evidence.method, field_name="protocol_evidence.method")
    path = _require_nonempty_str(evidence.path, field_name="protocol_evidence.path")

    protocol_evidence_projection = _project_protocol_evidence(
        protocol=protocol, method=method, path=path, metadata=evidence.metadata
    )

    return AdapterEvidenceMaterial(
        evidence_profile=EVIDENCE_PROFILE,
        canonicalization_profile=CANONICALIZATION_PROFILE,
        protocol=protocol,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        protocol_evidence=protocol_evidence_projection,
    )


def _project_protocol_evidence(
    *, protocol: str, method: str, path: str, metadata: dict[str, Any]
) -> Mapping[str, Any]:
    """
    Build the governed protocol-evidence projection: `protocol`, `method`,
    `path`, and only the approved metadata keys for `protocol`.

    Never mutates `metadata`; the returned mapping is an independent,
    freshly-constructed, deep-validated, and recursively immutable copy
    (see `_freeze_json_value`).

    Check order for non-REST protocols, deliberately: prohibited field
    names are checked first, *regardless* of whether the key is otherwise
    approved — matching the architecture document's "prohibited values are
    rejected regardless of key name" rule (§4) — and only afterward are the
    remaining keys checked against the approved-key list. A key that is
    both prohibited and unapproved therefore always raises
    `ProhibitedEvidenceValueError`, never `UnexpectedEvidenceFieldError`.
    """
    approved_keys = _APPROVED_METADATA_KEYS.get(protocol)
    if approved_keys is None:
        raise UnsupportedEvidenceProtocolError(
            f"protocol {protocol!r} has no governed {EVIDENCE_PROFILE} metadata projection"
        )

    if not isinstance(metadata, dict):
        raise EvidenceConstructionError(
            f"protocol_evidence.metadata must be a dict, got {type(metadata).__name__}"
        )

    # REST is the deliberate, documented exception: its metadata is never
    # projected under this profile version, regardless of content. See the
    # module-level comment above `_APPROVED_METADATA_KEYS`.
    if protocol == "rest":
        projected_metadata: Mapping[str, Any] = MappingProxyType({})
    else:
        prohibited_present = sorted(key for key in metadata if key in _PROHIBITED_METADATA_KEYS)
        if prohibited_present:
            raise ProhibitedEvidenceValueError(
                f"protocol {protocol!r}: metadata key(s) are prohibited field names: "
                f"{prohibited_present}"
            )

        unknown_keys = set(metadata.keys()) - approved_keys
        if unknown_keys:
            raise UnexpectedEvidenceFieldError(
                f"protocol {protocol!r}: metadata key(s) not approved for "
                f"{EVIDENCE_PROFILE} projection: {sorted(unknown_keys)}"
            )

        frozen_metadata: dict[str, Any] = {}
        for key in metadata:
            frozen_metadata[key] = _freeze_json_value(metadata[key], path=f"metadata.{key}")
        projected_metadata = MappingProxyType(frozen_metadata)

    return MappingProxyType(
        {
            "protocol": protocol,
            "method": method,
            "path": path,
            "metadata": projected_metadata,
        }
    )


def _require_nonempty_str(value: Any, *, field_name: str) -> str:
    """Validate that `value` is a non-empty string."""
    if not isinstance(value, str) or not value:
        raise EvidenceConstructionError(
            f"structurally invalid request: {field_name} must be a non-empty string, got {value!r}"
        )
    return value


def _freeze_json_value(value: Any, *, path: str) -> Any:
    """
    Validate that `value` is I-JSON-conformant (recursively) and return an
    independent, recursively immutable value: nested `dict`s become
    `types.MappingProxyType` and nested `list`/`tuple`s become `tuple`, so
    nothing reachable from the returned value can be mutated by a caller.

    Exception categories, matching the architecture document's RFC 8785 /
    I-JSON constraints (§5) versus its general unsupported-value handling:

    - `EvidenceCanonicalizationError`: the value fails a constraint that is
      specifically RFC 8785 / I-JSON-shaped — a non-finite float (`NaN`,
      `+Infinity`, `-Infinity`), an integer outside the safe IEEE 754
      double-precision domain, or a non-string object key. These are
      preflight checks for constraints `rfc8785.dumps()` would otherwise
      reject itself; raising the same error type here as `_canonicalize`
      does keeps both preflight and dependency-surfaced RFC 8785 failures
      under one stable category.
    - `ProhibitedEvidenceValueError`: a prohibited field name (defense in
      depth; see `_PROHIBITED_METADATA_KEYS`).
    - `EvidenceConstructionError`: any other unsupported Python value that
      is not a JSON value at all — for example `bytes`, a `set`, or a
      custom class instance. This is a structural-input failure, not an
      RFC 8785 constraint.

    Accepted, returned-as-is or recursively frozen types: `str`, `bool`,
    `int` (within the safe domain), `float` (finite only), `None`,
    `list`/`tuple` (frozen to `tuple`), and `dict` with string keys (frozen
    to `MappingProxyType`).
    """
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        # bool must be checked before int (bool is an int subclass).
        return value
    if isinstance(value, int):
        if value < _SAFE_INT_MIN or value > _SAFE_INT_MAX:
            raise EvidenceCanonicalizationError(
                f"{path}: integer {value} exceeds the safe IEEE 754 double-precision "
                f"domain required by RFC 8785"
            )
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise EvidenceCanonicalizationError(
                f"{path}: non-finite float values are not supported by RFC 8785"
            )
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item, path=f"{path}[{i}]") for i, item in enumerate(value))
    if isinstance(value, dict):
        frozen: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise EvidenceCanonicalizationError(
                    f"{path}: object keys must be strings, got {type(key).__name__}"
                )
            if key in _PROHIBITED_METADATA_KEYS:
                raise ProhibitedEvidenceValueError(f"{path}.{key}: prohibited field name")
            frozen[key] = _freeze_json_value(nested, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    raise EvidenceConstructionError(f"{path}: unsupported value type {type(value).__name__}")


def _deep_copy_plain(value: Any) -> Any:
    """
    Return a fresh, ordinary, JSON-compatible (`dict`/`list`) deep copy of
    an already-validated, possibly-frozen value. Unfreezes any
    `MappingProxyType`/`tuple` structure produced by `_freeze_json_value`
    back into plain `dict`/`list` — the shape `to_dict()` and the RFC 8785
    canonicalizer both expect. Never returns a value sharing any mutable
    container with its input.
    """
    if isinstance(value, Mapping):
        return {key: _deep_copy_plain(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_deep_copy_plain(item) for item in value]
    return value


def _canonicalize(material_dict: dict[str, Any]) -> bytes:
    """
    Canonicalize `material_dict` under RFC 8785 using the `rfc8785`
    dependency, translating any canonicalization failure into a stable
    `basis-adapters` error type rather than exposing the dependency's own
    exception as the only public failure contract.
    """
    try:
        return rfc8785.dumps(material_dict)
    except rfc8785.CanonicalizationError as exc:
        raise EvidenceCanonicalizationError(str(exc)) from exc
