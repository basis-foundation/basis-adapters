"""
Cross-protocol normalization contract tests — Phases 5, 7, 10, 11, 12, and 13.

These tests prove that:
1. REST normalized requests serialize to the canonical shape.
2. BACnet normalized requests serialize to the canonical shape.
3. Modbus normalized requests serialize to the canonical shape.
4. OPC UA normalized requests serialize to the canonical shape.
5. MQTT normalized requests serialize to the canonical shape.
6. DNP3 normalized requests serialize to the canonical shape.
7. IEC 61850 normalized requests serialize to the canonical shape.
8. KNX normalized requests serialize to the canonical shape.
9. Required fields are present for all eight protocols.
10. Protocol-specific evidence is nested under "protocol_evidence".
11. No authorization decision field is present in the output.
12. No resolved subject identity field is present (only the unverified hint).
13. No gateway transport code is invoked.
14. No basis_core import exists anywhere in basis_adapters.
15. REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, and KNX outputs
    share exactly the same top-level field set.
16. Serialization is deterministic.

The contract document is: docs/contracts/normalization-contract.md
The JSON Schema is: schemas/normalized-authorization-request.schema.json
"""

from __future__ import annotations

import json
import sys
from typing import Any

from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import BacnetMappingConfig, BacnetOperation, BacnetRouteMapping
from basis_adapters.dnp3.adapter import Dnp3Adapter
from basis_adapters.dnp3.mapping import Dnp3MappingConfig, Dnp3Operation, Dnp3RouteMapping
from basis_adapters.iec61850.adapter import Iec61850Adapter
from basis_adapters.iec61850.mapping import (
    Iec61850MappingConfig,
    Iec61850Operation,
    Iec61850RouteMapping,
)
from basis_adapters.knx.adapter import KnxAdapter
from basis_adapters.knx.mapping import KnxMappingConfig, KnxOperation, KnxRouteMapping
from basis_adapters.modbus.adapter import ModbusAdapter
from basis_adapters.modbus.mapping import ModbusMappingConfig, ModbusOperation, ModbusRouteMapping
from basis_adapters.models import (
    AdapterContext,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.mqtt.adapter import MqttAdapter
from basis_adapters.mqtt.mapping import MqttMappingConfig, MqttOperation, MqttRouteMapping
from basis_adapters.opcua.adapter import OpcuaAdapter
from basis_adapters.opcua.mapping import OpcuaMappingConfig, OpcuaOperation, OpcuaRouteMapping
from basis_adapters.rest.adapter import RestAdapter
from basis_adapters.rest.mapping import RestMappingConfig, RouteMapping

# ---------------------------------------------------------------------------
# Canonical field set — the contract defines exactly these top-level keys.
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)

CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})

# Fields that must never appear in the serialized output.
FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        # Decision fields — adapters do not produce decisions
        "decision",
        "allow",
        "deny",
        "permitted",
        "authorized",
        "result",
        # Verified identity — the gateway owns identity resolution
        "subject",
        "principal",
        "identity",
        "user_id",
        "verified_subject",
    }
)


# ---------------------------------------------------------------------------
# Fixtures — minimal but realistic adapter configurations
# ---------------------------------------------------------------------------


def _rest_adapter() -> RestAdapter:
    route = RouteMapping(
        methods=["GET", "HEAD"],
        path_pattern="/devices/{device_id}/points/{point_id}",
        resource_type="point",
        resource_id_template="devices/{device_id}/points/{point_id}",
        name="read-point",
    )
    config = RestMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="rest-normalization-test")
    return RestAdapter(mapping=config, context=ctx)


def _rest_operation(subject_hint: str | None = None) -> ProtocolOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return ProtocolOperation(
        protocol="rest",
        method="GET",
        path="/devices/ahu-1/points/supply-temp",
        metadata=meta,
    )


def _bacnet_adapter() -> BacnetAdapter:
    route = BacnetRouteMapping(
        service="ReadProperty",
        object_type="analogInput",
        property_identifier="presentValue",
        action="read",
        resource_type="point",
        resource_id_template="device-{device_id}/point/{object_type}:{object_instance}:{property_identifier}",
        name="read-analog-point",
    )
    config = BacnetMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="bacnet-normalization-test")
    return BacnetAdapter(mapping=config, context=ctx)


def _bacnet_operation(subject_hint: str | None = None) -> BacnetOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return BacnetOperation(
        service="ReadProperty",
        object_type="analogInput",
        object_instance=1,
        property_identifier="presentValue",
        device_id="device-42",
        metadata=meta,
    )


def _rest_normalized() -> NormalizedAuthorizationRequest:
    adapter = _rest_adapter()
    result = adapter.normalize(_rest_operation())
    assert result.success, f"REST normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _bacnet_normalized() -> NormalizedAuthorizationRequest:
    adapter = _bacnet_adapter()
    result = adapter.normalize(_bacnet_operation())
    assert result.success, f"BACnet normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _modbus_adapter() -> ModbusAdapter:
    route = ModbusRouteMapping(
        function="ReadHoldingRegisters",
        register_type="holding_register",
        action="read",
        resource_type="modbus_register",
        resource_id_template="unit:{unit_id}:{register_type}:{address}",
        name="read-holding",
    )
    config = ModbusMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="modbus-normalization-test")
    return ModbusAdapter(mapping=config, context=ctx)


def _modbus_operation(subject_hint: str | None = None) -> ModbusOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return ModbusOperation(
        function="ReadHoldingRegisters",
        unit_id=1,
        address=40001,
        quantity=1,
        metadata=meta,
    )


def _modbus_normalized() -> NormalizedAuthorizationRequest:
    adapter = _modbus_adapter()
    result = adapter.normalize(_modbus_operation())
    assert result.success, f"Modbus normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _opcua_adapter() -> OpcuaAdapter:
    route = OpcuaRouteMapping(
        service="Read",
        attribute_id="Value",
        action="read",
        resource_type="opcua_node",
        resource_id_template="{node_id}:{attribute_id}",
        name="read-node-value",
    )
    config = OpcuaMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="opcua-normalization-test")
    return OpcuaAdapter(mapping=config, context=ctx)


def _opcua_operation(subject_hint: str | None = None) -> OpcuaOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return OpcuaOperation(
        service="Read",
        node_id="ns=2;s=Building.AHU1.SupplyTemp",
        attribute_id="Value",
        namespace_index=2,
        metadata=meta,
    )


def _opcua_normalized() -> NormalizedAuthorizationRequest:
    adapter = _opcua_adapter()
    result = adapter.normalize(_opcua_operation())
    assert result.success, f"OPC UA normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _mqtt_adapter() -> MqttAdapter:
    route = MqttRouteMapping(
        operation="PUBLISH",
        topic="*",
        action="write",
        resource_type="mqtt_topic",
        resource_id_template="mqtt:{topic}",
        name="publish-any",
    )
    config = MqttMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="mqtt-normalization-test")
    return MqttAdapter(mapping=config, context=ctx)


def _mqtt_operation(subject_hint: str | None = None) -> MqttOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return MqttOperation(
        operation="PUBLISH",
        topic="building/ahu-1/setpoint",
        client_id="bms-controller-7",
        qos=1,
        payload_type="json",
        metadata=meta,
    )


def _mqtt_normalized() -> NormalizedAuthorizationRequest:
    adapter = _mqtt_adapter()
    result = adapter.normalize(_mqtt_operation())
    assert result.success, f"MQTT normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _dnp3_adapter() -> Dnp3Adapter:
    route = Dnp3RouteMapping(
        operation="READ",
        point_type="analog_input",
        action="read",
        resource_type="dnp3_point",
        resource_id_template="dnp3:outstation:{outstation_id}/analog_input/{point_index}",
        name="read-analog-input",
    )
    config = Dnp3MappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="dnp3-normalization-test")
    return Dnp3Adapter(mapping=config, context=ctx)


def _dnp3_operation(subject_hint: str | None = None) -> Dnp3Operation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return Dnp3Operation(
        operation="READ",
        source_address=1,
        destination_address=10,
        outstation_id="os-14",
        master_id="master-1",
        object_group=30,
        variation=5,
        point_index=3,
        point_type="analog_input",
        function_code=1,
        metadata=meta,
    )


def _dnp3_normalized() -> NormalizedAuthorizationRequest:
    adapter = _dnp3_adapter()
    result = adapter.normalize(_dnp3_operation())
    assert result.success, f"DNP3 normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _iec61850_adapter() -> Iec61850Adapter:
    route = Iec61850RouteMapping(
        operation="READ",
        logical_node="MMXU1",
        action="read",
        resource_type="iec61850_data_attribute",
        resource_id_template=(
            "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
            "/do:{data_object}/da:{data_attribute}"
        ),
        name="read-data-attribute",
    )
    config = Iec61850MappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="iec61850-normalization-test")
    return Iec61850Adapter(mapping=config, context=ctx)


def _iec61850_operation(subject_hint: str | None = None) -> Iec61850Operation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return Iec61850Operation(
        operation="READ",
        ied_name="ied-sub1",
        logical_device="MEAS",
        logical_node="MMXU1",
        data_object="TotW",
        data_attribute="mag",
        functional_constraint="MX",
        quality="good",
        timestamp="2026-06-10T14:30:00Z",
        metadata=meta,
    )


def _iec61850_normalized() -> NormalizedAuthorizationRequest:
    adapter = _iec61850_adapter()
    result = adapter.normalize(_iec61850_operation())
    assert result.success, f"IEC 61850 normalization failed: {result.error}"
    assert result.request is not None
    return result.request


def _knx_adapter() -> KnxAdapter:
    route = KnxRouteMapping(
        operation="GROUP_VALUE_READ",
        group_address="*",
        action="read",
        resource_type="knx_group_address",
        resource_id_template="knx:group:{group_address}",
        name="read-any-group",
    )
    config = KnxMappingConfig(routes=[route])
    ctx = AdapterContext(adapter_id="knx-normalization-test")
    return KnxAdapter(mapping=config, context=ctx)


def _knx_operation(subject_hint: str | None = None) -> KnxOperation:
    meta: dict[str, Any] = {}
    if subject_hint is not None:
        meta["subject_hint"] = subject_hint
    return KnxOperation(
        operation="GROUP_VALUE_READ",
        group_address="1/2/3",
        individual_address="1.1.5",
        datapoint_type="1.001",
        priority="normal",
        metadata=meta,
    )


def _knx_normalized() -> NormalizedAuthorizationRequest:
    adapter = _knx_adapter()
    result = adapter.normalize(_knx_operation())
    assert result.success, f"KNX normalization failed: {result.error}"
    assert result.request is not None
    return result.request


# ---------------------------------------------------------------------------
# 1. REST serializes to canonical shape
# ---------------------------------------------------------------------------


class TestRestCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _rest_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_rest(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol"] == "rest"

    def test_action_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _rest_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _rest_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_is_dict(self) -> None:
        d = _rest_normalized().to_dict()
        assert isinstance(d["protocol_evidence"]["metadata"], dict)

    def test_no_forbidden_fields(self) -> None:
        d = _rest_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in REST output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _rest_adapter()
        result = adapter.normalize(_rest_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _rest_normalized().to_dict()
        # Should not raise
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 2. BACnet serializes to canonical shape
# ---------------------------------------------------------------------------


class TestBacnetCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_bacnet(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol"] == "bacnet"

    def test_action_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_bacnet_fields(self) -> None:
        d = _bacnet_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "service" in meta
        assert "object_type" in meta
        assert "object_instance" in meta
        assert "property_identifier" in meta
        assert "device_id" in meta
        assert "priority" in meta
        assert "value_present" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _bacnet_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in BACnet output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _bacnet_adapter()
        result = adapter.normalize(_bacnet_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _bacnet_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 3. Modbus serializes to canonical shape
# ---------------------------------------------------------------------------


class TestModbusCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _modbus_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _modbus_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_modbus(self) -> None:
        d = _modbus_normalized().to_dict()
        assert d["protocol"] == "modbus"

    def test_action_is_string(self) -> None:
        d = _modbus_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _modbus_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _modbus_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _modbus_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _modbus_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_modbus_fields(self) -> None:
        d = _modbus_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "unit_id" in meta
        assert "address" in meta
        assert "quantity" in meta
        assert "value_present" in meta
        assert "function" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _modbus_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in Modbus output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _modbus_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _modbus_adapter()
        result = adapter.normalize(_modbus_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _modbus_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 4. OPC UA serializes to canonical shape
# ---------------------------------------------------------------------------


class TestOpcuaCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _opcua_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _opcua_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_opcua(self) -> None:
        d = _opcua_normalized().to_dict()
        assert d["protocol"] == "opcua"

    def test_action_is_string(self) -> None:
        d = _opcua_normalized().to_dict()
        assert isinstance(d["action"], str)
        assert len(d["action"]) > 0

    def test_resource_type_is_string(self) -> None:
        d = _opcua_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _opcua_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _opcua_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _opcua_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_opcua_fields(self) -> None:
        d = _opcua_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "service" in meta
        assert "node_id" in meta
        assert "attribute_id" in meta
        assert "method_id" in meta
        assert "namespace_index" in meta
        assert "value_present" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _opcua_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in OPC UA output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _opcua_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _opcua_adapter()
        result = adapter.normalize(_opcua_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _opcua_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 5. MQTT serializes to canonical shape
# ---------------------------------------------------------------------------


class TestMqttCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_mqtt(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["protocol"] == "mqtt"

    def test_publish_action_is_write(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["action"] == "write"

    def test_resource_type_is_string(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_mqtt_fields(self) -> None:
        d = _mqtt_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "operation" in meta
        assert "topic" in meta
        assert "client_id" in meta
        assert "qos" in meta
        assert "retain" in meta
        assert "payload_type" in meta
        assert "protocol_version" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _mqtt_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in MQTT output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _mqtt_adapter()
        result = adapter.normalize(_mqtt_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _mqtt_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 6. DNP3 serializes to canonical shape
# ---------------------------------------------------------------------------


class TestDnp3CanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_dnp3(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["protocol"] == "dnp3"

    def test_read_action_is_read(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["action"] == "read"

    def test_resource_type_is_string(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_dnp3_fields(self) -> None:
        d = _dnp3_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "operation" in meta
        assert "source_address" in meta
        assert "destination_address" in meta
        assert "outstation_id" in meta
        assert "master_id" in meta
        assert "object_group" in meta
        assert "variation" in meta
        assert "point_index" in meta
        assert "point_type" in meta
        assert "function_code" in meta
        assert "qualifier" in meta
        assert "control_code" in meta
        assert "control_model" in meta
        assert "event_class" in meta
        assert "value" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _dnp3_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in DNP3 output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _dnp3_adapter()
        result = adapter.normalize(_dnp3_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _dnp3_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 7. IEC 61850 serializes to canonical shape
# ---------------------------------------------------------------------------


class TestIec61850CanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_iec61850(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["protocol"] == "iec61850"

    def test_read_action_is_read(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["action"] == "read"

    def test_resource_type_is_string(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_iec61850_fields(self) -> None:
        d = _iec61850_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "operation" in meta
        assert "ied_name" in meta
        assert "logical_device" in meta
        assert "logical_node" in meta
        assert "data_object" in meta
        assert "data_attribute" in meta
        assert "functional_constraint" in meta
        assert "dataset" in meta
        assert "report_control_block" in meta
        assert "goose_control_block" in meta
        assert "sampled_values_control_block" in meta
        assert "control_model" in meta
        assert "origin" in meta
        assert "cause" in meta
        assert "quality" in meta
        assert "timestamp" in meta
        assert "value" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _iec61850_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in IEC 61850 output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _iec61850_adapter()
        result = adapter.normalize(_iec61850_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _iec61850_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 8. KNX serializes to canonical shape
# ---------------------------------------------------------------------------


class TestKnxCanonicalShape:
    def test_to_dict_returns_dict(self) -> None:
        d = _knx_normalized().to_dict()
        assert isinstance(d, dict)

    def test_top_level_fields_exactly_canonical(self) -> None:
        d = _knx_normalized().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_knx(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["protocol"] == "knx"

    def test_read_action_is_read(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["action"] == "read"

    def test_resource_type_is_string(self) -> None:
        d = _knx_normalized().to_dict()
        assert isinstance(d["resource_type"], str)
        assert len(d["resource_type"]) > 0

    def test_resource_id_is_string(self) -> None:
        d = _knx_normalized().to_dict()
        assert isinstance(d["resource_id"], str)
        assert len(d["resource_id"]) > 0

    def test_protocol_evidence_present_and_nested(self) -> None:
        d = _knx_normalized().to_dict()
        assert "protocol_evidence" in d
        assert isinstance(d["protocol_evidence"], dict)

    def test_protocol_evidence_fields_exactly_canonical(self) -> None:
        d = _knx_normalized().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_protocol_evidence_metadata_contains_knx_fields(self) -> None:
        d = _knx_normalized().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "operation" in meta
        assert "group_address" in meta
        assert "individual_address" in meta
        assert "device_address" in meta
        assert "communication_object" in meta
        assert "datapoint_type" in meta
        assert "payload_type" in meta
        assert "value" in meta
        assert "priority" in meta
        assert "area" in meta
        assert "line" in meta
        assert "device" in meta

    def test_no_forbidden_fields(self) -> None:
        d = _knx_normalized().to_dict()
        present = FORBIDDEN_FIELDS & set(d.keys())
        assert not present, f"Forbidden fields found in KNX output: {present}"

    def test_subject_hint_none_when_absent(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["subject_hint"] is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        adapter = _knx_adapter()
        result = adapter.normalize(_knx_operation(subject_hint="operator@example.internal"))
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["subject_hint"] == "operator@example.internal"

    def test_output_is_json_serializable(self) -> None:
        d = _knx_normalized().to_dict()
        encoded = json.dumps(d)
        assert len(encoded) > 0


# ---------------------------------------------------------------------------
# 6. REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850, and KNX share the
#    same canonical field set
# ---------------------------------------------------------------------------


class TestCrossProtocolFieldSetParity:
    def test_rest_bacnet_top_level_field_sets_identical(self) -> None:
        rest_keys = set(_rest_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        rest_only = rest_keys - bacnet_keys
        bacnet_only = bacnet_keys - rest_keys
        assert rest_keys == bacnet_keys, (
            f"Field set mismatch:\n  REST-only: {rest_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_rest_modbus_top_level_field_sets_identical(self) -> None:
        rest_keys = set(_rest_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        rest_only = rest_keys - modbus_keys
        modbus_only = modbus_keys - rest_keys
        assert rest_keys == modbus_keys, (
            f"Field set mismatch:\n  REST-only: {rest_only}\n  Modbus-only: {modbus_only}"
        )

    def test_bacnet_modbus_top_level_field_sets_identical(self) -> None:
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        bacnet_only = bacnet_keys - modbus_keys
        modbus_only = modbus_keys - bacnet_keys
        assert bacnet_keys == modbus_keys, (
            f"Field set mismatch:\n  BACnet-only: {bacnet_only}\n  Modbus-only: {modbus_only}"
        )

    def test_rest_opcua_top_level_field_sets_identical(self) -> None:
        rest_keys = set(_rest_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        rest_only = rest_keys - opcua_keys
        opcua_only = opcua_keys - rest_keys
        assert rest_keys == opcua_keys, (
            f"Field set mismatch:\n  REST-only: {rest_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_bacnet_opcua_top_level_field_sets_identical(self) -> None:
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        bacnet_only = bacnet_keys - opcua_keys
        opcua_only = opcua_keys - bacnet_keys
        assert bacnet_keys == opcua_keys, (
            f"Field set mismatch:\n  BACnet-only: {bacnet_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_modbus_opcua_top_level_field_sets_identical(self) -> None:
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        modbus_only = modbus_keys - opcua_keys
        opcua_only = opcua_keys - modbus_keys
        assert modbus_keys == opcua_keys, (
            f"Field set mismatch:\n  Modbus-only: {modbus_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_mqtt_rest_top_level_field_sets_identical(self) -> None:
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        rest_keys = set(_rest_normalized().to_dict().keys())
        mqtt_only = mqtt_keys - rest_keys
        rest_only = rest_keys - mqtt_keys
        assert mqtt_keys == rest_keys, (
            f"Field set mismatch:\n  MQTT-only: {mqtt_only}\n  REST-only: {rest_only}"
        )

    def test_mqtt_bacnet_top_level_field_sets_identical(self) -> None:
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        mqtt_only = mqtt_keys - bacnet_keys
        bacnet_only = bacnet_keys - mqtt_keys
        assert mqtt_keys == bacnet_keys, (
            f"Field set mismatch:\n  MQTT-only: {mqtt_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_mqtt_modbus_top_level_field_sets_identical(self) -> None:
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        mqtt_only = mqtt_keys - modbus_keys
        modbus_only = modbus_keys - mqtt_keys
        assert mqtt_keys == modbus_keys, (
            f"Field set mismatch:\n  MQTT-only: {mqtt_only}\n  Modbus-only: {modbus_only}"
        )

    def test_mqtt_opcua_top_level_field_sets_identical(self) -> None:
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        mqtt_only = mqtt_keys - opcua_keys
        opcua_only = opcua_keys - mqtt_keys
        assert mqtt_keys == opcua_keys, (
            f"Field set mismatch:\n  MQTT-only: {mqtt_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_dnp3_rest_top_level_field_sets_identical(self) -> None:
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        rest_keys = set(_rest_normalized().to_dict().keys())
        dnp3_only = dnp3_keys - rest_keys
        rest_only = rest_keys - dnp3_keys
        assert dnp3_keys == rest_keys, (
            f"Field set mismatch:\n  DNP3-only: {dnp3_only}\n  REST-only: {rest_only}"
        )

    def test_dnp3_bacnet_top_level_field_sets_identical(self) -> None:
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        dnp3_only = dnp3_keys - bacnet_keys
        bacnet_only = bacnet_keys - dnp3_keys
        assert dnp3_keys == bacnet_keys, (
            f"Field set mismatch:\n  DNP3-only: {dnp3_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_dnp3_modbus_top_level_field_sets_identical(self) -> None:
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        dnp3_only = dnp3_keys - modbus_keys
        modbus_only = modbus_keys - dnp3_keys
        assert dnp3_keys == modbus_keys, (
            f"Field set mismatch:\n  DNP3-only: {dnp3_only}\n  Modbus-only: {modbus_only}"
        )

    def test_dnp3_opcua_top_level_field_sets_identical(self) -> None:
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        dnp3_only = dnp3_keys - opcua_keys
        opcua_only = opcua_keys - dnp3_keys
        assert dnp3_keys == opcua_keys, (
            f"Field set mismatch:\n  DNP3-only: {dnp3_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_dnp3_mqtt_top_level_field_sets_identical(self) -> None:
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        dnp3_only = dnp3_keys - mqtt_keys
        mqtt_only = mqtt_keys - dnp3_keys
        assert dnp3_keys == mqtt_keys, (
            f"Field set mismatch:\n  DNP3-only: {dnp3_only}\n  MQTT-only: {mqtt_only}"
        )

    def test_iec61850_rest_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        rest_keys = set(_rest_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - rest_keys
        rest_only = rest_keys - iec61850_keys
        assert iec61850_keys == rest_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  REST-only: {rest_only}"
        )

    def test_iec61850_bacnet_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - bacnet_keys
        bacnet_only = bacnet_keys - iec61850_keys
        assert iec61850_keys == bacnet_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_iec61850_modbus_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - modbus_keys
        modbus_only = modbus_keys - iec61850_keys
        assert iec61850_keys == modbus_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  Modbus-only: {modbus_only}"
        )

    def test_iec61850_opcua_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - opcua_keys
        opcua_only = opcua_keys - iec61850_keys
        assert iec61850_keys == opcua_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_iec61850_mqtt_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - mqtt_keys
        mqtt_only = mqtt_keys - iec61850_keys
        assert iec61850_keys == mqtt_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  MQTT-only: {mqtt_only}"
        )

    def test_iec61850_dnp3_top_level_field_sets_identical(self) -> None:
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        iec61850_only = iec61850_keys - dnp3_keys
        dnp3_only = dnp3_keys - iec61850_keys
        assert iec61850_keys == dnp3_keys, (
            f"Field set mismatch:\n  IEC 61850-only: {iec61850_only}\n  DNP3-only: {dnp3_only}"
        )

    def test_knx_rest_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        rest_keys = set(_rest_normalized().to_dict().keys())
        knx_only = knx_keys - rest_keys
        rest_only = rest_keys - knx_keys
        assert knx_keys == rest_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  REST-only: {rest_only}"
        )

    def test_knx_bacnet_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        bacnet_keys = set(_bacnet_normalized().to_dict().keys())
        knx_only = knx_keys - bacnet_keys
        bacnet_only = bacnet_keys - knx_keys
        assert knx_keys == bacnet_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  BACnet-only: {bacnet_only}"
        )

    def test_knx_modbus_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        modbus_keys = set(_modbus_normalized().to_dict().keys())
        knx_only = knx_keys - modbus_keys
        modbus_only = modbus_keys - knx_keys
        assert knx_keys == modbus_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  Modbus-only: {modbus_only}"
        )

    def test_knx_opcua_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        opcua_keys = set(_opcua_normalized().to_dict().keys())
        knx_only = knx_keys - opcua_keys
        opcua_only = opcua_keys - knx_keys
        assert knx_keys == opcua_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  OPC UA-only: {opcua_only}"
        )

    def test_knx_mqtt_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        mqtt_keys = set(_mqtt_normalized().to_dict().keys())
        knx_only = knx_keys - mqtt_keys
        mqtt_only = mqtt_keys - knx_keys
        assert knx_keys == mqtt_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  MQTT-only: {mqtt_only}"
        )

    def test_knx_dnp3_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        dnp3_keys = set(_dnp3_normalized().to_dict().keys())
        knx_only = knx_keys - dnp3_keys
        dnp3_only = dnp3_keys - knx_keys
        assert knx_keys == dnp3_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  DNP3-only: {dnp3_only}"
        )

    def test_knx_iec61850_top_level_field_sets_identical(self) -> None:
        knx_keys = set(_knx_normalized().to_dict().keys())
        iec61850_keys = set(_iec61850_normalized().to_dict().keys())
        knx_only = knx_keys - iec61850_keys
        iec61850_only = iec61850_keys - knx_keys
        assert knx_keys == iec61850_keys, (
            f"Field set mismatch:\n  KNX-only: {knx_only}\n  IEC 61850-only: {iec61850_only}"
        )

    def test_all_eight_evidence_field_sets_identical(self) -> None:
        rest_ev = set(_rest_normalized().to_dict()["protocol_evidence"].keys())
        bacnet_ev = set(_bacnet_normalized().to_dict()["protocol_evidence"].keys())
        modbus_ev = set(_modbus_normalized().to_dict()["protocol_evidence"].keys())
        opcua_ev = set(_opcua_normalized().to_dict()["protocol_evidence"].keys())
        mqtt_ev = set(_mqtt_normalized().to_dict()["protocol_evidence"].keys())
        dnp3_ev = set(_dnp3_normalized().to_dict()["protocol_evidence"].keys())
        iec61850_ev = set(_iec61850_normalized().to_dict()["protocol_evidence"].keys())
        knx_ev = set(_knx_normalized().to_dict()["protocol_evidence"].keys())
        assert (
            rest_ev
            == bacnet_ev
            == modbus_ev
            == opcua_ev
            == mqtt_ev
            == dnp3_ev
            == iec61850_ev
            == knx_ev
        ), (
            f"Evidence field set mismatch: REST={rest_ev}, BACnet={bacnet_ev}, "
            f"Modbus={modbus_ev}, OPC UA={opcua_ev}, MQTT={mqtt_ev}, DNP3={dnp3_ev}, "
            f"IEC 61850={iec61850_ev}, KNX={knx_ev}"
        )

    def test_all_protocols_have_correct_protocol_field(self) -> None:
        assert _rest_normalized().to_dict()["protocol"] == "rest"
        assert _bacnet_normalized().to_dict()["protocol"] == "bacnet"
        assert _modbus_normalized().to_dict()["protocol"] == "modbus"
        assert _opcua_normalized().to_dict()["protocol"] == "opcua"
        assert _mqtt_normalized().to_dict()["protocol"] == "mqtt"
        assert _dnp3_normalized().to_dict()["protocol"] == "dnp3"
        assert _iec61850_normalized().to_dict()["protocol"] == "iec61850"
        assert _knx_normalized().to_dict()["protocol"] == "knx"

    def test_all_protocols_produce_read_action_for_read_operations(self) -> None:
        assert _rest_normalized().to_dict()["action"] == "read"
        assert _bacnet_normalized().to_dict()["action"] == "read"
        assert _modbus_normalized().to_dict()["action"] == "read"
        assert _opcua_normalized().to_dict()["action"] == "read"
        assert _dnp3_normalized().to_dict()["action"] == "read"
        assert _iec61850_normalized().to_dict()["action"] == "read"
        assert _knx_normalized().to_dict()["action"] == "read"


# ---------------------------------------------------------------------------
# 6. Serialization is deterministic
# ---------------------------------------------------------------------------


class TestSerializationDeterminism:
    def test_rest_deterministic_across_calls(self) -> None:
        r = _rest_normalized()
        assert r.to_dict() == r.to_dict()

    def test_bacnet_deterministic_across_calls(self) -> None:
        r = _bacnet_normalized()
        assert r.to_dict() == r.to_dict()

    def test_modbus_deterministic_across_calls(self) -> None:
        r = _modbus_normalized()
        assert r.to_dict() == r.to_dict()

    def test_rest_deterministic_across_instances(self) -> None:
        r1 = _rest_normalized()
        r2 = _rest_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_bacnet_deterministic_across_instances(self) -> None:
        r1 = _bacnet_normalized()
        r2 = _bacnet_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_modbus_deterministic_across_instances(self) -> None:
        r1 = _modbus_normalized()
        r2 = _modbus_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_opcua_deterministic_across_calls(self) -> None:
        r = _opcua_normalized()
        assert r.to_dict() == r.to_dict()

    def test_opcua_deterministic_across_instances(self) -> None:
        r1 = _opcua_normalized()
        r2 = _opcua_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_mqtt_deterministic_across_calls(self) -> None:
        r = _mqtt_normalized()
        assert r.to_dict() == r.to_dict()

    def test_mqtt_deterministic_across_instances(self) -> None:
        r1 = _mqtt_normalized()
        r2 = _mqtt_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_dnp3_deterministic_across_calls(self) -> None:
        r = _dnp3_normalized()
        assert r.to_dict() == r.to_dict()

    def test_dnp3_deterministic_across_instances(self) -> None:
        r1 = _dnp3_normalized()
        r2 = _dnp3_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_iec61850_deterministic_across_calls(self) -> None:
        r = _iec61850_normalized()
        assert r.to_dict() == r.to_dict()

    def test_iec61850_deterministic_across_instances(self) -> None:
        r1 = _iec61850_normalized()
        r2 = _iec61850_normalized()
        assert r1.to_dict() == r2.to_dict()

    def test_knx_deterministic_across_calls(self) -> None:
        r = _knx_normalized()
        assert r.to_dict() == r.to_dict()

    def test_knx_deterministic_across_instances(self) -> None:
        r1 = _knx_normalized()
        r2 = _knx_normalized()
        assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# 7. Isolation — no basis_core import, no gateway transport
# ---------------------------------------------------------------------------


class TestAdapterIsolation:
    def test_basis_adapters_does_not_import_basis_core(self) -> None:
        """basis_adapters must never import basis_core — confirmed by import check."""
        # basis_adapters submodules are already loaded by top-level imports above.
        modules = [name for name in sys.modules if name.startswith("basis_adapters")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_basis_adapters_does_not_import_basis_gateway(self) -> None:
        """basis_adapters must never import basis_gateway — confirmed by import check."""
        # basis_adapters submodules are already loaded by top-level imports above.
        modules = [name for name in sys.modules if name.startswith("basis_adapters")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_normalized_request_to_dict_does_not_call_network(self) -> None:
        """to_dict() is a pure in-memory operation — no side effects."""
        import socket

        original_getaddrinfo = socket.getaddrinfo

        calls: list[tuple[Any, ...]] = []

        def spy_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            return original_getaddrinfo(*args, **kwargs)

        socket.getaddrinfo = spy_getaddrinfo  # type: ignore[method-assign]
        try:
            _rest_normalized().to_dict()
            _bacnet_normalized().to_dict()
            _modbus_normalized().to_dict()
            _opcua_normalized().to_dict()
            _mqtt_normalized().to_dict()
            _dnp3_normalized().to_dict()
            _iec61850_normalized().to_dict()
            _knx_normalized().to_dict()
        finally:
            socket.getaddrinfo = original_getaddrinfo  # type: ignore[method-assign]

        assert not calls, "to_dict() triggered a network lookup — it must be pure"


# ---------------------------------------------------------------------------
# 8. Protocol evidence is always present in serialized output
# ---------------------------------------------------------------------------


class TestProtocolEvidencePresence:
    def test_rest_evidence_protocol_matches_parent(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_bacnet_evidence_protocol_matches_parent(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_rest_evidence_method_is_http_verb(self) -> None:
        d = _rest_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "GET"

    def test_bacnet_evidence_method_is_service_name(self) -> None:
        d = _bacnet_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "ReadProperty"

    def test_rest_evidence_path_is_clean(self) -> None:
        """REST evidence path must not contain a query string."""
        d = _rest_normalized().to_dict()
        assert "?" not in d["protocol_evidence"]["path"]

    def test_modbus_evidence_protocol_matches_parent(self) -> None:
        d = _modbus_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_modbus_evidence_method_is_function_name(self) -> None:
        d = _modbus_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "ReadHoldingRegisters"

    def test_modbus_evidence_path_encodes_unit_and_address(self) -> None:
        d = _modbus_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "unit:1:addr:40001"

    def test_opcua_evidence_protocol_matches_parent(self) -> None:
        d = _opcua_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_opcua_evidence_method_is_service_name(self) -> None:
        d = _opcua_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "Read"

    def test_opcua_evidence_path_is_node_id(self) -> None:
        d = _opcua_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "ns=2;s=Building.AHU1.SupplyTemp"

    def test_mqtt_evidence_protocol_matches_parent(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_mqtt_evidence_method_is_operation_name(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "PUBLISH"

    def test_mqtt_evidence_path_is_topic(self) -> None:
        d = _mqtt_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "building/ahu-1/setpoint"

    def test_dnp3_evidence_protocol_matches_parent(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_dnp3_evidence_method_is_operation_name(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "READ"

    def test_dnp3_evidence_path_encodes_outstation_and_point(self) -> None:
        d = _dnp3_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "outstation:os-14/analog_input/3"

    def test_iec61850_evidence_protocol_matches_parent(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_iec61850_evidence_method_is_operation_name(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "READ"

    def test_iec61850_evidence_path_encodes_hierarchy(self) -> None:
        d = _iec61850_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag"

    def test_knx_evidence_protocol_matches_parent(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["protocol_evidence"]["protocol"] == d["protocol"]

    def test_knx_evidence_method_is_operation_name(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["protocol_evidence"]["method"] == "GROUP_VALUE_READ"

    def test_knx_evidence_path_encodes_group_address(self) -> None:
        d = _knx_normalized().to_dict()
        assert d["protocol_evidence"]["path"] == "group:1/2/3"
