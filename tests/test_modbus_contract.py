"""
Modbus adapter contract preservation tests.

These tests verify that the Modbus adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no gateway, no policy evaluation.
8. Modbus serializes to the same canonical shape as REST and BACnet.
"""

from __future__ import annotations

import sys

from basis_adapters.modbus.adapter import ModbusAdapter
from basis_adapters.modbus.mapping import ModbusMappingConfig, ModbusOperation, ModbusRouteMapping
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)

# Canonical field sets shared with test_normalization_contract.py.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)
CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> ModbusOperation:
    defaults: dict[str, object] = {
        "function": "ReadHoldingRegisters",
        "unit_id": 1,
        "address": 40001,
        "quantity": 1,
    }
    defaults.update(kwargs)
    return ModbusOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> ModbusRouteMapping:
    defaults: dict[str, object] = {
        "function": "*",
        "register_type": "*",
        "action": "read",
        "resource_type": "modbus_register",
        "resource_id_template": "unit:{unit_id}:{register_type}:{address}",
        "name": "",
    }
    defaults.update(kwargs)
    return ModbusRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: ModbusRouteMapping, adapter_id: str = "contract-test") -> ModbusAdapter:
    config = ModbusMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return ModbusAdapter(mapping=config, context=ctx)


def normalized_modbus() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"Modbus normalization failed: {result.error}"
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

    def test_normalize_never_raises_with_any_function(self) -> None:
        from basis_adapters.modbus.mapping import VALID_MODBUS_FUNCTIONS

        adapter = make_adapter()  # no routes — all will fail
        for fn in VALID_MODBUS_FUNCTIONS:
            result = adapter.normalize(make_op(function=fn))
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

    def test_evidence_protocol_is_modbus(self) -> None:
        req = normalized_modbus()
        assert req.protocol_evidence.protocol == "modbus"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route(function="*", register_type="*"))
        result = adapter.normalize(make_op(unit_id=99, address=12345))
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["unit_id"] == 99
        assert ev.metadata["address"] == 12345


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway
# ---------------------------------------------------------------------------


class TestModbusAdapterIsolation:
    def test_modbus_does_not_import_basis_core(self) -> None:
        modbus_modules = [n for n in sys.modules if n.startswith("basis_adapters.modbus")]
        for mod_name in modbus_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_modbus_does_not_import_basis_gateway(self) -> None:
        modbus_modules = [n for n in sys.modules if n.startswith("basis_adapters.modbus")]
        for mod_name in modbus_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

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
            adapter.normalize(make_op())
        finally:
            socket.getaddrinfo = original  # type: ignore[method-assign]

        assert not calls, "normalize() triggered a network call — it must be pure"


# ---------------------------------------------------------------------------
# 4. Canonical serialized shape
# ---------------------------------------------------------------------------


class TestModbusCanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_modbus().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_modbus(self) -> None:
        d = normalized_modbus().to_dict()
        assert d["protocol"] == "modbus"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_modbus().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_modbus().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_modbus().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_modbus().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_modbus()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_modbus_fields(self) -> None:
        d = normalized_modbus().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "unit_id" in meta
        assert "address" in meta
        assert "quantity" in meta
        assert "value_present" in meta
        assert "function" in meta
