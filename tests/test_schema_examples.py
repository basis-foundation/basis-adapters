"""
Schema/example validation tests — Phase 6.

These tests prove that the example files in examples/ and the JSON Schemas in
schemas/ cannot silently drift apart, and that live adapter output conforms to
the canonical normalized request schema.

Validated pairs:
1. REST mapping examples (full + minimal) against rest-mapping.schema.json.
2. The deliberately invalid REST mapping example FAILS validation.
3. BACnet mapping example against bacnet-mapping.schema.json.
4. Modbus mapping example against modbus-mapping.schema.json.
5. OPC UA mapping example against opcua-mapping.schema.json.
6. MQTT mapping example against mqtt-mapping.schema.json, and the
   deliberately invalid MQTT mapping example FAILS validation.
7. DNP3 mapping example against dnp3-mapping.schema.json, and the
   deliberately invalid DNP3 mapping example FAILS validation.
8. All handoff examples against normalized-authorization-request.schema.json.
9. Live adapter output (REST, BACnet, Modbus, OPC UA, MQTT, DNP3) against the
   normalized request schema — schemas must match the implementation, not
   just the example files.

Convention: keys beginning with "_" (e.g. "_comment", "_error") are
documentation annotations, not part of any contract. The adapters' from_dict()
constructors ignore them, and these tests strip them before validating, since
the schemas are intentionally strict (additionalProperties: false).

See docs/schema-validation.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from basis_adapters.bacnet import BacnetAdapter, BacnetMappingConfig, BacnetOperation
from basis_adapters.dnp3 import Dnp3Adapter, Dnp3MappingConfig, Dnp3Operation
from basis_adapters.modbus import ModbusAdapter, ModbusMappingConfig, ModbusOperation
from basis_adapters.models import AdapterContext, ProtocolOperation
from basis_adapters.mqtt import MqttAdapter, MqttMappingConfig, MqttOperation
from basis_adapters.opcua import OpcuaAdapter, OpcuaMappingConfig, OpcuaOperation
from basis_adapters.rest import RestAdapter, RestMappingConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = REPO_ROOT / "schemas"
EXAMPLES = REPO_ROOT / "examples"

REST_MAPPING_SCHEMA = SCHEMAS / "rest-mapping.schema.json"
BACNET_MAPPING_SCHEMA = SCHEMAS / "bacnet-mapping.schema.json"
MODBUS_MAPPING_SCHEMA = SCHEMAS / "modbus-mapping.schema.json"
OPCUA_MAPPING_SCHEMA = SCHEMAS / "opcua-mapping.schema.json"
MQTT_MAPPING_SCHEMA = SCHEMAS / "mqtt-mapping.schema.json"
DNP3_MAPPING_SCHEMA = SCHEMAS / "dnp3-mapping.schema.json"
NORMALIZED_REQUEST_SCHEMA = SCHEMAS / "normalized-authorization-request.schema.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data: dict[str, Any] = json.load(f)
    return data


def strip_annotations(value: Any) -> Any:
    """
    Recursively remove "_"-prefixed annotation keys (e.g. "_comment", "_error").

    These keys are documentation embedded in example files. They are ignored by
    the adapters' from_dict() constructors and are not part of any contract, so
    they are stripped before validating against the (strict) schemas.
    """
    if isinstance(value, dict):
        return {k: strip_annotations(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [strip_annotations(item) for item in value]
    return value


def validator_for(schema_path: Path) -> Draft202012Validator:
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_example(schema_path: Path, example_path: Path) -> None:
    instance = strip_annotations(load_json(example_path))
    validator_for(schema_path).validate(instance)


class TestMappingExamplesMatchSchemas:
    def test_rest_mapping_example_matches_schema(self) -> None:
        validate_example(REST_MAPPING_SCHEMA, EXAMPLES / "rest" / "mapping.example.json")

    def test_rest_mapping_minimal_example_matches_schema(self) -> None:
        validate_example(REST_MAPPING_SCHEMA, EXAMPLES / "rest" / "mapping-minimal.example.json")

    def test_rest_mapping_invalid_example_fails_schema(self) -> None:
        instance = strip_annotations(load_json(EXAMPLES / "rest" / "mapping-invalid.example.json"))
        with pytest.raises(ValidationError):
            validator_for(REST_MAPPING_SCHEMA).validate(instance)

    def test_bacnet_mapping_example_matches_schema(self) -> None:
        validate_example(BACNET_MAPPING_SCHEMA, EXAMPLES / "bacnet" / "mapping.example.json")

    def test_modbus_mapping_example_matches_schema(self) -> None:
        validate_example(MODBUS_MAPPING_SCHEMA, EXAMPLES / "modbus" / "mapping.example.json")

    def test_opcua_mapping_example_matches_schema(self) -> None:
        validate_example(OPCUA_MAPPING_SCHEMA, EXAMPLES / "opcua" / "mapping.example.json")

    def test_mqtt_mapping_example_matches_schema(self) -> None:
        validate_example(MQTT_MAPPING_SCHEMA, EXAMPLES / "mqtt" / "mapping.example.json")

    def test_mqtt_mapping_invalid_example_fails_schema(self) -> None:
        instance = strip_annotations(load_json(EXAMPLES / "mqtt" / "mapping-invalid.example.json"))
        with pytest.raises(ValidationError):
            validator_for(MQTT_MAPPING_SCHEMA).validate(instance)

    def test_dnp3_mapping_example_matches_schema(self) -> None:
        validate_example(DNP3_MAPPING_SCHEMA, EXAMPLES / "dnp3" / "mapping.example.json")

    def test_dnp3_mapping_invalid_example_fails_schema(self) -> None:
        instance = strip_annotations(load_json(EXAMPLES / "dnp3" / "mapping-invalid.example.json"))
        with pytest.raises(ValidationError):
            validator_for(DNP3_MAPPING_SCHEMA).validate(instance)


class TestHandoffExamplesMatchNormalizedRequestSchema:
    @pytest.mark.parametrize(
        "example_name",
        [
            "rest-normalized-request.example.json",
            "bacnet-normalized-request.example.json",
            "modbus-normalized-request.example.json",
            "opcua-normalized-request.example.json",
            "mqtt-publish-normalized-request.example.json",
            "mqtt-subscribe-normalized-request.example.json",
            "dnp3-read-normalized-request.example.json",
            "dnp3-direct-operate-normalized-request.example.json",
        ],
    )
    def test_handoff_example_matches_schema(self, example_name: str) -> None:
        validate_example(NORMALIZED_REQUEST_SCHEMA, EXAMPLES / "handoff" / example_name)


class TestLiveAdapterOutputMatchesNormalizedRequestSchema:
    """Schemas must match the implementation, not just the static example files."""

    def test_rest_adapter_output_matches_schema(self) -> None:
        config = RestMappingConfig.from_dict(load_json(EXAMPLES / "rest" / "mapping.example.json"))
        adapter = RestAdapter(mapping=config, context=AdapterContext(adapter_id="rest-schema"))
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(result.request.to_dict())

    def test_bacnet_adapter_output_matches_schema(self) -> None:
        config = BacnetMappingConfig.from_dict(
            load_json(EXAMPLES / "bacnet" / "mapping.example.json")
        )
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="bacnet-schema"))
        op = BacnetOperation(
            service="ReadProperty",
            object_type="analogInput",
            object_instance=1,
            property_identifier="presentValue",
            device_id="device-42",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(result.request.to_dict())

    def test_modbus_adapter_output_matches_schema(self) -> None:
        config = ModbusMappingConfig.from_dict(
            load_json(EXAMPLES / "modbus" / "mapping.example.json")
        )
        adapter = ModbusAdapter(mapping=config, context=AdapterContext(adapter_id="modbus-schema"))
        op = ModbusOperation(
            function="ReadHoldingRegisters",
            unit_id=1,
            address=40001,
            quantity=1,
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(result.request.to_dict())

    def test_opcua_adapter_output_matches_schema(self) -> None:
        config = OpcuaMappingConfig.from_dict(
            load_json(EXAMPLES / "opcua" / "mapping.example.json")
        )
        adapter = OpcuaAdapter(mapping=config, context=AdapterContext(adapter_id="opcua-schema"))
        op = OpcuaOperation(
            service="Read",
            node_id="ns=2;s=Building.AHU1.SupplyTemp",
            attribute_id="Value",
            namespace_index=2,
            identifier="Building.AHU1.SupplyTemp",
            identifier_type="string",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(result.request.to_dict())

    def test_opcua_call_output_matches_schema(self) -> None:
        config = OpcuaMappingConfig.from_dict(
            load_json(EXAMPLES / "opcua" / "mapping.example.json")
        )
        adapter = OpcuaAdapter(mapping=config, context=AdapterContext(adapter_id="opcua-schema"))
        op = OpcuaOperation(
            service="Call",
            node_id="ns=2;s=Building.AHU1",
            method_id="ns=2;s=Building.AHU1.Reset",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["action"] == "execute"
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(d)

    def test_mqtt_publish_output_matches_schema(self) -> None:
        config = MqttMappingConfig.from_dict(load_json(EXAMPLES / "mqtt" / "mapping.example.json"))
        adapter = MqttAdapter(mapping=config, context=AdapterContext(adapter_id="mqtt-schema"))
        op = MqttOperation(
            operation="PUBLISH",
            topic="building/ahu-1/setpoint",
            client_id="bms-controller-7",
            qos=1,
            payload_type="json",
            protocol_version="5.0",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["action"] == "write"
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(d)

    def test_mqtt_subscribe_output_matches_schema(self) -> None:
        config = MqttMappingConfig.from_dict(load_json(EXAMPLES / "mqtt" / "mapping.example.json"))
        adapter = MqttAdapter(mapping=config, context=AdapterContext(adapter_id="mqtt-schema"))
        op = MqttOperation(
            operation="SUBSCRIBE",
            topic="building/+/telemetry",
            client_id="energy-dashboard-2",
            qos=0,
            protocol_version="3.1.1",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["action"] == "subscribe"
        # The MQTT wildcard is preserved verbatim, never expanded.
        assert d["resource_id"] == "mqtt:building/+/telemetry"
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(d)

    def test_dnp3_read_output_matches_schema(self) -> None:
        config = Dnp3MappingConfig.from_dict(load_json(EXAMPLES / "dnp3" / "mapping.example.json"))
        adapter = Dnp3Adapter(mapping=config, context=AdapterContext(adapter_id="dnp3-schema"))
        op = Dnp3Operation(
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
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["action"] == "read"
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(d)

    def test_dnp3_direct_operate_output_matches_schema(self) -> None:
        config = Dnp3MappingConfig.from_dict(load_json(EXAMPLES / "dnp3" / "mapping.example.json"))
        adapter = Dnp3Adapter(mapping=config, context=AdapterContext(adapter_id="dnp3-schema"))
        op = Dnp3Operation(
            operation="DIRECT_OPERATE",
            source_address=1,
            destination_address=10,
            outstation_id="os-14",
            object_group=12,
            variation=1,
            point_index=7,
            point_type="binary_output",
            function_code=5,
            control_code=65,
            control_model="direct_operate",
            value="LATCH_ON",
        )
        result = adapter.normalize(op)
        assert result.success and result.request is not None
        d = result.request.to_dict()
        assert d["action"] == "execute"
        assert d["resource_id"] == "dnp3:outstation:os-14/binary_output/7"
        validator_for(NORMALIZED_REQUEST_SCHEMA).validate(d)


class TestSchemasAreThemselvesValid:
    @pytest.mark.parametrize(
        "schema_path",
        [
            REST_MAPPING_SCHEMA,
            BACNET_MAPPING_SCHEMA,
            MODBUS_MAPPING_SCHEMA,
            OPCUA_MAPPING_SCHEMA,
            MQTT_MAPPING_SCHEMA,
            DNP3_MAPPING_SCHEMA,
            NORMALIZED_REQUEST_SCHEMA,
        ],
        ids=lambda p: p.name,
    )
    def test_schema_is_valid_draft_2020_12(self, schema_path: Path) -> None:
        Draft202012Validator.check_schema(load_json(schema_path))
