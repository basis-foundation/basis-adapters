"""
IEC 61850 adapter contract preservation tests.

These tests verify that the IEC 61850 adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no IEC 61850 stack, no policy
   evaluation.
8. IEC 61850 serializes to the same canonical shape as the other protocols.
9. Origin is evidence only — never identity.
10. The adapter is stateless — SELECT/OPERATE normalize independently.
"""

from __future__ import annotations

import sys

from basis_adapters.iec61850.adapter import Iec61850Adapter
from basis_adapters.iec61850.mapping import (
    Iec61850MappingConfig,
    Iec61850Operation,
    Iec61850RouteMapping,
)
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


def make_op(**kwargs: object) -> Iec61850Operation:
    defaults: dict[str, object] = {
        "operation": "READ",
        "ied_name": "ied-sub1",
        "logical_device": "MEAS",
        "logical_node": "MMXU1",
        "data_object": "TotW",
        "data_attribute": "mag",
        "functional_constraint": "MX",
    }
    defaults.update(kwargs)
    return Iec61850Operation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> Iec61850RouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "logical_node": "*",
        "action": "",
        "resource_type": "iec61850_data_attribute",
        "resource_id_template": (
            "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
            "/do:{data_object}/da:{data_attribute}"
        ),
        "name": "",
    }
    defaults.update(kwargs)
    return Iec61850RouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(
    *routes: Iec61850RouteMapping, adapter_id: str = "contract-test"
) -> Iec61850Adapter:
    config = Iec61850MappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return Iec61850Adapter(mapping=config, context=ctx)


def normalized_iec61850() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"IEC 61850 normalization failed: {result.error}"
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
            make_op(operation="GET_DIRECTORY"),
            make_op(ied_name=None),
            make_op(logical_device=None),
            make_op(data_object=None),
            make_op(functional_constraint="ZZ"),
            make_op(operation="OPERATE", data_object=None),
            make_op(
                operation="DIRECT_OPERATE",
                data_attribute=None,
                control_model="sbo_with_normal_security",
            ),
            make_op(operation="ENABLE_REPORTING", report_control_block=None),
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

    def test_evidence_protocol_is_iec61850(self) -> None:
        req = normalized_iec61850()
        assert req.protocol_evidence.protocol == "iec61850"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(
            make_route(
                operation="*",
                logical_node="*",
                resource_id_template=(
                    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}"
                ),
            )
        )
        result = adapter.normalize(
            make_op(
                operation="DIRECT_OPERATE",
                logical_device="CTRL",
                logical_node="CSWI1",
                data_object="Pos",
                data_attribute=None,
                functional_constraint="CO",
                control_model="direct_with_enhanced_security",
                origin={"orCat": "remote-control", "orIdent": "scada-master-1"},
                cause="remote-command",
                timestamp="2026-06-10T14:31:12Z",
                value=True,
            )
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["operation"] == "DIRECT_OPERATE"
        assert ev.metadata["logical_device"] == "CTRL"
        assert ev.metadata["logical_node"] == "CSWI1"
        assert ev.metadata["data_object"] == "Pos"
        assert ev.metadata["functional_constraint"] == "CO"
        assert ev.metadata["control_model"] == "direct_with_enhanced_security"
        assert ev.metadata["origin"] == {"orCat": "remote-control", "orIdent": "scada-master-1"}
        assert ev.metadata["cause"] == "remote-command"
        assert ev.metadata["timestamp"] == "2026-06-10T14:31:12Z"
        assert ev.metadata["value"] is True

    def test_value_preserved_verbatim_but_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="WRITE", value=72.5))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5
        assert "72.5" not in result.request.resource_id


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no IEC 61850 stack
# ---------------------------------------------------------------------------


class TestIec61850AdapterIsolation:
    def test_iec61850_does_not_import_basis_core(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.iec61850")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_iec61850_does_not_import_basis_gateway(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.iec61850")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_iec61850_does_not_import_iec61850_stack_libraries(self) -> None:
        """The adapter is pure normalization — no pyiec61850/libiec61850 or
        other protocol stack libraries."""
        modules = [n for n in sys.modules if n.startswith("basis_adapters.iec61850")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "import pyiec61850" not in content, (
                    f"Module {mod_name!r} must not import an IEC 61850 stack library"
                )
                assert "import libiec61850" not in content, (
                    f"Module {mod_name!r} must not import an IEC 61850 stack library"
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


class TestIec61850CanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_iec61850().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_iec61850(self) -> None:
        d = normalized_iec61850().to_dict()
        assert d["protocol"] == "iec61850"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_iec61850().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_iec61850().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_iec61850().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_iec61850_specific_top_level_fields(self) -> None:
        """IEC 61850 detail (IED, logical node, data object, control model,
        origin) must stay inside protocol_evidence — never as top-level
        siblings of action/resource_id."""
        d = normalized_iec61850().to_dict()
        iec61850_specific = {
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
        assert not (iec61850_specific & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_iec61850().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_iec61850()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_iec61850_fields(self) -> None:
        d = normalized_iec61850().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        for key in (
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
        ):
            assert key in meta, f"Evidence metadata missing IEC 61850 field {key!r}"


# ---------------------------------------------------------------------------
# 5. Origin is evidence, never identity
# ---------------------------------------------------------------------------


class TestOriginIsNotIdentity:
    def test_origin_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(origin={"orCat": "remote-control", "orIdent": "scada-master-1"})
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_only_from_explicit_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                origin={"orCat": "remote-control", "orIdent": "scada-master-1"},
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
        adapter = make_adapter(
            make_route(
                resource_id_template=(
                    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}"
                )
            )
        )
        op_select = make_op(
            operation="SELECT",
            logical_device="CTRL",
            logical_node="CSWI1",
            data_object="Pos",
            data_attribute=None,
            functional_constraint="CO",
            control_model="sbo_with_normal_security",
        )
        op_operate = make_op(
            operation="OPERATE",
            logical_device="CTRL",
            logical_node="CSWI1",
            data_object="Pos",
            data_attribute=None,
            functional_constraint="CO",
            control_model="sbo_with_normal_security",
        )

        operate_before = adapter.normalize(op_operate)
        adapter.normalize(op_select)
        operate_after = adapter.normalize(op_operate)

        assert operate_before.success and operate_after.success
        assert operate_before.request is not None and operate_after.request is not None
        assert operate_before.request.to_dict() == operate_after.request.to_dict()
