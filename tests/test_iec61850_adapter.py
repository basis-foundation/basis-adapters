"""
Tests for Iec61850Adapter normalization behavior.

Covers read, write, and control normalization, select-before-operate
statelessness, direct operate, reporting/GOOSE/Sampled Values (subscribe),
route matching, template substitution, operation validation (fail closed),
protocol evidence preservation, and failure result shapes.
"""

from __future__ import annotations

from basis_adapters.iec61850.adapter import Iec61850Adapter
from basis_adapters.iec61850.mapping import (
    Iec61850MappingConfig,
    Iec61850Operation,
    Iec61850RouteMapping,
)
from basis_adapters.models import AdapterContext, AdapterResult

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


def make_control_op(**kwargs: object) -> Iec61850Operation:
    defaults: dict[str, object] = {
        "operation": "DIRECT_OPERATE",
        "ied_name": "ied-sub1",
        "logical_device": "CTRL",
        "logical_node": "CSWI1",
        "data_object": "Pos",
        "data_attribute": None,
        "functional_constraint": "CO",
        "control_model": "direct_with_normal_security",
    }
    defaults.update(kwargs)
    return Iec61850Operation(**defaults)  # type: ignore[arg-type]


def make_reporting_op(**kwargs: object) -> Iec61850Operation:
    defaults: dict[str, object] = {
        "operation": "ENABLE_REPORTING",
        "ied_name": "ied-sub1",
        "logical_device": "MEAS",
        "logical_node": "LLN0",
        "dataset": "MeasFlt",
        "report_control_block": "urcbMX01",
    }
    defaults.update(kwargs)
    return Iec61850Operation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> Iec61850RouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "logical_node": "*",
        "action": "",
        "resource_type": "iec61850_data_object",
        "resource_id_template": (
            "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}"
        ),
        "name": "",
    }
    defaults.update(kwargs)
    return Iec61850RouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: Iec61850RouteMapping, adapter_id: str = "test") -> Iec61850Adapter:
    config = Iec61850MappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return Iec61850Adapter(mapping=config, context=ctx)


DA_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
    "/do:{data_object}/da:{data_attribute}"
)
RCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/rcb:{report_control_block}"
)
GCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/gcb:{goose_control_block}"
)
SVCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
    "/svcb:{sampled_values_control_block}"
)


# ---------------------------------------------------------------------------
# Read normalization
# ---------------------------------------------------------------------------


class TestReadNormalization:
    def test_read_normalizes_to_read_by_default(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op(operation="READ"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_data_attribute_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="READ", resource_id_template=DA_TEMPLATE))
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag"

    def test_read_data_object_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op(data_attribute=None))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW"

    def test_read_logical_node_resource_id(self) -> None:
        route = make_route(
            operation="READ",
            resource_id_template="iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(data_object=None, data_attribute=None, functional_constraint=None)
        )
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1"

    def test_read_evidence_includes_iec61850_fields(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op(quality="good", timestamp="2026-06-10T14:30:00Z"))
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["operation"] == "READ"
        assert meta["ied_name"] == "ied-sub1"
        assert meta["logical_device"] == "MEAS"
        assert meta["logical_node"] == "MMXU1"
        assert meta["data_object"] == "TotW"
        assert meta["data_attribute"] == "mag"
        assert meta["functional_constraint"] == "MX"
        assert meta["quality"] == "good"
        assert meta["timestamp"] == "2026-06-10T14:30:00Z"


# ---------------------------------------------------------------------------
# Write normalization
# ---------------------------------------------------------------------------


class TestWriteNormalization:
    def test_write_normalizes_to_write_by_default(self) -> None:
        adapter = make_adapter(make_route(operation="WRITE"))
        result = adapter.normalize(make_op(operation="WRITE", value=42.5))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_write_value_preserved_as_evidence(self) -> None:
        adapter = make_adapter(make_route(operation="WRITE"))
        result = adapter.normalize(make_op(operation="WRITE", value=42.5))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 42.5

    def test_write_value_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="WRITE", resource_id_template=DA_TEMPLATE))
        result = adapter.normalize(make_op(operation="WRITE", value="SECRET_SETPOINT"))
        assert result.success
        assert result.request is not None
        assert "SECRET_SETPOINT" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Control normalization — select / operate / direct operate / cancel
# ---------------------------------------------------------------------------


class TestControlNormalization:
    def test_select_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="SELECT"))
        result = adapter.normalize(
            make_control_op(operation="SELECT", control_model="sbo_with_normal_security")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_select_with_value_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="SELECT_WITH_VALUE"))
        result = adapter.normalize(
            make_control_op(
                operation="SELECT_WITH_VALUE",
                control_model="sbo_with_enhanced_security",
                value=True,
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_operate_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="OPERATE"))
        result = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="sbo_with_normal_security")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_direct_operate_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_cancel_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="CANCEL"))
        result = adapter.normalize(
            make_control_op(operation="CANCEL", control_model="sbo_with_normal_security")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_control_resource_id_targets_data_object(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op())
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:CTRL/ln:CSWI1/do:Pos"

    def test_control_model_preserved_as_evidence(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op())
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["control_model"] == "direct_with_normal_security"

    def test_control_evidence_preserves_origin_and_value(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(
            make_control_op(
                origin={"orCat": "remote-control", "orIdent": "scada-master-1"},
                cause="remote-command",
                value=True,
            )
        )
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["origin"] == {"orCat": "remote-control", "orIdent": "scada-master-1"}
        assert meta["cause"] == "remote-command"
        assert meta["value"] is True

    def test_value_never_appears_in_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op(value="TRIP_BREAKER"))
        assert result.success
        assert result.request is not None
        assert "TRIP_BREAKER" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Select-before-operate — stateless, independent normalization
# ---------------------------------------------------------------------------


class TestSelectBeforeOperate:
    def test_select_and_operate_normalize_independently(self) -> None:
        adapter = make_adapter(make_route())
        select = adapter.normalize(
            make_control_op(operation="SELECT", control_model="sbo_with_normal_security")
        )
        operate = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="sbo_with_normal_security")
        )
        assert select.success and operate.success
        assert select.request is not None and operate.request is not None
        # Same data object, same resource — only the operation differs.
        assert select.request.resource_id == operate.request.resource_id
        assert select.request.protocol_evidence.method == "SELECT"
        assert operate.request.protocol_evidence.method == "OPERATE"

    def test_operate_succeeds_without_prior_select(self) -> None:
        """The adapter keeps no sequencing state: an OPERATE normalizes on its
        own. Whether it should be honored without a SELECT is a runtime
        enforcement question, not a normalization question."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="sbo_with_normal_security")
        )
        assert result.success

    def test_repeated_select_produces_identical_output(self) -> None:
        """No state accumulates between calls."""
        adapter = make_adapter(make_route())
        op = make_control_op(operation="SELECT", control_model="sbo_with_normal_security")
        r1 = adapter.normalize(op)
        r2 = adapter.normalize(op)
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.to_dict() == r2.request.to_dict()

    def test_evidence_distinguishes_operation_type(self) -> None:
        adapter = make_adapter(make_route())
        select = adapter.normalize(
            make_control_op(operation="SELECT", control_model="sbo_with_normal_security")
        )
        direct = adapter.normalize(make_control_op())
        assert select.request is not None and direct.request is not None
        assert select.request.protocol_evidence.metadata["operation"] == "SELECT"
        assert select.request.protocol_evidence.metadata["control_model"] == (
            "sbo_with_normal_security"
        )
        assert direct.request.protocol_evidence.metadata["operation"] == "DIRECT_OPERATE"
        assert direct.request.protocol_evidence.metadata["control_model"] == (
            "direct_with_normal_security"
        )


# ---------------------------------------------------------------------------
# Reporting / GOOSE / Sampled Values — subscribe semantics
# ---------------------------------------------------------------------------


class TestReportingGooseSampledValues:
    def test_enable_reporting_normalizes_to_subscribe(self) -> None:
        route = make_route(
            operation="ENABLE_REPORTING",
            resource_type="iec61850_report_control_block",
            resource_id_template=RCB_TEMPLATE,
        )
        adapter = make_adapter(route)
        result = adapter.normalize(make_reporting_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:MEAS/ln:LLN0/rcb:urcbMX01"

    def test_enable_goose_normalizes_to_subscribe(self) -> None:
        route = make_route(
            operation="ENABLE_GOOSE",
            resource_type="iec61850_goose_control_block",
            resource_id_template=GCB_TEMPLATE,
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(
                operation="ENABLE_GOOSE",
                logical_device="PROT",
                report_control_block=None,
                dataset="TripSignals",
                goose_control_block="gcbTrip",
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:PROT/ln:LLN0/gcb:gcbTrip"

    def test_enable_sampled_values_normalizes_to_subscribe(self) -> None:
        route = make_route(
            operation="ENABLE_SAMPLED_VALUES",
            resource_type="iec61850_sampled_values_control_block",
            resource_id_template=SVCB_TEMPLATE,
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(
                operation="ENABLE_SAMPLED_VALUES",
                logical_device="MU01",
                report_control_block=None,
                dataset=None,
                sampled_values_control_block="MSVCB01",
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"
        assert result.request.resource_id == "iec61850:ied:ied-sub1/ld:MU01/ln:LLN0/svcb:MSVCB01"

    def test_control_block_identifiers_preserved_as_evidence(self) -> None:
        route = make_route(operation="ENABLE_REPORTING", resource_id_template=RCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(make_reporting_op())
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["report_control_block"] == "urcbMX01"
        assert meta["dataset"] == "MeasFlt"

    def test_goose_control_block_preserved_as_evidence(self) -> None:
        route = make_route(operation="ENABLE_GOOSE", resource_id_template=GCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(
                operation="ENABLE_GOOSE",
                report_control_block=None,
                goose_control_block="gcbTrip",
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["goose_control_block"] == "gcbTrip"

    def test_sampled_values_control_block_preserved_as_evidence(self) -> None:
        route = make_route(operation="ENABLE_SAMPLED_VALUES", resource_id_template=SVCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(
                operation="ENABLE_SAMPLED_VALUES",
                report_control_block=None,
                sampled_values_control_block="MSVCB01",
            )
        )
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["sampled_values_control_block"] == "MSVCB01"


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_exact_logical_node_route_matches(self) -> None:
        route = make_route(operation="DIRECT_OPERATE", logical_node="CSWI1")
        adapter = make_adapter(route)
        result = adapter.normalize(make_control_op())
        assert result.success

    def test_exact_logical_node_route_does_not_match_other_logical_node(self) -> None:
        route = make_route(operation="DIRECT_OPERATE", logical_node="CSWI1")
        adapter = make_adapter(route)
        result = adapter.normalize(make_control_op(logical_node="CSWI2"))
        assert not result.success

    def test_operation_mismatch_fails_closed(self) -> None:
        route = make_route(operation="READ")
        adapter = make_adapter(route)
        result = adapter.normalize(make_control_op())
        assert not result.success

    def test_first_match_wins(self) -> None:
        first = make_route(operation="READ", action="read", name="first")
        second = make_route(operation="READ", action="discover", name="second")
        adapter = make_adapter(first, second)
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"


# ---------------------------------------------------------------------------
# Resource ID template
# ---------------------------------------------------------------------------


class TestResourceIdTemplate:
    def test_template_fails_closed_when_data_attribute_absent(self) -> None:
        adapter = make_adapter(make_route(resource_id_template=DA_TEMPLATE))
        result = adapter.normalize(make_op(data_attribute=None))
        assert not result.success
        assert result.error is not None

    def test_different_data_objects_produce_different_resource_ids(self) -> None:
        adapter = make_adapter(make_route())
        r1 = adapter.normalize(make_op(data_object="TotW", data_attribute=None))
        r2 = adapter.normalize(make_op(data_object="TotVAr", data_attribute=None))
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.resource_id != r2.request.resource_id

    def test_resource_id_is_deterministic(self) -> None:
        adapter = make_adapter(make_route())
        r1 = adapter.normalize(make_op())
        r2 = adapter.normalize(make_op())
        assert r1.request is not None and r2.request is not None
        assert r1.request.resource_id == r2.request.resource_id


# ---------------------------------------------------------------------------
# Operation validation — fail closed
# ---------------------------------------------------------------------------


class TestOperationValidation:
    def test_empty_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation=""))
        assert not result.success
        assert result.error is not None

    def test_unsupported_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GET_DIRECTORY"))
        assert not result.success
        assert result.error is not None

    def test_lowercase_operation_fails_no_silent_coercion(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="read"))
        assert not result.success

    def test_missing_ied_name_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(ied_name=None))
        assert not result.success
        assert result.error is not None

    def test_empty_ied_name_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(ied_name=""))
        assert not result.success

    def test_read_without_logical_node_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(logical_node=None, data_object=None, data_attribute=None)
        )
        assert not result.success

    def test_write_without_logical_node_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(operation="WRITE", logical_node=None, data_object=None, data_attribute=None)
        )
        assert not result.success

    def test_logical_node_without_logical_device_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(logical_device=None))
        assert not result.success

    def test_data_object_without_logical_node_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(logical_node=None, data_attribute=None))
        assert not result.success

    def test_data_attribute_without_data_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(data_object=None))
        assert not result.success

    def test_control_operation_without_data_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(data_object=None))
        assert not result.success
        assert result.error is not None

    def test_select_without_data_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(
                operation="SELECT", control_model="sbo_with_normal_security", data_object=None
            )
        )
        assert not result.success

    def test_invalid_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_model="fire_and_forget"))
        assert not result.success

    def test_direct_operate_with_sbo_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_model="sbo_with_normal_security"))
        assert not result.success

    def test_select_with_direct_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(operation="SELECT", control_model="direct_with_normal_security")
        )
        assert not result.success

    def test_operate_with_direct_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="direct_with_enhanced_security")
        )
        assert not result.success

    def test_control_on_status_only_point_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_model="status_only"))
        assert not result.success

    def test_invalid_functional_constraint_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(functional_constraint="ZZ"))
        assert not result.success

    def test_enable_reporting_without_rcb_fails(self) -> None:
        route = make_route(operation="ENABLE_REPORTING", resource_id_template=RCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(make_reporting_op(report_control_block=None))
        assert not result.success

    def test_enable_goose_without_gcb_fails(self) -> None:
        route = make_route(operation="ENABLE_GOOSE", resource_id_template=GCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(operation="ENABLE_GOOSE", report_control_block=None)
        )
        assert not result.success

    def test_enable_sampled_values_without_svcb_fails(self) -> None:
        route = make_route(operation="ENABLE_SAMPLED_VALUES", resource_id_template=SVCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_reporting_op(operation="ENABLE_SAMPLED_VALUES", report_control_block=None)
        )
        assert not result.success

    def test_enable_reporting_without_logical_node_fails(self) -> None:
        route = make_route(operation="ENABLE_REPORTING", resource_id_template=RCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(make_reporting_op(logical_node=None))
        assert not result.success

    def test_empty_logical_device_fails_when_present(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(logical_device=""))
        assert not result.success

    def test_non_dict_origin_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(origin="scada-master-1"))
        assert not result.success


# ---------------------------------------------------------------------------
# Protocol field
# ---------------------------------------------------------------------------


class TestProtocolField:
    def test_protocol_is_iec61850(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol == "iec61850"


# ---------------------------------------------------------------------------
# Protocol evidence
# ---------------------------------------------------------------------------


class TestProtocolEvidence:
    def test_protocol_evidence_present(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence is not None

    def test_evidence_protocol_is_iec61850(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.protocol == "iec61850"

    def test_evidence_method_is_operation_name(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="READ"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "READ"

    def test_evidence_path_encodes_hierarchy(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == (
            "ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag"
        )

    def test_evidence_path_encodes_control_block(self) -> None:
        route = make_route(operation="ENABLE_REPORTING", resource_id_template=RCB_TEMPLATE)
        adapter = make_adapter(route)
        result = adapter.normalize(make_reporting_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == (
            "ied:ied-sub1/ld:MEAS/ln:LLN0/rcb:urcbMX01"
        )

    def test_extra_metadata_preserved_in_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"substation": "north-7"}))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["substation"] == "north-7"


# ---------------------------------------------------------------------------
# Subject hint
# ---------------------------------------------------------------------------


class TestSubjectHint:
    def test_subject_hint_none_when_absent(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_forwarded_from_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"subject_hint": "operator@example.internal"}))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"

    def test_origin_is_not_subject_hint(self) -> None:
        """origin is evidence, never identity — it must not leak into
        subject_hint."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(origin={"orCat": "remote-control", "orIdent": "scada-master-1"})
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None


# ---------------------------------------------------------------------------
# Failure cases — fail closed
# ---------------------------------------------------------------------------


class TestFailureCases:
    def test_no_routes_returns_failure(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op())
        assert not result.success
        assert result.request is None
        assert result.error is not None

    def test_normalize_never_raises(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op(operation="GET_DIRECTORY", ied_name=None))
        assert isinstance(result, AdapterResult)
        assert not result.success


# ---------------------------------------------------------------------------
# AdapterResult shape invariants
# ---------------------------------------------------------------------------


class TestAdapterResultShape:
    def test_success_result_shape(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success is True
        assert result.request is not None
        assert result.error is None

    def test_failure_result_shape(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op())
        assert result.success is False
        assert result.request is None
        assert result.error is not None
        assert isinstance(result.error, str)
        assert len(result.error) > 0


# ---------------------------------------------------------------------------
# Adapter ID
# ---------------------------------------------------------------------------


class TestAdapterId:
    def test_adapter_id_accessible(self) -> None:
        config = Iec61850MappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="iec61850-primary")
        adapter = Iec61850Adapter(mapping=config, context=ctx)
        assert adapter.adapter_id == "iec61850-primary"
