"""
Tests for Dnp3Adapter normalization behavior.

Covers read and control normalization, select-before-operate statelessness,
direct operate, enable-unsolicited (subscribe), route matching, template
substitution, operation validation (fail closed), protocol evidence
preservation, and failure result shapes.
"""

from __future__ import annotations

from basis_adapters.dnp3.adapter import Dnp3Adapter
from basis_adapters.dnp3.mapping import Dnp3MappingConfig, Dnp3Operation, Dnp3RouteMapping
from basis_adapters.models import AdapterContext, AdapterResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> Dnp3Operation:
    defaults: dict[str, object] = {
        "operation": "READ",
        "outstation_id": "os-14",
        "point_type": "analog_input",
        "point_index": 3,
    }
    defaults.update(kwargs)
    return Dnp3Operation(**defaults)  # type: ignore[arg-type]


def make_control_op(**kwargs: object) -> Dnp3Operation:
    defaults: dict[str, object] = {
        "operation": "DIRECT_OPERATE",
        "outstation_id": "os-14",
        "point_type": "binary_output",
        "point_index": 7,
        "control_model": "direct_operate",
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


def make_adapter(*routes: Dnp3RouteMapping, adapter_id: str = "test") -> Dnp3Adapter:
    config = Dnp3MappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return Dnp3Adapter(mapping=config, context=ctx)


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

    def test_read_resource_id_includes_outstation_and_point(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/analog_input/3"

    def test_read_binary_input(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op(point_type="binary_input", point_index=12))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/binary_input/12"

    def test_read_counter(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(make_op(point_type="counter", point_index=0))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/counter/0"

    def test_read_object_group_variation_resource_id(self) -> None:
        route = make_route(
            operation="READ",
            resource_id_template=(
                "dnp3:outstation:{outstation_id}/group/{object_group}/variation/{variation}"
            ),
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(point_type=None, point_index=None, object_group=30, variation=5)
        )
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/group/30/variation/5"

    def test_class_level_read_without_point_index_succeeds(self) -> None:
        """Class-level reads need no point index — only control ops require one."""
        route = make_route(
            operation="READ",
            resource_id_template="dnp3:outstation:{outstation_id}/events/class/{event_class}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(point_type=None, point_index=None, object_group=60, event_class=1)
        )
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/events/class/1"

    def test_read_evidence_includes_dnp3_fields(self) -> None:
        adapter = make_adapter(make_route(operation="READ"))
        result = adapter.normalize(
            make_op(object_group=30, variation=5, function_code=1, qualifier=40)
        )
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["operation"] == "READ"
        assert meta["outstation_id"] == "os-14"
        assert meta["object_group"] == 30
        assert meta["variation"] == 5
        assert meta["point_index"] == 3
        assert meta["point_type"] == "analog_input"
        assert meta["function_code"] == 1
        assert meta["qualifier"] == 40


# ---------------------------------------------------------------------------
# Control normalization — select / operate / direct operate
# ---------------------------------------------------------------------------


class TestControlNormalization:
    def test_select_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="SELECT"))
        result = adapter.normalize(
            make_control_op(operation="SELECT", control_model="select_before_operate")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_operate_normalizes_to_execute(self) -> None:
        adapter = make_adapter(make_route(operation="OPERATE"))
        result = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="select_before_operate")
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

    def test_control_normalizes_to_execute_by_default(self) -> None:
        adapter = make_adapter(make_route(operation="CONTROL"))
        result = adapter.normalize(make_control_op(operation="CONTROL", control_model=None))
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_control_route_may_override_to_write(self) -> None:
        """CONTROL may be mapped to write where the command is a value write."""
        adapter = make_adapter(make_route(operation="CONTROL", action="write"))
        result = adapter.normalize(make_control_op(operation="CONTROL", control_model=None))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_binary_output_control_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op())
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/binary_output/7"

    def test_analog_output_command_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(
            make_control_op(point_type="analog_output", point_index=2, value=72.5)
        )
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:os-14/analog_output/2"

    def test_control_evidence_preserves_control_details(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(
            make_control_op(
                object_group=12, variation=1, function_code=5, control_code=65, value="LATCH_ON"
            )
        )
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["control_model"] == "direct_operate"
        assert meta["function_code"] == 5
        assert meta["control_code"] == 65
        assert meta["object_group"] == 12
        assert meta["variation"] == 1
        assert meta["value"] == "LATCH_ON"

    def test_value_never_appears_in_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op(value="LATCH_ON"))
        assert result.success
        assert result.request is not None
        assert "LATCH_ON" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Select-before-operate — stateless, independent normalization
# ---------------------------------------------------------------------------


class TestSelectBeforeOperate:
    def test_select_and_operate_normalize_independently(self) -> None:
        adapter = make_adapter(make_route())
        select = adapter.normalize(
            make_control_op(operation="SELECT", control_model="select_before_operate")
        )
        operate = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="select_before_operate")
        )
        assert select.success and operate.success
        assert select.request is not None and operate.request is not None
        # Same point, same resource — only the operation differs.
        assert select.request.resource_id == operate.request.resource_id
        assert select.request.protocol_evidence.method == "SELECT"
        assert operate.request.protocol_evidence.method == "OPERATE"

    def test_operate_succeeds_without_prior_select(self) -> None:
        """The adapter keeps no sequencing state: an OPERATE normalizes on its
        own. Whether it should be honored without a SELECT is a runtime
        enforcement question, not a normalization question."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(operation="OPERATE", control_model="select_before_operate")
        )
        assert result.success

    def test_repeated_select_produces_identical_output(self) -> None:
        """No state accumulates between calls."""
        adapter = make_adapter(make_route())
        op = make_control_op(operation="SELECT", control_model="select_before_operate")
        r1 = adapter.normalize(op)
        r2 = adapter.normalize(op)
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.to_dict() == r2.request.to_dict()

    def test_evidence_distinguishes_operation_type(self) -> None:
        adapter = make_adapter(make_route())
        select = adapter.normalize(
            make_control_op(operation="SELECT", control_model="select_before_operate")
        )
        direct = adapter.normalize(make_control_op())
        assert select.request is not None and direct.request is not None
        assert select.request.protocol_evidence.metadata["operation"] == "SELECT"
        assert select.request.protocol_evidence.metadata["control_model"] == (
            "select_before_operate"
        )
        assert direct.request.protocol_evidence.metadata["operation"] == "DIRECT_OPERATE"
        assert direct.request.protocol_evidence.metadata["control_model"] == "direct_operate"


# ---------------------------------------------------------------------------
# Enable unsolicited — subscribe semantics
# ---------------------------------------------------------------------------


class TestEnableUnsolicited:
    def test_enable_unsolicited_normalizes_to_subscribe(self) -> None:
        route = make_route(
            operation="ENABLE_UNSOLICITED",
            resource_type="dnp3_event_class",
            resource_id_template="dnp3:outstation:{outstation_id}/events/class/{event_class}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(
                operation="ENABLE_UNSOLICITED",
                point_type=None,
                point_index=None,
                event_class=2,
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"
        assert result.request.resource_id == "dnp3:outstation:os-14/events/class/2"

    def test_event_class_preserved_in_evidence(self) -> None:
        route = make_route(
            operation="ENABLE_UNSOLICITED",
            resource_id_template="dnp3:outstation:{outstation_id}/events/class/{event_class}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(
                operation="ENABLE_UNSOLICITED",
                point_type=None,
                point_index=None,
                event_class=1,
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["event_class"] == 1


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_exact_point_type_route_matches(self) -> None:
        route = make_route(operation="READ", point_type="analog_input")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(point_type="analog_input"))
        assert result.success

    def test_exact_point_type_route_does_not_match_other_point_type(self) -> None:
        route = make_route(operation="READ", point_type="analog_input")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(point_type="binary_input"))
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

    def test_wildcard_point_type_matches_absent_point_type(self) -> None:
        route = make_route(
            operation="READ",
            point_type="*",
            resource_id_template="dnp3:outstation:{outstation_id}/group/{object_group}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(point_type=None, point_index=None, object_group=30))
        assert result.success


# ---------------------------------------------------------------------------
# Resource ID template
# ---------------------------------------------------------------------------


class TestResourceIdTemplate:
    def test_destination_address_in_resource_id(self) -> None:
        route = make_route(
            resource_id_template="dnp3:outstation:{destination_address}/{point_type}/{point_index}"
        )
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(outstation_id=None, destination_address=10))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "dnp3:outstation:10/analog_input/3"

    def test_template_fails_closed_when_outstation_id_absent(self) -> None:
        route = make_route()  # template references {outstation_id}
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(outstation_id=None, destination_address=10))
        assert not result.success
        assert result.error is not None

    def test_template_fails_closed_when_variation_absent(self) -> None:
        route = make_route(
            operation="READ",
            resource_id_template=(
                "dnp3:outstation:{outstation_id}/group/{object_group}/variation/{variation}"
            ),
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(point_type=None, point_index=None, object_group=30, variation=None)
        )
        assert not result.success

    def test_different_points_produce_different_resource_ids(self) -> None:
        adapter = make_adapter(make_route())
        r1 = adapter.normalize(make_op(point_index=1))
        r2 = adapter.normalize(make_op(point_index=2))
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
        result = adapter.normalize(make_op(operation="COLD_RESTART"))
        assert not result.success
        assert result.error is not None

    def test_lowercase_operation_fails_no_silent_coercion(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="read"))
        assert not result.success

    def test_missing_target_identity_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(outstation_id=None, destination_address=None))
        assert not result.success
        assert result.error is not None

    def test_empty_outstation_id_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(outstation_id=""))
        assert not result.success

    def test_destination_address_out_of_range_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(destination_address=65536))
        assert not result.success

    def test_negative_source_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(source_address=-1))
        assert not result.success

    def test_boolean_destination_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(outstation_id=None, destination_address=True))
        assert not result.success

    def test_invalid_object_group_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(object_group=256))
        assert not result.success

    def test_invalid_variation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(object_group=30, variation=-2))
        assert not result.success

    def test_variation_without_object_group_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(object_group=None, variation=5))
        assert not result.success

    def test_negative_point_index_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(point_index=-1))
        assert not result.success

    def test_invalid_point_type_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(point_type="thermocouple"))
        assert not result.success

    def test_invalid_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_model="fire_and_forget"))
        assert not result.success

    def test_direct_operate_with_sbo_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_model="select_before_operate"))
        assert not result.success

    def test_select_with_direct_operate_control_model_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(operation="SELECT", control_model="direct_operate")
        )
        assert not result.success

    def test_control_operation_without_point_index_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(point_index=None))
        assert not result.success
        assert result.error is not None

    def test_select_without_point_index_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_control_op(
                operation="SELECT", control_model="select_before_operate", point_index=None
            )
        )
        assert not result.success

    def test_invalid_event_class_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(event_class=4))
        assert not result.success

    def test_invalid_function_code_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(function_code=300))
        assert not result.success

    def test_invalid_qualifier_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(qualifier=-1))
        assert not result.success

    def test_invalid_control_code_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_control_op(control_code=999))
        assert not result.success

    def test_empty_master_id_fails_when_present(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(master_id=""))
        assert not result.success


# ---------------------------------------------------------------------------
# Protocol field
# ---------------------------------------------------------------------------


class TestProtocolField:
    def test_protocol_is_dnp3(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol == "dnp3"


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

    def test_evidence_protocol_is_dnp3(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.protocol == "dnp3"

    def test_evidence_method_is_operation_name(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="READ"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "READ"

    def test_evidence_path_encodes_outstation_and_point(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "outstation:os-14/analog_input/3"

    def test_evidence_path_uses_group_for_object_reads(self) -> None:
        route = make_route(
            operation="READ",
            resource_id_template="dnp3:outstation:{outstation_id}/group/{object_group}",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(point_type=None, point_index=None, object_group=30, variation=5)
        )
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "outstation:os-14/group/30/variation/5"

    def test_evidence_metadata_contains_addresses(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(source_address=1, destination_address=10))
        assert result.success
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["source_address"] == 1
        assert meta["destination_address"] == 10

    def test_evidence_metadata_contains_master_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(master_id="master-1"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["master_id"] == "master-1"

    def test_evidence_metadata_contains_value(self) -> None:
        adapter = make_adapter(make_route(operation="DIRECT_OPERATE"))
        result = adapter.normalize(make_control_op(value=72.5))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5

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

    def test_master_id_is_not_subject_hint(self) -> None:
        """master_id is evidence, never identity — it must not leak into
        subject_hint."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(master_id="master-1"))
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
        result = adapter.normalize(
            make_op(operation="COLD_RESTART", outstation_id=None, point_index=-5)
        )
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
        config = Dnp3MappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="dnp3-primary")
        adapter = Dnp3Adapter(mapping=config, context=ctx)
        assert adapter.adapter_id == "dnp3-primary"
