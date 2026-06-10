"""
Cross-protocol normalization contract tests — Phase 4.

These tests prove that:
1. REST normalized requests serialize to the canonical shape.
2. BACnet normalized requests serialize to the canonical shape.
3. Required fields are present for both protocols.
4. Protocol-specific evidence is nested under "protocol_evidence".
5. No authorization decision field is present in the output.
6. No resolved subject identity field is present (only the unverified hint).
7. No gateway transport code is invoked.
8. No basis_core import exists anywhere in basis_adapters.
9. REST and BACnet outputs share exactly the same top-level field set.
10. Serialization is deterministic.

The contract document is: docs/contracts/normalization-contract.md
The JSON Schema is: schemas/normalized-authorization-request.schema.json
"""

from __future__ import annotations

import json
import sys
from typing import Any

from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import BacnetMappingConfig, BacnetOperation, BacnetRouteMapping
from basis_adapters.models import (
    AdapterContext,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.rest.adapter import RestAdapter
from basis_adapters.rest.mapping import RestMappingConfig, RouteMapping

# ---------------------------------------------------------------------------
# Canonical field set — the contract defines exactly these top-level keys.
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)

CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})

# Fields that must never appear in the serialized output.
FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        # Decision fields — adapters do not produce decisions
        "decision",
        "allow",
        "deny",
        "permitted",
        "authorized",
        "result",
        # Verified identity — the gateway owns identity resolution
        "subject",
        "principal",
        "identity",
        "user_id",
        "verified_subject",
    }
)


# ---------------------------------------------------------------------------
# Fixtures — minimal but realistic adapter configurations
# ---------------------------------------------------------------------------


def _rest_adapter() -> RestAdapter:
    route = RouteMapping(
        methods=["GET", "HEAD"],
        path_pattern="/devices/{device_id}/points/{point_id}",
        resource_type="point",
        resource_id_template="devices/{device_id}/points/{point_id}",
        name="read-point",
    )
    config = RestMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="rest-normalization-test")
    return RestAdapter(mapping=config, context=ctx)


def _rest_operation(subject_hint: str | None = None) -> ProtocolOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return ProtocolOperation(
        protocol="rest",
        method="GET",
        path="/devices/ahu-1/points/supply-temp",
        metadata=meta,
    )


def _bacnet_adapter() -> BacnetAdapter:
    route = BacnetRouteMapping(
        service="ReadProperty",
        object_type="analogInput",
        property_identifier="presentValue",
        action="read",
        resource_type="point",
        resource_id_template="device-{device_id}/point/{object_type}:{object_instance}:{property_identifier}",
        name="read-analog-point",
    )
    config = BacnetMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="bacnet-normalization-test")
    return BacnetAdapter(mapping=config, context=ctx)


def _bacnet_operation(subject_hint: str | None = None) -> BacnetOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return BacnetOperation(
        service="ReadProperty",
        object_type="analogInput",
        object_instance=1,
        property_identifier="presentValue",
        device_id="device-42",
        metadata=meta,
    )


def _rest_normalized() -> NormalizedAuthorizationRequest:
    adapter = _rest_adapter()
    result = adapter.normalize(_rest_operation())
    assert result.success, f"REST normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _bacnet_normalized() -> NormalizedAuthorizationRequest:
    adapter = _bacnet_adapter()
    result = adapter.normalize(_bacnet_operation())
    assert result.success, f"BACnet normalization failed: {result.error}"
    assert result.request is not None
    return result.request


# ---------------------------------------------------------------------------
# 1. REST serializes to canonical shape
# ---------------------------------------------------------------------------


class TestRestCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _rest_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_rest(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol"] == "rest"

    def test_action_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _rest_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _rest_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_is_dict(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["protocol_evidence"]["metadata"], dict)

    def test_no_forbidden_fields(self) -> None:
        d = _rest_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in REST output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _rest_adapter()
        result = adapter.normalize(_rest_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _rest_normalized().to_dict()
        # Should not raise
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 2. BACnet serializes to canonical shape
# ---------------------------------------------------------------------------


class TestBacnetCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_bacnet(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol"] == "bacnet"

    def test_action_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_bacnet_fields(self) -> None:
        d = _bacnet_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "service" in meta
        assert "object_type" in meta
        assert "object_instance" in meta
        assert "property_identifier" in meta
        assert "device_id" in meta
        assert "priority" in meta
        assert "value_present" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _bacnet_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in BACnet output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _bacnet_adapter()
        result = adapter.normalize(_bacnet_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _bacnet_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 3. REST and BACnet share the same canonical field set
# ---------------------------------------------------------------------------


class TestCrossProtocolFieldSetParity:
    def test_top_level_field_sets_are_identical(self) -> None:
        rest_keys = set(_rest_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        rest_only = rest_keys - bacnet_keys
        bacnet_only = bacnet_keys - rest_keys
        assert rest_keys == bacnet_keys, (
            f"Field set mismatch:\n  REST-only: {rest_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_evidence_field_sets_are_identical(self) -> None:
        rest_ev = set(_rest_normalized().to_dict()["protocol_evidence"].keys())
        bacnet_ev = set(_bacnet_normalized().to_dict()["protocol_evidence"].keys())
        rest_only = rest_ev - bacnet_ev
        bacnet_only = bacnet_ev - rest_ev
        assert rest_ev == bacnet_ev, (
            f"Evidence field set mismatch:\n  REST-only: {rest_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_both_protocols_have_correct_protocol_field(self) -> None:
        assert _rest_normalized().to_dict()["protocol"] == "rest"
        assert _bacnet_normalized().to_dict()["protocol"] == "bacnet"

    def test_both_protocols_produce_same_action_for_read(self) -> None:
        # Both adapters are configured to produce "read" for their respective read operations.
        assert _rest_normalized().to_dict()["action"] == "read"
        assert _bacnet_normalized().to_dict()["action"] == "read"

    def test_both_protocols_produce_same_resource_type(self) -> None:
        assert _rest_normalized().to_dict()["resource_type"] == "point"
        assert _bacnet_normalized().to_dict()["resource_type"] == "point"


# ---------------------------------------------------------------------------
# 4. Serialization is deterministic
# ---------------------------------------------------------------------------


class TestSerializationDeterminism:
    def test_rest_deterministic_across_calls(self) -> None:
        r = _rest_normalized()
        assert r.to_dict() == r.to_dict()

    def test_bacnet_deterministic_across_calls(self) -> None:
        r = _bacnet_normalized()
        assert r.to_dict() == r.to_dict()

    def test_rest_deterministic_across_instances(self) -> None:
        r1 = _rest_normalized()
        r2 = _rest_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_bacnet_deterministic_across_instances(self) -> None:
        r1 = _bacnet_normalized()
        r2 = _bacnet_normalized()
        assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# 5. Isolation — no basis_core import, no gateway transport
# ---------------------------------------------------------------------------


class TestAdapterIsolation:
    def test_basis_adapters_does_not_import_basis_core(self) -> None:
        """basis_adapters must never import basis_core — confirmed by import check."""
        # basis_adapters submodules are already loaded by top-level imports above.
        modules = [name for name in sys.modules if name.startswith("basis_adapters")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_basis_adapters_does_not_import_basis_gateway(self) -> None:
        """basis_adapters must never import basis_gateway — confirmed by import check."""
        # basis_adapters submodules are already loaded by top-level imports above.
        modules = [name for name in sys.modules if name.startswith("basis_adapters")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_normalized_request_to_dict_does_not_call_network(self) -> None:
        """to_dict() is a pure in-memory operation — no side effects."""
        import socket

        original_getaddrinfo = socket.getaddrinfo

        calls: list[tuple[Any, ...]] = []

        def spy_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            return original_getaddrinfo(*args, **kwargs)

        socket.getaddrinfo = spy_getaddrinfo  # type: ignore[method-assign]
        try:
            _rest_normalized().to_dict()
            _bacnet_normalized().to_dict()
        finally:
            socket.getaddrinfo = original_getaddrinfo  # type: ignore[method-assign]

        assert not calls, "to_dict() triggered a network lookup — it must be pure"


# ---------------------------------------------------------------------------
# 6. Protocol evidence is always present in serialized output
# ---------------------------------------------------------------------------


class TestProtocolEvidencePresence:
    def test_rest_evidence_protocol_matches_parent(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_bacnet_evidence_protocol_matches_parent(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_rest_evidence_method_is_http_verb(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "GET"

    def test_bacnet_evidence_method_is_service_name(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "ReadProperty"

    def test_rest_evidence_path_is_clean(self) -> None:
        """REST evidence path must not contain a query string."""
        d = _rest_normalized().to_dict()
        assert "?" not in d["protocol_evidence"]["path"]
