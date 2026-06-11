"""
Niagara adapter contract preservation tests.

These tests verify that the Niagara adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no Niagara stack, no policy
   evaluation.
8. Niagara serializes to the same canonical shape as the other protocols.
9. niagara_user and niagara_role are evidence only — never identity.
10. The adapter is stateless — no platform state is retained between calls.
"""

from __future__ import annotations

import sys

from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.niagara.adapter import NiagaraAdapter
from basis_adapters.niagara.mapping import (
    NiagaraMappingConfig,
    NiagaraOperation,
    NiagaraRouteMapping,
)

# Canonical field sets shared with test_normalization_contract.py.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)
CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> NiagaraOperation:
    defaults: dict[str, object] = {
        "operation": "READ_POINT",
        "station": "station-east",
        "point": "AHU1-SupplyTemp",
        "point_type": "NumericPoint",
        "baja_type": "control:NumericPoint",
    }
    defaults.update(kwargs)
    return NiagaraOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> NiagaraRouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "station": "*",
        "action": "",
        "resource_type": "niagara_point",
        "resource_id_template": "niagara:station:{station}/point:{point}",
        "name": "",
    }
    defaults.update(kwargs)
    return NiagaraRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: NiagaraRouteMapping, adapter_id: str = "contract-test") -> NiagaraAdapter:
    config = NiagaraMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return NiagaraAdapter(mapping=config, context=ctx)


def normalized_niagara() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"Niagara normalization failed: {result.error}"
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
            make_op(operation="FOX_LOGIN"),
            make_op(station=None),
            make_op(station="  "),
            make_op(point=None),
            make_op(operation="ACK_ALARM", point=None),
            make_op(operation="RESOLVE_ORD", point=None),
            make_op(ord=" "),
            make_op(niagara_user=""),
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

    def test_evidence_protocol_is_niagara(self) -> None:
        req = normalized_niagara()
        assert req.protocol_evidence.protocol == "niagara"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                operation="OVERRIDE_POINT",
                station="station-west",
                host="supervisor-1.example.internal",
                ord="station:|slot:/Drivers/BacnetNetwork/AHU2",
                point="AHU2-SupplyTempSetpoint",
                point_type="NumericWritable",
                value=68.0,
                facet="units=°F",
                category="HVAC",
                baja_type="control:NumericWritable",
                nav_path="/Drivers/BacnetNetwork/AHU2",
                niagara_user="operator1",
                niagara_role="operator",
                metadata={"override_level": 8},
            )
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["operation"] == "OVERRIDE_POINT"
        assert ev.metadata["station"] == "station-west"
        assert ev.metadata["host"] == "supervisor-1.example.internal"
        assert ev.metadata["ord"] == "station:|slot:/Drivers/BacnetNetwork/AHU2"
        assert ev.metadata["point"] == "AHU2-SupplyTempSetpoint"
        assert ev.metadata["point_type"] == "NumericWritable"
        assert ev.metadata["value"] == 68.0
        assert ev.metadata["facet"] == "units=°F"
        assert ev.metadata["category"] == "HVAC"
        assert ev.metadata["baja_type"] == "control:NumericWritable"
        assert ev.metadata["nav_path"] == "/Drivers/BacnetNetwork/AHU2"
        assert ev.metadata["niagara_user"] == "operator1"
        assert ev.metadata["niagara_role"] == "operator"
        assert ev.metadata["override_level"] == 8

    def test_value_preserved_verbatim_but_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="WRITE_POINT", value=72.5))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5
        assert "72.5" not in result.request.resource_id


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no Niagara stack
# ---------------------------------------------------------------------------


class TestNiagaraAdapterIsolation:
    def test_niagara_does_not_import_basis_core(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.niagara")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_niagara_does_not_import_basis_gateway(self) -> None:
        modules = [n for n in sys.modules if n.startswith("basis_adapters.niagara")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_niagara_does_not_import_niagara_client_libraries(self) -> None:
        """The adapter is pure normalization — no Fox/Foxs, Haystack, or
        other Niagara connectivity libraries."""
        modules = [n for n in sys.modules if n.startswith("basis_adapters.niagara")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                for forbidden in ("import hszinc", "import pyhaystack", "import niawebclient"):
                    assert forbidden not in content, (
                        f"Module {mod_name!r} must not import a Niagara client library"
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


class TestNiagaraCanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_niagara().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_niagara(self) -> None:
        d = normalized_niagara().to_dict()
        assert d["protocol"] == "niagara"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_niagara().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_niagara().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_niagara().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_niagara_specific_top_level_fields(self) -> None:
        """Niagara detail (station, ord, component, point, value, facet,
        users, roles, ...) must stay inside protocol_evidence — never as
        top-level siblings of action/resource_id."""
        d = normalized_niagara().to_dict()
        niagara_specific = {
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
        assert not (niagara_specific & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_niagara().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_niagara()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_niagara_fields(self) -> None:
        d = normalized_niagara().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        for key in (
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
        ):
            assert key in meta, f"Evidence metadata missing Niagara field {key!r}"


# ---------------------------------------------------------------------------
# 5. Niagara users and roles are evidence, never identity
# ---------------------------------------------------------------------------


class TestNiagaraUserIsNotIdentity:
    def test_niagara_user_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_user="operator1"))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_niagara_role_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_role="operator"))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_only_from_explicit_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                niagara_user="operator1",
                niagara_role="operator",
                metadata={"subject_hint": "operator@example.internal"},
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"


# ---------------------------------------------------------------------------
# 6. Statelessness — no platform state retained
# ---------------------------------------------------------------------------


class TestStatelessness:
    def test_adapter_holds_no_operation_state(self) -> None:
        """Normalizing an override, a subscription, or an acknowledgement
        must not change how a subsequent operation normalizes — the adapter
        is a pure function of (mapping, operation) and retains no platform,
        override, or command state."""
        adapter = make_adapter(make_route())
        op_read = make_op()

        read_before = adapter.normalize(op_read)
        adapter.normalize(make_op(operation="OVERRIDE_POINT", value=68.0))
        adapter.normalize(make_op(operation="SUBSCRIBE_POINT"))
        adapter.normalize(make_op(operation="RELEASE_OVERRIDE"))
        read_after = adapter.normalize(op_read)

        assert read_before.success and read_after.success
        assert read_before.request is not None and read_after.request is not None
        assert read_before.request.to_dict() == read_after.request.to_dict()
