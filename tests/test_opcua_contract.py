"""
OPC UA adapter contract preservation tests — Phase 7.

These tests verify that the OPC UA adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no gateway, no policy evaluation,
   no authentication.
8. OPC UA serializes to the same canonical shape as REST, BACnet, and Modbus.
"""

from __future__ import annotations

import sys

from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.opcua.adapter import OpcuaAdapter
from basis_adapters.opcua.mapping import (
    OpcuaMappingConfig,
    OpcuaOperation,
    OpcuaRouteMapping,
)

# Canonical field sets shared with test_normalization_contract.py.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)
CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> OpcuaOperation:
    defaults: dict[str, object] = {
        "service": "Read",
        "node_id": "ns=2;s=Building.AHU1.SupplyTemp",
        "attribute_id": "Value",
    }
    defaults.update(kwargs)
    return OpcuaOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> OpcuaRouteMapping:
    defaults: dict[str, object] = {
        "service": "*",
        "attribute_id": "*",
        "action": "read",
        "resource_type": "opcua_node",
        "resource_id_template": "{node_id}",
        "name": "",
    }
    defaults.update(kwargs)
    return OpcuaRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: OpcuaRouteMapping, adapter_id: str = "contract-test") -> OpcuaAdapter:
    config = OpcuaMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return OpcuaAdapter(mapping=config, context=ctx)


def normalized_opcua() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"OPC UA normalization failed: {result.error}"
    assert result.request is not None
    return result.request


# ---------------------------------------------------------------------------
# 1. AdapterResult invariants
# ---------------------------------------------------------------------------


class TestAdapterResultInvariants:
    def test_success_result_has_request_and_no_error(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success is True
        assert result.request is not None
        assert result.error is None

    def test_failure_result_has_error_and_no_request(self) -> None:
        adapter = make_adapter()  # no routes → always fails
        result = adapter.normalize(make_op())
        assert result.success is False
        assert result.request is None
        assert result.error is not None

    def test_normalize_never_raises(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op())
        assert isinstance(result, AdapterResult)

    def test_normalize_never_raises_with_any_service(self) -> None:
        from basis_adapters.opcua.mapping import VALID_OPCUA_SERVICES

        adapter = make_adapter()  # no routes — all will fail
        for service in VALID_OPCUA_SERVICES:
            result = adapter.normalize(make_op(service=service))
            assert isinstance(result, AdapterResult)


# ---------------------------------------------------------------------------
# 2. Protocol evidence always preserved
# ---------------------------------------------------------------------------


class TestProtocolEvidenceContract:
    def test_evidence_always_present_on_success(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence is not None
        assert isinstance(result.request.protocol_evidence, ProtocolOperation)

    def test_evidence_protocol_is_opcua(self) -> None:
        req = normalized_opcua()
        assert req.protocol_evidence.protocol == "opcua"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route(service="*", attribute_id="*"))
        result = adapter.normalize(
            make_op(node_id="ns=5;s=Plant.Boiler2", namespace_index=5, session_id="s-1")
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["node_id"] == "ns=5;s=Plant.Boiler2"
        assert ev.metadata["namespace_index"] == 5
        assert ev.metadata["session_id"] == "s-1"


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no authentication
# ---------------------------------------------------------------------------


class TestOpcuaAdapterIsolation:
    def test_opcua_does_not_import_basis_core(self) -> None:
        opcua_modules = [n for n in sys.modules if n.startswith("basis_adapters.opcua")]
        for mod_name in opcua_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_opcua_does_not_import_basis_gateway(self) -> None:
        opcua_modules = [n for n in sys.modules if n.startswith("basis_adapters.opcua")]
        for mod_name in opcua_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_opcua_does_not_import_opcua_protocol_libraries(self) -> None:
        """No asyncua, no opcua library — this phase models intent only."""
        opcua_modules = [n for n in sys.modules if n.startswith("basis_adapters.opcua")]
        for mod_name in opcua_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "import asyncua" not in content, (
                    f"Module {mod_name!r} must not import asyncua"
                )
                assert "from asyncua" not in content, f"Module {mod_name!r} must not import asyncua"

    def test_normalize_does_not_call_network(self) -> None:
        import socket

        original = socket.getaddrinfo
        calls: list[object] = []

        def spy(*args: object, **kwargs: object) -> object:
            calls.append(args)
            return original(*args, **kwargs)  # type: ignore[arg-type]

        socket.getaddrinfo = spy  # type: ignore[method-assign]
        try:
            adapter = make_adapter(make_route())
            adapter.normalize(make_op(endpoint_url="opc.tcp://building-server:4840/basis"))
        finally:
            socket.getaddrinfo = original  # type: ignore[method-assign]

        assert not calls, "normalize() triggered a network call — it must be pure"

    def test_session_id_is_evidence_not_authentication(self) -> None:
        """A session_id on the operation is preserved as evidence only — it is
        never resolved into a verified subject."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(session_id="session-7f3a"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        # session_id lives only inside protocol_evidence.metadata
        assert d["protocol_evidence"]["metadata"]["session_id"] == "session-7f3a"
        assert d["subject_hint"] is None


# ---------------------------------------------------------------------------
# 4. Canonical serialized shape
# ---------------------------------------------------------------------------


class TestOpcuaCanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_opcua().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_opcua(self) -> None:
        d = normalized_opcua().to_dict()
        assert d["protocol"] == "opcua"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_opcua().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_opcua().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_opcua().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_opcua().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_opcua()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_opcua_fields(self) -> None:
        d = normalized_opcua().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "service" in meta
        assert "node_id" in meta
        assert "attribute_id" in meta
        assert "method_id" in meta
        assert "namespace_index" in meta
        assert "value_present" in meta
        assert "endpoint_url" in meta
        assert "session_id" in meta
