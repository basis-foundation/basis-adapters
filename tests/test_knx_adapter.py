"""
KNX adapter normalization tests.

These tests verify that:
1. Read normalization: GROUP_VALUE_READ maps to "read", the resource ID
   includes the KNX group address, and evidence includes KNX fields.
2. Write normalization: GROUP_VALUE_WRITE maps to "write", the value is
   preserved as evidence and never appears in the resource ID.
3. Response normalization: GROUP_VALUE_RESPONSE maps to "read".
4. Observe normalization: OBSERVE maps to "subscribe" with group address and
   DPT context preserved as evidence, and no live-monitoring implication.
5. Validation fails closed for missing/unsupported operations, missing or
   malformed group addresses, malformed individual/device addresses,
   malformed datapoint types, invalid priorities, and out-of-range topology
   evidence.
6. Action overrides and route precedence behave as configured.
"""

from __future__ import annotations

import json
from pathlib import Path

from basis_adapters.knx.adapter import KnxAdapter
from basis_adapters.knx.mapping import (
    KnxMappingConfig,
    KnxOperation,
    KnxRouteMapping,
)
from basis_adapters.models import AdapterContext

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_MAPPING = REPO_ROOT / "examples" / "knx" / "mapping.example.json"


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


def make_adapter(*routes: KnxRouteMapping, adapter_id: str = "knx-test") -> KnxAdapter:
    config = KnxMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return KnxAdapter(mapping=config, context=ctx)


def make_op(**kwargs: object) -> KnxOperation:
    defaults: dict[str, object] = {
        "operation": "GROUP_VALUE_READ",
        "group_address": "1/2/3",
    }
    defaults.update(kwargs)
    return KnxOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Read normalization
# ---------------------------------------------------------------------------


class TestReadNormalization:
    def test_group_value_read_maps_to_read(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_resource_id_includes_group_address(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.request is not None
        assert result.request.resource_id == "knx:group:1/2/3"
        assert "1/2/3" in result.request.resource_id

    def test_evidence_includes_knx_fields(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                individual_address="1.1.5",
                datapoint_type="1.001",
                priority="normal",
            )
        )
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.protocol == "knx"
        assert ev.method == "GROUP_VALUE_READ"
        assert ev.path == "group:1/2/3"
        assert ev.metadata["operation"] == "GROUP_VALUE_READ"
        assert ev.metadata["group_address"] == "1/2/3"
        assert ev.metadata["individual_address"] == "1.1.5"
        assert ev.metadata["datapoint_type"] == "1.001"
        assert ev.metadata["priority"] == "normal"

    def test_protocol_is_knx(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.request is not None
        assert result.request.protocol == "knx"

    def test_two_level_group_address_normalizes(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(group_address="1/200"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "knx:group:1/200"

    def test_free_style_group_address_normalizes(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(group_address="2563"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "knx:group:2563"


# ---------------------------------------------------------------------------
# Write normalization
# ---------------------------------------------------------------------------


class TestWriteNormalization:
    def test_group_value_write_maps_to_write(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE", value=True))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_value_preserved_as_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(operation="GROUP_VALUE_WRITE", value=21.5, datapoint_type="9.001")
        )
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] == 21.5

    def test_value_never_in_resource_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE", value=21.5))
        assert result.request is not None
        assert "21.5" not in result.request.resource_id

    def test_communication_object_in_resource_id_when_templated(self) -> None:
        adapter = make_adapter(
            make_route(
                resource_id_template="knx:group:{group_address}/object:{communication_object}"
            )
        )
        result = adapter.normalize(
            make_op(operation="GROUP_VALUE_WRITE", communication_object=4, value=True)
        )
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "knx:group:1/2/3/object:4"

    def test_evidence_path_includes_communication_object(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE", communication_object=4))
        assert result.request is not None
        assert result.request.protocol_evidence.path == "group:1/2/3/object:4"


# ---------------------------------------------------------------------------
# Response normalization
# ---------------------------------------------------------------------------


class TestResponseNormalization:
    def test_group_value_response_maps_to_read(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(operation="GROUP_VALUE_RESPONSE", value=False, datapoint_type="1.001")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_response_value_is_evidence_only(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="GROUP_VALUE_RESPONSE", value=False))
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value"] is False
        assert "False" not in result.request.resource_id


# ---------------------------------------------------------------------------
# Observe / subscribe normalization
# ---------------------------------------------------------------------------


class TestObserveNormalization:
    def test_observe_maps_to_subscribe(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="OBSERVE"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"

    def test_observe_preserves_group_address_and_dpt_context(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(operation="OBSERVE", group_address="2/0/14", datapoint_type="9.001")
        )
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["group_address"] == "2/0/14"
        assert ev.metadata["datapoint_type"] == "9.001"

    def test_observe_implies_no_live_bus_monitoring(self) -> None:
        """Normalizing OBSERVE is a pure function — the adapter retains no
        bus state and observing once changes nothing about later calls."""
        adapter = make_adapter(make_route())
        op = make_op(operation="OBSERVE")
        before = adapter.normalize(make_op())
        adapter.normalize(op)
        after = adapter.normalize(make_op())
        assert before.request is not None and after.request is not None
        assert before.request.to_dict() == after.request.to_dict()


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
        result = adapter.normalize(make_op(operation="DEVICE_DESCRIPTOR_READ"))
        assert not result.success

    def test_lowercase_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="group_value_read"))
        assert not result.success

    def test_missing_group_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(group_address=None))
        assert not result.success
        assert result.error is not None
        assert "group_address" in result.error

    def test_empty_group_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(group_address="  "))
        assert not result.success

    def test_invalid_group_address_format_fails(self) -> None:
        adapter = make_adapter(make_route())
        for bad in ("1/8/3", "32/2/3", "1/2/256", "a/b/c", "1.2.3", "1/2/3/4", "65536"):
            result = adapter.normalize(make_op(group_address=bad))
            assert not result.success, f"group address {bad!r} should fail closed"

    def test_invalid_individual_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        for bad in ("16.1.5", "1.16.5", "1.1.256", "1.1", "1/1/5", "x.y.z"):
            result = adapter.normalize(make_op(individual_address=bad))
            assert not result.success, f"individual address {bad!r} should fail closed"

    def test_invalid_device_address_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(device_address="99.99.999"))
        assert not result.success

    def test_malformed_datapoint_type_fails(self) -> None:
        adapter = make_adapter(make_route())
        for bad in ("dpt-1", "1_001", "switching", "1."):
            result = adapter.normalize(make_op(datapoint_type=bad))
            assert not result.success, f"datapoint type {bad!r} should fail closed"

    def test_invalid_priority_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(priority="critical"))
        assert not result.success

    def test_non_integer_communication_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(communication_object="four"))
        assert not result.success

    def test_boolean_communication_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(communication_object=True))
        assert not result.success

    def test_negative_communication_object_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(communication_object=-1))
        assert not result.success

    def test_out_of_range_topology_fields_fail(self) -> None:
        adapter = make_adapter(make_route())
        for kwargs in ({"area": 16}, {"line": 16}, {"device": 256}, {"area": -1}):
            result = adapter.normalize(make_op(**kwargs))
            assert not result.success, f"topology {kwargs!r} should fail closed"

    def test_empty_payload_type_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(payload_type=" "))
        assert not result.success

    def test_unmatched_operation_fails(self) -> None:
        adapter = make_adapter(make_route(operation="GROUP_VALUE_WRITE"))
        result = adapter.normalize(make_op(operation="GROUP_VALUE_READ"))
        assert not result.success

    def test_template_referencing_absent_field_fails(self) -> None:
        adapter = make_adapter(
            make_route(
                resource_id_template="knx:device:{device_address}/object:{communication_object}"
            )
        )
        result = adapter.normalize(make_op())  # no device_address / comm object
        assert not result.success


# ---------------------------------------------------------------------------
# Route configuration behavior
# ---------------------------------------------------------------------------


class TestRouteConfiguration:
    def test_action_override_applies(self) -> None:
        adapter = make_adapter(make_route(operation="GROUP_VALUE_WRITE", action="control"))
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "control"

    def test_specific_route_takes_precedence(self) -> None:
        specific = make_route(
            operation="GROUP_VALUE_WRITE",
            group_address="1/2/3",
            resource_type="knx_lighting_scene",
            name="specific",
        )
        broad = make_route(name="broad")
        adapter = make_adapter(specific, broad)
        result = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE"))
        assert result.request is not None
        assert result.request.resource_type == "knx_lighting_scene"

    def test_example_mapping_file_loads_and_normalizes(self) -> None:
        with EXAMPLE_MAPPING.open() as f:
            config = KnxMappingConfig.from_dict(json.load(f))
        adapter = KnxAdapter(mapping=config, context=AdapterContext(adapter_id="knx-example"))

        read = adapter.normalize(make_op())
        assert read.success and read.request is not None
        assert read.request.action == "read"

        write = adapter.normalize(make_op(operation="GROUP_VALUE_WRITE", value=True))
        assert write.success and write.request is not None
        assert write.request.action == "write"

        response = adapter.normalize(make_op(operation="GROUP_VALUE_RESPONSE", value=True))
        assert response.success and response.request is not None
        assert response.request.action == "read"

        observe = adapter.normalize(make_op(operation="OBSERVE", group_address="2/0/14"))
        assert observe.success and observe.request is not None
        assert observe.request.action == "subscribe"

    def test_adapter_id_property(self) -> None:
        adapter = make_adapter(make_route(), adapter_id="knx-primary")
        assert adapter.adapter_id == "knx-primary"

    def test_subject_hint_forwarded_from_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"subject_hint": "operator@example.internal"}))
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"

    def test_extra_metadata_merged_into_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"source_interface": "tunnel-1"}))
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["source_interface"] == "tunnel-1"
