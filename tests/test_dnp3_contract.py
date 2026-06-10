"""
DNP3 adapter contract preservation tests.

These tests verify that the DNP3 adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no DNP3 stack, no policy evaluation.
8. DNP3 serializes to the same canonical shape as the other protocols.
9. Addresses and master_id are evidence only — never identity.
10. The adapter is stateless — SELECT/OPERATE normalize independently.
"""

from __future__ import annotations

import sys

from basis_adapters.dnp3.adapter import Dnp3Adapter
from basis_adapters.dnp3.mapping import Dnp3MappingConfig, Dnp3Operation, Dnp3RouteMapping
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


def make_op(**kwargs: object) -> Dnp3Operation:
    defaults: dict[str, object] = {
        "operation": "READ",
        "outstation_id": "os-14",
        "point_type": "analog_input",
        "point_index": 3,
        "source_address": 1,
        "destination_address": 10,
    }
    defaults.update(kwargs)
    return Dnp3Operation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> Dnp3RouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "point_type": "*",
        "action": "",
        "resource_type": "dnp3_point",
        "resource_id_template": "dnp3:outstation:{outstation_id}/{point_type}/{point_index}",
        "name": "",
    }
    defaults.update(kwargs)
    return Dnp3RouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: Dnp3RouteMapping, adapter_id: str = "contract-test") -> Dnp3Adapter:
    config = Dnp3MappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return Dnp3Adapter(mapping=config, context=ctx)


def normalized_dnp3() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"DNP3 normalization failed: {result.error}"
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

    def test_normalize_never_raises_on_invalid_operations(self) -> None:
        adapter = make_adapter(make_route())
        invalid_ops = [
            make_op(operation="COLD_RESTART"),
            make_op(outstation_id=None, destination_address=None),
            make_op(object_group=999),
            make_op(point_type="thermocouple"),
            make_op(operation="OPERATE", point_index=None),
            make_op(operation="DIRECT_OPERATE", control_model="select_before_operate"),
            make_op(event_class=9),
        ]
        for op in invalid_ops:
            result = adapter.normalize(op)
            assert isinstance(result, AdapterResult)
            assert not result.success


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

    def test_evidence_protocol_is_dnp3(self) -> None:
        req = normalized_dnp3()
        assert req.protocol_evidence.protocol == "dnp3"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route(operation="*", point_type="*"))
        result = adapter.normalize(
            make_op(
                operation="DIRECT_OPERATE",
                point_type="binary_output",
                point_index=7,
                object_group=12,
                variation=1,
                function_code=5,
                control_code=65,
                control_model="direct_operate",
                value="LATCH_ON",
                master_id="master-1",
            )
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["operation"] == "DIRECT_OPERATE"
        assert ev.metadata["object_group"] == 12
        assert ev.metadata["variation"] == 1
        assert ev.metadata["function_code"] == 5
        assert ev.metadata["control_code"] == 65
        assert ev.metadata["control_model"] == "direct_operate"
        assert ev.metadata["value"] == "LATCH_ON"
        assert ev.metadata["master_id"] == "master-1"

    def test_value_preserved_verbatim_but_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                operation="DIRECT_OPERATE",
                point_type="analog_output",
                point_index=2,
                control_model="direct_operate",
                value=72.5,
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5
        assert "72.5" not in result.request.resource_id


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no DNP3 stack
# ---------------------------------------------------------------------------


class TestDnp3AdapterIsolation:
    def test_dnp3_does_not_import_basis_core(self) -> None:
        dnp3_modules = [n for n in sys.modules if n.startswith("basis_adapters.dnp3")]
        for mod_name in dnp3_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_dnp3_does_not_import_basis_gateway(self) -> None:
        dnp3_modules = [n for n in sys.modules if n.startswith("basis_adapters.dnp3")]
        for mod_name in dnp3_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_dnp3_does_not_import_dnp3_stack_libraries(self) -> None:
        """The adapter is pure normalization — no dnp3-python/pydnp3 or other
        protocol stack libraries."""
        dnp3_modules = [n for n in sys.modules if n.startswith("basis_adapters.dnp3")]
        for mod_name in dnp3_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "import pydnp3" not in content, (
                    f"Module {mod_name!r} must not import a DNP3 stack library"
                )
                assert "import dnp3_python" not in content, (
                    f"Module {mod_name!r} must not import a DNP3 stack library"
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


class TestDnp3CanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_dnp3().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_dnp3(self) -> None:
        d = normalized_dnp3().to_dict()
        assert d["protocol"] == "dnp3"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_dnp3().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_dnp3().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_dnp3().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_dnp3_specific_top_level_fields(self) -> None:
        """DNP3 detail (outstation, addresses, object group, control model)
        must stay inside protocol_evidence — never as top-level siblings of
        action/resource_id."""
        d = normalized_dnp3().to_dict()
        dnp3_specific = {
            "operation",
            "outstation_id",
            "master_id",
            "source_address",
            "destination_address",
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
        assert not (dnp3_specific & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_dnp3().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_dnp3()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_dnp3_fields(self) -> None:
        d = normalized_dnp3().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        for key in (
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
        ):
            assert key in meta, f"Evidence metadata missing DNP3 field {key!r}"


# ---------------------------------------------------------------------------
# 5. Addresses and master_id are evidence, never identity
# ---------------------------------------------------------------------------


class TestAddressesAreNotIdentity:
    def test_master_id_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(master_id="master-1"))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_source_address_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(source_address=1))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_only_from_explicit_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                master_id="master-1",
                metadata={"subject_hint": "operator@example.internal"},
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"


# ---------------------------------------------------------------------------
# 6. Statelessness — no select/operate correlation
# ---------------------------------------------------------------------------


class TestStatelessness:
    def test_adapter_holds_no_operation_state(self) -> None:
        """Normalizing a SELECT must not change how a subsequent OPERATE (or
        anything else) normalizes — the adapter is a pure function of
        (mapping, operation)."""
        adapter = make_adapter(make_route())
        op_select = make_op(
            operation="SELECT",
            point_type="binary_output",
            point_index=7,
            control_model="select_before_operate",
        )
        op_operate = make_op(
            operation="OPERATE",
            point_type="binary_output",
            point_index=7,
            control_model="select_before_operate",
        )

        operate_before = adapter.normalize(op_operate)
        adapter.normalize(op_select)
        operate_after = adapter.normalize(op_operate)

        assert operate_before.success and operate_after.success
        assert operate_before.request is not None and operate_after.request is not None
        assert operate_before.request.to_dict() == operate_after.request.to_dict()
