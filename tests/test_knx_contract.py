"""
KNX adapter contract preservation tests.

These tests verify that the KNX adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no KNX stack, no policy evaluation.
8. KNX serializes to the same canonical shape as the other protocols.
9. The individual address is evidence only — never identity.
10. The adapter is stateless — no bus state is retained between calls.
"""

from __future__ import annotations

import sys

from basis_adapters.knx.adapter import KnxAdapter
from basis_adapters.knx.mapping import (
    KnxMappingConfig,
    KnxOperation,
    KnxRouteMapping,
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


def make_op(**kwargs: object) -> KnxOperation:
    defaults: dict[str, object] = {
        "operation": "GROUP_VALUE_READ",
        "group_address": "1/2/3",
        "individual_address": "1.1.5",
        "datapoint_type": "1.001",
        "priority": "normal",
    }
    defaults.update(kwargs)
    return KnxOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> KnxRouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "group_address": "*",
        "action": "",
        "resource_type": "knx_group_address",
        "resource_id_template": "knx:group:{group_address}",
        "name": "",
    }
    defaults.update(kwargs)
    return KnxRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: KnxRouteMapping, adapter_id: str = "contract-test") -> KnxAdapter:
    config = KnxMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return KnxAdapter(mapping=config, context=ctx)


def normalized_knx() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"KNX normalization failed: {result.error}"
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
            make_op(operation="DEVICE_DESCRIPTOR_READ"),
            make_op(group_address=None),
            make_op(group_address="32/0/0"),
            make_op(individual_address="16.1.5"),
            make_op(datapoint_type="not-a-dpt"),
            make_op(priority="critical"),
            make_op(communication_object=-1),
            make_op(area=99),
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

    def test_evidence_protocol_is_knx(self) -> None:
        req = normalized_knx()
        assert req.protocol_evidence.protocol == "knx"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                operation="GROUP_VALUE_WRITE",
                group_address="4/1/20",
                device_address="1.1.7",
                communication_object=4,
                datapoint_type="9.001",
                payload_type="float",
                value=21.5,
                priority="urgent",
                area=1,
                line=1,
                device=7,
            )
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["operation"] == "GROUP_VALUE_WRITE"
        assert ev.metadata["group_address"] == "4/1/20"
        assert ev.metadata["device_address"] == "1.1.7"
        assert ev.metadata["communication_object"] == 4
        assert ev.metadata["datapoint_type"] == "9.001"
        assert ev.metadata["payload_type"] == "float"
        assert ev.metadata["value"] == 21.5
        assert ev.metadata["priority"] == "urgent"
        assert ev.metadata["area"] == 1
        assert ev.metadata["line"] == 1
        assert ev.metadata["device"] == 7

    def test_value_preserved_verbatim_but_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE", value=72.5))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5
        assert "72.5" not in result.request.resource_id


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no KNX stack
# ---------------------------------------------------------------------------


class TestKnxAdapterIsolation:
    def test_knx_does_not_import_basis_core(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.knx")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_knx_does_not_import_basis_gateway(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.knx")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_knx_does_not_import_knx_stack_libraries(self) -> None:
        """The adapter is pure normalization — no xknx/knxip or other
        protocol stack libraries."""
        modules = [n for n in sys.modules if n.startswith("basis_adapters.knx")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "import xknx" not in content, (
                    f"Module {mod_name!r} must not import a KNX stack library"
                )
                assert "import knxip" not in content, (
                    f"Module {mod_name!r} must not import a KNX stack library"
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


class TestKnxCanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_knx().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_knx(self) -> None:
        d = normalized_knx().to_dict()
        assert d["protocol"] == "knx"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_knx().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_knx().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_knx().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_knx_specific_top_level_fields(self) -> None:
        """KNX detail (group address, individual address, communication
        object, DPT, value, priority, topology) must stay inside
        protocol_evidence — never as top-level siblings of
        action/resource_id."""
        d = normalized_knx().to_dict()
        knx_specific = {
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
        assert not (knx_specific & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_knx().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_knx()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_knx_fields(self) -> None:
        d = normalized_knx().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        for key in (
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
        ):
            assert key in meta, f"Evidence metadata missing KNX field {key!r}"


# ---------------------------------------------------------------------------
# 5. Individual address is evidence, never identity
# ---------------------------------------------------------------------------


class TestIndividualAddressIsNotIdentity:
    def test_individual_address_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(individual_address="1.1.5"))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_only_from_explicit_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                individual_address="1.1.5",
                metadata={"subject_hint": "operator@example.internal"},
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"


# ---------------------------------------------------------------------------
# 6. Statelessness — no bus state retained
# ---------------------------------------------------------------------------


class TestStatelessness:
    def test_adapter_holds_no_operation_state(self) -> None:
        """Normalizing an OBSERVE or a GROUP_VALUE_RESPONSE must not change
        how a subsequent operation normalizes — the adapter is a pure
        function of (mapping, operation) and retains no bus state."""
        adapter = make_adapter(make_route())
        op_write = make_op(operation="GROUP_VALUE_WRITE", value=True)

        write_before = adapter.normalize(op_write)
        adapter.normalize(make_op(operation="OBSERVE"))
        adapter.normalize(make_op(operation="GROUP_VALUE_RESPONSE", value=False))
        write_after = adapter.normalize(op_write)

        assert write_before.success and write_after.success
        assert write_before.request is not None and write_after.request is not None
        assert write_before.request.to_dict() == write_after.request.to_dict()
