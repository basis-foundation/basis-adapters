"""
Niagara adapter normalization tests.

These tests verify that:
1. Read normalization: READ_COMPONENT/READ_POINT/READ_SLOT/READ_HISTORY/
   READ_ALARM/READ_SCHEDULE map to "read", resource IDs include station and
   target semantics, and evidence includes Niagara fields.
2. Write normalization: WRITE_POINT/WRITE_SLOT/UPDATE_SCHEDULE map to
   "write", values are preserved as evidence and never appear in resource
   IDs.
3. Execute normalization: ACK_ALARM, INVOKE_ACTION, COMMAND_POINT,
   OVERRIDE_POINT, and RELEASE_OVERRIDE map to "execute".
4. Browse normalization: BROWSE/RESOLVE_ORD/LIST_CHILDREN map to "browse",
   with ORDs preserved exactly.
5. Subscribe normalization: SUBSCRIBE_POINT/SUBSCRIBE_ALARM/
   SUBSCRIBE_HISTORY map to "subscribe".
6. Identity boundary: niagara_user and niagara_role are evidence only —
   never subject_hint.
7. Validation fails closed for missing/unsupported operations, missing
   station or target identifiers, and empty optional fields.
8. Action overrides and route precedence behave as configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from basis_adapters.models import AdapterContext
from basis_adapters.niagara.adapter import NiagaraAdapter
from basis_adapters.niagara.mapping import (
    NiagaraMappingConfig,
    NiagaraOperation,
    NiagaraRouteMapping,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_MAPPING = REPO_ROOT / "examples" / "niagara" / "mapping.example.json"

EXAMPLE_ORD = "station:|slot:/Drivers/BacnetNetwork/AHU1"


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


def make_adapter(*routes: NiagaraRouteMapping, adapter_id: str = "niagara-test") -> NiagaraAdapter:
    config = NiagaraMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return NiagaraAdapter(mapping=config, context=ctx)


def make_op(**kwargs: object) -> NiagaraOperation:
    defaults: dict[str, object] = {
        "operation": "READ_POINT",
        "station": "station-east",
        "point": "AHU1-SupplyTemp",
    }
    defaults.update(kwargs)
    return NiagaraOperation(**defaults)  # type: ignore[arg-type]


def example_adapter() -> NiagaraAdapter:
    with EXAMPLE_MAPPING.open() as f:
        config = NiagaraMappingConfig.from_dict(json.load(f))
    return NiagaraAdapter(mapping=config, context=AdapterContext(adapter_id="niagara-example"))


# ---------------------------------------------------------------------------
# Read normalization
# ---------------------------------------------------------------------------


class TestReadNormalization:
    def test_read_point_maps_to_read(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_resource_id_includes_station_and_point(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.request is not None
        assert result.request.resource_id == "niagara:station:station-east/point:AHU1-SupplyTemp"
        assert "station-east" in result.request.resource_id
        assert "AHU1-SupplyTemp" in result.request.resource_id

    def test_read_component_maps_to_read(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/component:{component}")
        )
        result = adapter.normalize(
            make_op(operation="READ_COMPONENT", point=None, component="AHU1")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"
        assert result.request.resource_id == "niagara:station:station-east/component:AHU1"

    def test_read_slot_maps_to_read(self) -> None:
        adapter = make_adapter(
            make_route(
                resource_id_template=("niagara:station:{station}/component:{component}/slot:{slot}")
            )
        )
        result = adapter.normalize(
            make_op(operation="READ_SLOT", point=None, component="AHU1", slot="status")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"
        assert (
            result.request.resource_id == "niagara:station:station-east/component:AHU1/slot:status"
        )

    def test_read_history_maps_to_read(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/history:{history}")
        )
        result = adapter.normalize(
            make_op(operation="READ_HISTORY", point=None, history="AHU1-SupplyTemp-History")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_alarm_maps_to_read(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/alarm:{alarm}")
        )
        result = adapter.normalize(
            make_op(operation="READ_ALARM", point=None, alarm="AHU1-HighSupplyTemp")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_schedule_maps_to_read(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/schedule:{schedule}")
        )
        result = adapter.normalize(
            make_op(operation="READ_SCHEDULE", point=None, schedule="OfficeHours")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_evidence_includes_niagara_fields(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                host="supervisor-1.example.internal",
                ord=EXAMPLE_ORD,
                point_type="NumericPoint",
                facet="units=°F",
                category="HVAC",
                baja_type="control:NumericPoint",
                nav_path="/Drivers/BacnetNetwork/AHU1/points/SupplyTemp",
            )
        )
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.protocol == "niagara"
        assert ev.method == "READ_POINT"
        assert ev.metadata["operation"] == "READ_POINT"
        assert ev.metadata["station"] == "station-east"
        assert ev.metadata["host"] == "supervisor-1.example.internal"
        assert ev.metadata["ord"] == EXAMPLE_ORD
        assert ev.metadata["point"] == "AHU1-SupplyTemp"
        assert ev.metadata["point_type"] == "NumericPoint"
        assert ev.metadata["facet"] == "units=°F"
        assert ev.metadata["category"] == "HVAC"
        assert ev.metadata["baja_type"] == "control:NumericPoint"
        assert ev.metadata["nav_path"] == "/Drivers/BacnetNetwork/AHU1/points/SupplyTemp"

    def test_protocol_is_niagara(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.request is not None
        assert result.request.protocol == "niagara"


# ---------------------------------------------------------------------------
# Write normalization
# ---------------------------------------------------------------------------


class TestWriteNormalization:
    def test_write_point_maps_to_write(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="WRITE_POINT", value=72.5))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_write_slot_maps_to_write(self) -> None:
        adapter = make_adapter(
            make_route(
                resource_id_template=("niagara:station:{station}/component:{component}/slot:{slot}")
            )
        )
        result = adapter.normalize(
            make_op(operation="WRITE_SLOT", point=None, component="AHU1", slot="setpoint", value=70)
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_update_schedule_maps_to_write(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/schedule:{schedule}")
        )
        result = adapter.normalize(
            make_op(operation="UPDATE_SCHEDULE", point=None, schedule="OfficeHours")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_value_preserved_as_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="WRITE_POINT", value=72.5))
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 72.5

    def test_value_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="WRITE_POINT", value=72.5))
        assert result.request is not None
        assert "72.5" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Execute normalization
# ---------------------------------------------------------------------------


class TestExecuteNormalization:
    def test_invoke_action_maps_to_execute(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/component:{component}")
        )
        result = adapter.normalize(make_op(operation="INVOKE_ACTION", point=None, component="AHU1"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_command_point_maps_to_execute(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="COMMAND_POINT", value="auto"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_override_point_maps_to_execute(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                operation="OVERRIDE_POINT",
                value=68.0,
                metadata={"override_level": 8, "override_duration_minutes": 60},
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_release_override_maps_to_execute(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="RELEASE_OVERRIDE"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_ack_alarm_maps_to_execute(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/alarm:{alarm}")
        )
        result = adapter.normalize(
            make_op(operation="ACK_ALARM", point=None, alarm="AHU1-HighSupplyTemp")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"

    def test_override_metadata_preserved_as_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                operation="OVERRIDE_POINT",
                value=68.0,
                metadata={"override_level": 8, "override_duration_minutes": 60},
            )
        )
        assert result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["value"] == 68.0
        assert meta["override_level"] == 8
        assert meta["override_duration_minutes"] == 60
        assert "68.0" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Browse normalization
# ---------------------------------------------------------------------------


class TestBrowseNormalization:
    def test_browse_maps_to_browse(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        result = adapter.normalize(make_op(operation="BROWSE", point=None))
        assert result.success
        assert result.request is not None
        assert result.request.action == "browse"

    def test_resolve_ord_maps_to_browse(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/ord:{ord}")
        )
        result = adapter.normalize(make_op(operation="RESOLVE_ORD", point=None, ord=EXAMPLE_ORD))
        assert result.success
        assert result.request is not None
        assert result.request.action == "browse"

    def test_list_children_maps_to_browse(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/component:{component}")
        )
        result = adapter.normalize(make_op(operation="LIST_CHILDREN", point=None, component="AHU1"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "browse"

    def test_ord_preserved_exactly(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/ord:{ord}")
        )
        result = adapter.normalize(make_op(operation="RESOLVE_ORD", point=None, ord=EXAMPLE_ORD))
        assert result.request is not None
        assert result.request.resource_id == f"niagara:station:station-east/ord:{EXAMPLE_ORD}"
        assert result.request.protocol_evidence.metadata["ord"] == EXAMPLE_ORD


# ---------------------------------------------------------------------------
# Subscribe normalization
# ---------------------------------------------------------------------------


class TestSubscribeNormalization:
    def test_subscribe_point_maps_to_subscribe(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="SUBSCRIBE_POINT"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"

    def test_subscribe_alarm_maps_to_subscribe(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/alarm:{alarm}")
        )
        result = adapter.normalize(
            make_op(operation="SUBSCRIBE_ALARM", point=None, alarm="AHU1-HighSupplyTemp")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"

    def test_subscribe_history_maps_to_subscribe(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/history:{history}")
        )
        result = adapter.normalize(
            make_op(operation="SUBSCRIBE_HISTORY", point=None, history="AHU1-SupplyTemp-History")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"


# ---------------------------------------------------------------------------
# Identity boundary — niagara_user / niagara_role are evidence only
# ---------------------------------------------------------------------------


class TestIdentityBoundary:
    def test_niagara_user_preserved_as_evidence_only(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_user="operator1"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["niagara_user"] == "operator1"

    def test_niagara_role_preserved_as_evidence_only(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_role="operator"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["niagara_role"] == "operator"

    def test_niagara_user_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_user="operator1"))
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_niagara_role_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(niagara_role="operator"))
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
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"


# ---------------------------------------------------------------------------
# Validation — fail closed
# ---------------------------------------------------------------------------


class TestValidationFailClosed:
    def test_missing_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation=""))
        assert not result.success
        assert result.error is not None

    def test_unsupported_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="FOX_LOGIN"))
        assert not result.success

    def test_lowercase_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="read_point"))
        assert not result.success

    def test_missing_station_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(station=None))
        assert not result.success
        assert result.error is not None
        assert "station" in result.error

    def test_empty_station_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(station="  "))
        assert not result.success

    def test_point_operations_require_point(self) -> None:
        adapter = make_adapter(make_route())
        for operation in (
            "READ_POINT",
            "WRITE_POINT",
            "COMMAND_POINT",
            "OVERRIDE_POINT",
            "RELEASE_OVERRIDE",
            "SUBSCRIBE_POINT",
        ):
            result = adapter.normalize(make_op(operation=operation, point=None))
            assert not result.success, f"{operation} without point should fail closed"

    def test_alarm_operations_require_alarm(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        for operation in ("READ_ALARM", "ACK_ALARM", "SUBSCRIBE_ALARM"):
            result = adapter.normalize(make_op(operation=operation, point=None))
            assert not result.success, f"{operation} without alarm should fail closed"

    def test_history_operations_require_history(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        for operation in ("READ_HISTORY", "SUBSCRIBE_HISTORY"):
            result = adapter.normalize(make_op(operation=operation, point=None))
            assert not result.success, f"{operation} without history should fail closed"

    def test_schedule_operations_require_schedule(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        for operation in ("READ_SCHEDULE", "UPDATE_SCHEDULE"):
            result = adapter.normalize(make_op(operation=operation, point=None))
            assert not result.success, f"{operation} without schedule should fail closed"

    def test_slot_operations_require_slot(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        for operation in ("READ_SLOT", "WRITE_SLOT"):
            result = adapter.normalize(make_op(operation=operation, point=None, component="AHU1"))
            assert not result.success, f"{operation} without slot should fail closed"

    def test_read_component_requires_component(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        result = adapter.normalize(make_op(operation="READ_COMPONENT", point=None))
        assert not result.success

    def test_resolve_ord_requires_ord(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        result = adapter.normalize(make_op(operation="RESOLVE_ORD", point=None))
        assert not result.success

    def test_invoke_action_requires_a_target(self) -> None:
        adapter = make_adapter(make_route(resource_id_template="niagara:station:{station}"))
        result = adapter.normalize(make_op(operation="INVOKE_ACTION", point=None))
        assert not result.success

    def test_empty_optional_string_fields_fail(self) -> None:
        adapter = make_adapter(make_route())
        for kwargs in (
            {"ord": " "},
            {"host": ""},
            {"niagara_user": " "},
            {"niagara_role": ""},
            {"facet": " "},
            {"baja_type": ""},
        ):
            result = adapter.normalize(make_op(**kwargs))
            assert not result.success, f"empty field {kwargs!r} should fail closed"

    def test_unmatched_operation_fails(self) -> None:
        adapter = make_adapter(make_route(operation="WRITE_POINT"))
        result = adapter.normalize(make_op(operation="READ_POINT"))
        assert not result.success

    def test_template_referencing_absent_field_fails(self) -> None:
        adapter = make_adapter(
            make_route(resource_id_template="niagara:station:{station}/ord:{ord}")
        )
        result = adapter.normalize(make_op())  # no ord
        assert not result.success


# ---------------------------------------------------------------------------
# Route configuration behavior
# ---------------------------------------------------------------------------


class TestRouteConfiguration:
    def test_action_override_applies(self) -> None:
        adapter = make_adapter(
            make_route(
                operation="ACK_ALARM",
                action="write",
                resource_id_template="niagara:station:{station}/alarm:{alarm}",
            )
        )
        result = adapter.normalize(
            make_op(operation="ACK_ALARM", point=None, alarm="AHU1-HighSupplyTemp")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_specific_route_takes_precedence(self) -> None:
        specific = make_route(
            operation="READ_POINT",
            station="station-east",
            resource_type="niagara_critical_point",
            name="specific",
        )
        broad = make_route(name="broad")
        adapter = make_adapter(specific, broad)
        result = adapter.normalize(make_op())
        assert result.request is not None
        assert result.request.resource_type == "niagara_critical_point"

    def test_station_matched_verbatim(self) -> None:
        adapter = make_adapter(make_route(station="station-east"))
        result = adapter.normalize(make_op(station="station-west"))
        assert not result.success

    def test_example_mapping_file_loads_and_normalizes(self) -> None:
        adapter = example_adapter()

        read = adapter.normalize(make_op())
        assert read.success and read.request is not None
        assert read.request.action == "read"

        write = adapter.normalize(make_op(operation="WRITE_POINT", value=70))
        assert write.success and write.request is not None
        assert write.request.action == "write"

        override = adapter.normalize(make_op(operation="OVERRIDE_POINT", value=68.0))
        assert override.success and override.request is not None
        assert override.request.action == "execute"

        ack = adapter.normalize(
            make_op(operation="ACK_ALARM", point=None, alarm="AHU1-HighSupplyTemp")
        )
        assert ack.success and ack.request is not None
        assert ack.request.action == "execute"

        resolve = adapter.normalize(make_op(operation="RESOLVE_ORD", point=None, ord=EXAMPLE_ORD))
        assert resolve.success and resolve.request is not None
        assert resolve.request.action == "browse"

        browse = adapter.normalize(make_op(operation="BROWSE", point=None))
        assert browse.success and browse.request is not None
        assert browse.request.action == "browse"

        children = adapter.normalize(
            make_op(operation="LIST_CHILDREN", point=None, component="AHU1")
        )
        assert children.success and children.request is not None
        assert children.request.action == "browse"

        subscribe = adapter.normalize(make_op(operation="SUBSCRIBE_POINT"))
        assert subscribe.success and subscribe.request is not None
        assert subscribe.request.action == "subscribe"

    def test_adapter_id_property(self) -> None:
        adapter = make_adapter(make_route(), adapter_id="niagara-primary")
        assert adapter.adapter_id == "niagara-primary"

    def test_extra_metadata_merged_into_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"source_interface": "supervisor-1"}))
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["source_interface"] == "supervisor-1"
