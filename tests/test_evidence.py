"""
Tests for `basis_adapters.evidence` — adapter evidence material construction,
RFC 8785 canonicalization, and digest computation (ADR-0007, Stage 1).

Organized per the work item's required-test categories:
1. Profile and material tests
2. Protocol projection tests (all nine adapters)
3. Canonicalization tests
4. Digest tests
5. Boundary tests (purity, isolation, no reference assembly)

The contract documents are:
  basis-architecture: docs/adr/0007-adapter-evidence-construction.md
  basis-architecture: docs/architecture/adapter-evidence-construction-semantics.md
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from typing import Any

import rfc8785

from basis_adapters import evidence as evidence_module
from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import BacnetMappingConfig, BacnetOperation, BacnetRouteMapping
from basis_adapters.dnp3.adapter import Dnp3Adapter
from basis_adapters.dnp3.mapping import Dnp3MappingConfig, Dnp3Operation, Dnp3RouteMapping
from basis_adapters.errors import (
    AdapterError,
    EvidenceCanonicalizationError,
    EvidenceConstructionError,
    ProhibitedEvidenceValueError,
    UnexpectedEvidenceFieldError,
    UnsupportedDigestAlgorithmError,
    UnsupportedEvidenceProtocolError,
)
from basis_adapters.evidence import (
    CANONICALIZATION_PROFILE,
    DIGEST_ALGORITHM_SHA256,
    EVIDENCE_PROFILE,
    construct_adapter_evidence,
)
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
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.mqtt.adapter import MqttAdapter
from basis_adapters.mqtt.mapping import MqttMappingConfig, MqttOperation, MqttRouteMapping
from basis_adapters.niagara.adapter import NiagaraAdapter
from basis_adapters.niagara.mapping import (
    NiagaraMappingConfig,
    NiagaraOperation,
    NiagaraRouteMapping,
)
from basis_adapters.opcua.adapter import OpcuaAdapter
from basis_adapters.opcua.mapping import OpcuaMappingConfig, OpcuaOperation, OpcuaRouteMapping
from basis_adapters.rest.adapter import RestAdapter
from basis_adapters.rest.mapping import RestMappingConfig, RouteMapping

# ---------------------------------------------------------------------------
# Fixtures — one adapter + one representative, evidence-rich operation per
# protocol, each producing a successful AdapterResult.
# ---------------------------------------------------------------------------


def _bacnet_result(**overrides: Any) -> AdapterResult:
    route = BacnetRouteMapping(
        service="WriteProperty",
        object_type="analogValue",
        property_identifier="presentValue",
        action="write",
        resource_type="point",
        resource_id_template="device-{device_id}/point/{object_type}:{object_instance}",
        name="write-av",
    )
    config = BacnetMappingConfig(routes=[route])
    adapter = BacnetAdapter(
        mapping=config, context=AdapterContext(adapter_id="bacnet-evidence-test")
    )
    fields: dict[str, Any] = dict(
        service="WriteProperty",
        object_type="analogValue",
        object_instance=4,
        property_identifier="presentValue",
        device_id="device-42",
        priority=8,
        value_present=True,
    )
    fields.update(overrides)
    return adapter.normalize(BacnetOperation(**fields))


def _modbus_result(**overrides: Any) -> AdapterResult:
    route = ModbusRouteMapping(
        function="WriteSingleRegister",
        register_type="holding_register",
        action="write",
        resource_type="modbus_register",
        resource_id_template="unit:{unit_id}:{register_type}:{address}",
        name="write-holding",
    )
    config = ModbusMappingConfig(routes=[route])
    adapter = ModbusAdapter(
        mapping=config, context=AdapterContext(adapter_id="modbus-evidence-test")
    )
    fields: dict[str, Any] = dict(
        function="WriteSingleRegister",
        unit_id=12,
        address=40012,
        quantity=1,
        register_type="holding_register",
        source_address="10.0.0.3",
        transaction_id=99,
    )
    fields.update(overrides)
    return adapter.normalize(ModbusOperation(**fields))


def _opcua_result(**overrides: Any) -> AdapterResult:
    route = OpcuaRouteMapping(
        service="Read",
        attribute_id="Value",
        action="read",
        resource_type="opcua_node",
        resource_id_template="{node_id}:{attribute_id}",
        name="read-node-value",
    )
    config = OpcuaMappingConfig(routes=[route])
    adapter = OpcuaAdapter(mapping=config, context=AdapterContext(adapter_id="opcua-evidence-test"))
    fields: dict[str, Any] = dict(
        service="Read",
        node_id="ns=2;s=Building.AHU1.SupplyTemp",
        attribute_id="Value",
        namespace_index=2,
        session_id="sess-1",
        endpoint_url="opc.tcp://host:4840",
    )
    fields.update(overrides)
    return adapter.normalize(OpcuaOperation(**fields))


def _mqtt_result(**overrides: Any) -> AdapterResult:
    route = MqttRouteMapping(
        operation="PUBLISH",
        topic="*",
        action="write",
        resource_type="mqtt_topic",
        resource_id_template="mqtt:{topic}",
        name="publish-any",
    )
    config = MqttMappingConfig(routes=[route])
    adapter = MqttAdapter(mapping=config, context=AdapterContext(adapter_id="mqtt-evidence-test"))
    fields: dict[str, Any] = dict(
        operation="PUBLISH",
        topic="building/ahu-1/setpoint",
        client_id="bms-controller-7",
        qos=1,
        retain=False,
        payload_type="json",
        protocol_version="5.0",
    )
    fields.update(overrides)
    return adapter.normalize(MqttOperation(**fields))


def _dnp3_result(**overrides: Any) -> AdapterResult:
    route = Dnp3RouteMapping(
        operation="DIRECT_OPERATE",
        point_type="binary_output",
        action="execute",
        resource_type="dnp3_point",
        resource_id_template="dnp3:outstation:{outstation_id}/binary_output/{point_index}",
        name="operate-binary",
    )
    config = Dnp3MappingConfig(routes=[route])
    adapter = Dnp3Adapter(mapping=config, context=AdapterContext(adapter_id="dnp3-evidence-test"))
    fields: dict[str, Any] = dict(
        operation="DIRECT_OPERATE",
        source_address=1,
        destination_address=10,
        outstation_id="os-14",
        master_id="master-1",
        point_index=7,
        point_type="binary_output",
        function_code=5,
        control_code=3,
        control_model="direct_operate",
        value=True,
    )
    fields.update(overrides)
    return adapter.normalize(Dnp3Operation(**fields))


def _iec61850_result(**overrides: Any) -> AdapterResult:
    route = Iec61850RouteMapping(
        operation="DIRECT_OPERATE",
        logical_node="CSWI1",
        action="execute",
        resource_type="iec61850_data_object",
        resource_id_template="iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}",
        name="operate-switch",
    )
    config = Iec61850MappingConfig(routes=[route])
    adapter = Iec61850Adapter(
        mapping=config, context=AdapterContext(adapter_id="iec61850-evidence-test")
    )
    fields: dict[str, Any] = dict(
        operation="DIRECT_OPERATE",
        ied_name="ied-sub1",
        logical_device="CTRL",
        logical_node="CSWI1",
        data_object="Pos",
        functional_constraint="CO",
        control_model="direct_with_normal_security",
        origin={"orCat": "station-control", "orIdent": "operator-1"},
        cause="operator",
        quality="good",
        timestamp="2026-06-10T14:30:00Z",
        value=True,
    )
    fields.update(overrides)
    return adapter.normalize(Iec61850Operation(**fields))


def _knx_result(**overrides: Any) -> AdapterResult:
    route = KnxRouteMapping(
        operation="GROUP_VALUE_WRITE",
        group_address="*",
        action="write",
        resource_type="knx_group_address",
        resource_id_template="knx:group:{group_address}",
        name="write-any-group",
    )
    config = KnxMappingConfig(routes=[route])
    adapter = KnxAdapter(mapping=config, context=AdapterContext(adapter_id="knx-evidence-test"))
    fields: dict[str, Any] = dict(
        operation="GROUP_VALUE_WRITE",
        group_address="1/2/3",
        individual_address="1.1.5",
        datapoint_type="1.001",
        priority="normal",
        value=True,
        area=1,
        line=2,
        device=3,
    )
    fields.update(overrides)
    return adapter.normalize(KnxOperation(**fields))


def _niagara_result(**overrides: Any) -> AdapterResult:
    route = NiagaraRouteMapping(
        operation="OVERRIDE_POINT",
        station="*",
        action="execute",
        resource_type="niagara_point",
        resource_id_template="niagara:station:{station}/point:{point}",
        name="override-any-point",
    )
    config = NiagaraMappingConfig(routes=[route])
    adapter = NiagaraAdapter(
        mapping=config, context=AdapterContext(adapter_id="niagara-evidence-test")
    )
    fields: dict[str, Any] = dict(
        operation="OVERRIDE_POINT",
        station="station-east",
        point="AHU1-SupplyTemp",
        point_type="NumericPoint",
        baja_type="control:NumericPoint",
        value=72.5,
        niagara_user="operator1",
        niagara_role="operator",
    )
    fields.update(overrides)
    return adapter.normalize(NiagaraOperation(**fields))


def _rest_result(metadata: dict[str, Any] | None = None) -> AdapterResult:
    route = RouteMapping(
        methods=["GET"],
        path_pattern="/devices/{device_id}/points/{point_id}",
        resource_type="point",
        resource_id_template="devices/{device_id}/points/{point_id}",
        name="read-point",
    )
    config = RestMappingConfig(routes=[route])
    adapter = RestAdapter(mapping=config, context=AdapterContext(adapter_id="rest-evidence-test"))
    op = ProtocolOperation(
        protocol="rest",
        method="GET",
        path="/devices/ahu-1/points/supply-temp",
        metadata=metadata if metadata is not None else {},
    )
    return adapter.normalize(op)


ALL_PROTOCOL_RESULT_FACTORIES: dict[str, Any] = {
    "rest": lambda: _rest_result(metadata={"subject_hint": "alice"}),
    "bacnet": _bacnet_result,
    "modbus": _modbus_result,
    "opcua": _opcua_result,
    "mqtt": _mqtt_result,
    "dnp3": _dnp3_result,
    "iec61850": _iec61850_result,
    "knx": _knx_result,
    "niagara": _niagara_result,
}


# ---------------------------------------------------------------------------
# 1. Profile and material tests
# ---------------------------------------------------------------------------


class TestProfileAndMaterial:
    def test_evidence_profile_constant(self) -> None:
        assert EVIDENCE_PROFILE == "basis-adapter-evidence-v1"

    def test_canonicalization_profile_constant(self) -> None:
        assert CANONICALIZATION_PROFILE == "rfc8785"

    def test_both_profile_identifiers_present_in_material(self) -> None:
        result = _bacnet_result()
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        d = constructed.material.to_dict()
        assert d["evidence_profile"] == EVIDENCE_PROFILE
        assert d["canonicalization_profile"] == CANONICALIZATION_PROFILE

    def test_both_profile_identifiers_included_in_digest_input(self) -> None:
        result = _bacnet_result()
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        canonical_text = constructed.canonical_bytes.decode("utf-8")
        assert f'"evidence_profile":"{EVIDENCE_PROFILE}"' in canonical_text
        assert f'"canonicalization_profile":"{CANONICALIZATION_PROFILE}"' in canonical_text

    def test_normalized_protocol_action_resource_preserved(self) -> None:
        result = _bacnet_result()
        assert result.success and result.request is not None
        req = result.request
        constructed = construct_adapter_evidence(result)
        d = constructed.material.to_dict()
        assert d["protocol"] == req.protocol
        assert d["action"] == req.action
        assert d["resource_type"] == req.resource_type
        assert d["resource_id"] == req.resource_id

    def test_top_level_subject_hint_excluded(self) -> None:
        result = _rest_result(metadata={"subject_hint": "operator@example.internal"})
        assert result.success and result.request is not None
        assert result.request.subject_hint == "operator@example.internal"
        constructed = construct_adapter_evidence(result)
        d = constructed.material.to_dict()
        assert "subject_hint" not in d
        assert "subject_hint" not in d["protocol_evidence"]
        # REST's metadata projection is always empty under this profile
        # version, so subject_hint cannot leak through metadata either.
        assert d["protocol_evidence"]["metadata"] == {}

    def test_no_undeclared_top_level_fields(self) -> None:
        result = _bacnet_result()
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        d = constructed.material.to_dict()
        assert set(d.keys()) == {
            "evidence_profile",
            "canonicalization_profile",
            "protocol",
            "action",
            "resource_type",
            "resource_id",
            "protocol_evidence",
        }
        assert set(d["protocol_evidence"].keys()) == {"protocol", "method", "path", "metadata"}

    def test_producer_gateway_kernel_execution_fields_cannot_appear(self) -> None:
        result = _bacnet_result()
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        serialized = json.dumps(constructed.material.to_dict())
        forbidden = [
            "reference_id",
            "adapter_source",
            "redaction_classification",
            "request_id",
            "correlation_id",
            "trace_id",
            "adapter_evidence_reference",
            "evidence_digest",
            "normalization_version",
            "mapping_version",
        ]
        for field_name in forbidden:
            assert f'"{field_name}"' not in serialized, (
                f"{field_name} leaked into evidence material"
            )


# ---------------------------------------------------------------------------
# 2. Protocol projection tests (all nine adapters)
# ---------------------------------------------------------------------------


EXPECTED_APPROVED_KEYS: dict[str, frozenset[str]] = {
    "rest": frozenset(),
    "bacnet": frozenset(
        {
            "service",
            "object_type",
            "object_instance",
            "property_identifier",
            "device_id",
            "priority",
            "value_present",
        }
    ),
    "modbus": frozenset(
        {
            "function",
            "unit_id",
            "address",
            "quantity",
            "value_present",
            "register_type",
            "source_address",
            "transaction_id",
        }
    ),
    "opcua": frozenset(
        {
            "service",
            "node_id",
            "attribute_id",
            "method_id",
            "namespace_index",
            "identifier",
            "identifier_type",
            "browse_name",
            "parent_node_id",
            "subscription_id",
            "monitored_item_id",
            "value_present",
            "endpoint_url",
            "session_id",
        }
    ),
    "mqtt": frozenset(
        {"operation", "topic", "client_id", "qos", "retain", "payload_type", "protocol_version"}
    ),
    "dnp3": frozenset(
        {
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
        }
    ),
    "iec61850": frozenset(
        {
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
    ),
    "knx": frozenset(
        {
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
    ),
    "niagara": frozenset(
        {
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
    ),
}


class TestProtocolProjection:
    def test_expected_key_table_matches_all_nine_protocols(self) -> None:
        assert set(EXPECTED_APPROVED_KEYS.keys()) == set(ALL_PROTOCOL_RESULT_FACTORIES.keys())

    def test_accepted_metadata_keys_projected_for_every_protocol(self) -> None:
        for protocol, factory in ALL_PROTOCOL_RESULT_FACTORIES.items():
            result = factory()
            assert result.success and result.request is not None, f"{protocol} normalization failed"
            constructed = construct_adapter_evidence(result)
            projected_metadata = constructed.material.to_dict()["protocol_evidence"]["metadata"]
            assert set(projected_metadata.keys()).issubset(EXPECTED_APPROVED_KEYS[protocol]), (
                f"{protocol}: projected keys {set(projected_metadata.keys())} exceed the "
                f"approved set {EXPECTED_APPROVED_KEYS[protocol]}"
            )
            # Fields actually present on the fixture's metadata source must
            # survive projection unchanged.
            source_metadata = result.request.protocol_evidence.metadata
            for key in source_metadata:
                if key in EXPECTED_APPROVED_KEYS[protocol]:
                    assert projected_metadata[key] == source_metadata[key]

    def test_unknown_metadata_key_rejected_for_every_non_rest_protocol(self) -> None:
        factories_with_unknown_key: dict[str, Any] = {
            "bacnet": lambda: _bacnet_result(metadata={"totally_unapproved_field": "x"}),
            "modbus": lambda: _modbus_result(metadata={"totally_unapproved_field": "x"}),
            "opcua": lambda: _opcua_result(metadata={"totally_unapproved_field": "x"}),
            "mqtt": lambda: _mqtt_result(metadata={"totally_unapproved_field": "x"}),
            "dnp3": lambda: _dnp3_result(metadata={"totally_unapproved_field": "x"}),
            "iec61850": lambda: _iec61850_result(metadata={"totally_unapproved_field": "x"}),
            "knx": lambda: _knx_result(metadata={"totally_unapproved_field": "x"}),
            "niagara": lambda: _niagara_result(metadata={"totally_unapproved_field": "x"}),
        }
        for protocol, factory in factories_with_unknown_key.items():
            result = factory()
            assert result.success and result.request is not None, f"{protocol} normalization failed"
            try:
                construct_adapter_evidence(result)
                raise AssertionError(f"{protocol}: expected UnexpectedEvidenceFieldError")
            except UnexpectedEvidenceFieldError:
                pass

    def test_key_both_prohibited_and_unapproved_raises_prohibited_error(self) -> None:
        # "password" is neither an approved bacnet key nor a REST-exempt
        # protocol, so it is both prohibited *and* unapproved. Per the
        # documented check order (prohibited names checked first,
        # regardless of approval), this must raise
        # ProhibitedEvidenceValueError, never UnexpectedEvidenceFieldError.
        result = _bacnet_result(metadata={"password": "hunter2"})
        assert result.success and result.request is not None
        try:
            construct_adapter_evidence(result)
            raise AssertionError("expected ProhibitedEvidenceValueError")
        except ProhibitedEvidenceValueError as exc:
            assert type(exc) is ProhibitedEvidenceValueError
        except UnexpectedEvidenceFieldError:
            raise AssertionError(
                "prohibited-and-unapproved key raised UnexpectedEvidenceFieldError "
                "instead of ProhibitedEvidenceValueError"
            ) from None

    def test_rest_metadata_projection_is_always_empty(self) -> None:
        # Explicit REST empty-projection rule test, per the work item.
        result = _rest_result(metadata={"subject_hint": "alice", "x_custom_header": "value"})
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        d = constructed.material.to_dict()
        assert d["protocol_evidence"]["protocol"] == "rest"
        assert d["protocol_evidence"]["metadata"] == {}

    def test_rest_metadata_projection_empty_even_with_no_source_metadata(self) -> None:
        result = _rest_result(metadata={})
        assert result.success and result.request is not None
        constructed = construct_adapter_evidence(result)
        assert constructed.material.to_dict()["protocol_evidence"]["metadata"] == {}

    def test_rest_results_differing_only_in_metadata_produce_equal_evidence(self) -> None:
        # Two REST normalization results whose *only* difference is REST
        # metadata content. Because basis-adapter-evidence-v1 never projects
        # REST metadata, the two must produce byte-identical evidence
        # material, canonical bytes, and digests — while each source
        # NormalizedAuthorizationRequest keeps its own, different, complete
        # protocol_evidence.metadata untouched.
        result_a = _rest_result(metadata={"subject_hint": "alice", "x_custom_header": "value-a"})
        result_b = _rest_result(
            metadata={"subject_hint": "bob", "x_another_header": "value-b", "extra": 123}
        )
        assert result_a.success and result_a.request is not None
        assert result_b.success and result_b.request is not None

        # The two source requests genuinely differ in REST metadata.
        source_metadata_a = dict(result_a.request.protocol_evidence.metadata)
        source_metadata_b = dict(result_b.request.protocol_evidence.metadata)
        assert source_metadata_a != source_metadata_b
        assert source_metadata_a == {"subject_hint": "alice", "x_custom_header": "value-a"}
        assert source_metadata_b == {
            "subject_hint": "bob",
            "x_another_header": "value-b",
            "extra": 123,
        }

        constructed_a = construct_adapter_evidence(result_a)
        constructed_b = construct_adapter_evidence(result_b)

        # Both projections are the empty object.
        assert constructed_a.material.to_dict()["protocol_evidence"]["metadata"] == {}
        assert constructed_b.material.to_dict()["protocol_evidence"]["metadata"] == {}

        # Evidence material, canonical bytes, and digests are all equal.
        assert constructed_a.material.to_dict() == constructed_b.material.to_dict()
        assert constructed_a.canonical_bytes == constructed_b.canonical_bytes
        assert constructed_a.digest.value == constructed_b.digest.value

        # Neither original normalized request was mutated by construction.
        assert dict(result_a.request.protocol_evidence.metadata) == source_metadata_a
        assert dict(result_b.request.protocol_evidence.metadata) == source_metadata_b

        # The original protocol_evidence.metadata remains complete and
        # still differs between the two source requests — the projection's
        # emptiness is a property of the digested evidence material only,
        # never a mutation of the normalized request the adapter returned.
        assert (
            result_a.request.protocol_evidence.metadata
            != result_b.request.protocol_evidence.metadata
        )

    def test_projection_is_deterministic_for_every_protocol(self) -> None:
        for protocol, factory in ALL_PROTOCOL_RESULT_FACTORIES.items():
            result = factory()
            assert result.success
            first = construct_adapter_evidence(result)
            second = construct_adapter_evidence(result)
            assert first.material.to_dict() == second.material.to_dict(), protocol
            assert first.canonical_bytes == second.canonical_bytes, protocol
            assert first.digest.value == second.digest.value, protocol

    def test_original_normalized_request_and_protocol_evidence_not_mutated(self) -> None:
        for protocol, factory in ALL_PROTOCOL_RESULT_FACTORIES.items():
            result = factory()
            assert result.success and result.request is not None
            before = result.request.to_dict()
            construct_adapter_evidence(result)
            after = result.request.to_dict()
            assert before == after, f"{protocol}: normalized request was mutated"

    def test_unsupported_protocol_rejected(self) -> None:
        request = NormalizedAuthorizationRequest(
            action="read",
            resource_type="thing",
            resource_id="thing-1",
            protocol="carrier-pigeon",
            protocol_evidence=ProtocolOperation(
                protocol="carrier-pigeon", method="DELIVER", path="loft-1"
            ),
        )
        result = AdapterResult.ok(request)
        try:
            construct_adapter_evidence(result)
            raise AssertionError("expected UnsupportedEvidenceProtocolError")
        except UnsupportedEvidenceProtocolError:
            pass


# ---------------------------------------------------------------------------
# 3. Canonicalization tests
# ---------------------------------------------------------------------------


class TestCanonicalization:
    def test_exact_rfc8785_bytes_for_representative_material(self) -> None:
        result = _bacnet_result()
        assert result.success
        constructed = construct_adapter_evidence(result)
        # Independently recompute canonical bytes via the dependency
        # directly, from the same material dict, and compare.
        expected = rfc8785.dumps(constructed.material.to_dict())
        assert constructed.canonical_bytes == expected

    def test_dict_insertion_order_does_not_affect_canonical_bytes(self) -> None:
        a = {"z": 1, "a": 2, "m": 3}
        b = {"a": 2, "m": 3, "z": 1}
        assert evidence_module._canonicalize(a) == evidence_module._canonicalize(b)

    def test_nested_object_insertion_order_does_not_affect_canonical_bytes(self) -> None:
        a = {"outer": {"z": 1, "a": 2}}
        b = {"outer": {"a": 2, "z": 1}}
        assert evidence_module._canonicalize(a) == evidence_module._canonicalize(b)

    def test_array_order_affects_canonical_bytes(self) -> None:
        a = {"list": [1, 2, 3]}
        b = {"list": [3, 2, 1]}
        assert evidence_module._canonicalize(a) != evidence_module._canonicalize(b)

    def test_unicode_is_preserved_not_normalized(self) -> None:
        # NFD "e" + combining acute vs. NFC "é" must remain distinct —
        # RFC 8785 does not perform Unicode normalization.
        nfd = {"value": "é"}
        nfc = {"value": "é"}
        assert evidence_module._canonicalize(nfd) != evidence_module._canonicalize(nfc)
        # Round-trip: the string content itself is preserved verbatim.
        assert json.loads(evidence_module._canonicalize(nfd))["value"] == "é"

    def test_unsupported_non_string_dictionary_keys_fail(self) -> None:
        # RFC 8785 / I-JSON-specific: object keys must be strings. This is
        # an EvidenceCanonicalizationError, exactly — not the broader base
        # EvidenceConstructionError.
        try:
            evidence_module._freeze_json_value({1: "x"}, path="metadata.value")
            raise AssertionError("expected EvidenceCanonicalizationError")
        except EvidenceCanonicalizationError as exc:
            assert type(exc) is EvidenceCanonicalizationError

    def test_non_finite_numbers_fail(self) -> None:
        # RFC 8785 / I-JSON-specific: NaN/Infinity have no JSON
        # representation. EvidenceCanonicalizationError, exactly.
        for bad in (float("nan"), float("inf"), float("-inf")):
            try:
                evidence_module._freeze_json_value(bad, path="metadata.value")
                raise AssertionError(f"expected failure for {bad}")
            except EvidenceCanonicalizationError as exc:
                assert type(exc) is EvidenceCanonicalizationError

    def test_integer_outside_safe_domain_fails(self) -> None:
        # RFC 8785 / I-JSON-specific: every number must be representable as
        # an IEEE 754 double. EvidenceCanonicalizationError, exactly.
        for bad in (2**53, -(2**53), 2**60, -(2**60)):
            try:
                evidence_module._freeze_json_value(bad, path="metadata.value")
                raise AssertionError(f"expected failure for {bad}")
            except EvidenceCanonicalizationError as exc:
                assert type(exc) is EvidenceCanonicalizationError
        # The boundary values themselves remain valid.
        assert evidence_module._freeze_json_value(2**53 - 1, path="p") == 2**53 - 1
        assert evidence_module._freeze_json_value(-(2**53 - 1), path="p") == -(2**53 - 1)

    def test_unsupported_python_values_fail(self) -> None:
        # Not a JSON value at all — a general EvidenceConstructionError,
        # exactly, never reclassified as an RFC 8785-specific failure.
        class Custom:
            pass

        for bad in (b"raw-bytes", Custom(), {1, 2, 3}):
            try:
                evidence_module._freeze_json_value(bad, path="metadata.value")
                raise AssertionError(f"expected failure for {bad!r}")
            except EvidenceConstructionError as exc:
                assert type(exc) is EvidenceConstructionError

    def test_invalid_unicode_input_fails(self) -> None:
        # An unpaired UTF-16 surrogate cannot be encoded to UTF-8 — rfc8785
        # rejects it as a CanonicalizationError, which this module wraps as
        # EvidenceCanonicalizationError, exactly.
        bad_string = "abc\ud800def"
        try:
            evidence_module._canonicalize({"value": bad_string})
            raise AssertionError("expected EvidenceCanonicalizationError")
        except EvidenceCanonicalizationError as exc:
            assert type(exc) is EvidenceCanonicalizationError

    def test_no_ordinary_json_fallback_occurs(self) -> None:
        # json.dumps sorts nothing by default and would serialize NaN;
        # rfc8785 must not be silently bypassed by an ordinary json.dumps
        # fallback for a value json.dumps would otherwise accept.
        material = {"value": float("nan")}
        assert json.dumps(material)  # ordinary json.dumps tolerates NaN by default
        try:
            evidence_module._canonicalize(material)
            raise AssertionError("expected EvidenceCanonicalizationError, no silent json fallback")
        except EvidenceCanonicalizationError:
            pass

    def test_rfc8785_number_serialization_vector(self) -> None:
        # RFC 8785 Appendix B number-serialization example.
        material = {
            "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001]
        }
        expected = b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
        assert evidence_module._canonicalize(material) == expected

    def test_rfc8785_key_ordering_vector(self) -> None:
        # RFC 8785 section 3.2.3 object-member-ordering example: keys are
        # sorted by UTF-16 code-unit value, not code-point or locale order.
        material = json.loads(
            '{"\\u20ac":"Euro Sign","\\r":"Carriage Return",'
            '"\\ufb33":"Hebrew Letter Dalet With Dagesh","1":"One",'
            '"\\u0080":"Control\\u0080",'
            '"\\u00f6":"Latin Small Letter O With Diaeresis"}'
        )
        expected = (
            b'{"\\r":"Carriage Return","1":"One","\xc2\x80":"Control\xc2\x80",'
            b'"\xc3\xb6":"Latin Small Letter O With Diaeresis",'
            b'"\xe2\x82\xac":"Euro Sign","\xef\xac\xb3":"Hebrew Letter Dalet With Dagesh"}'
        )
        assert evidence_module._canonicalize(material) == expected


# ---------------------------------------------------------------------------
# 4. Digest tests
# ---------------------------------------------------------------------------


class TestDigest:
    def test_same_material_always_produces_same_digest(self) -> None:
        result = _bacnet_result()
        assert result.success
        digests = {construct_adapter_evidence(result).digest.value for _ in range(5)}
        assert len(digests) == 1

    def test_repeated_calls_produce_byte_identical_canonical_output(self) -> None:
        result = _bacnet_result()
        assert result.success
        outputs = {construct_adapter_evidence(result).canonical_bytes for _ in range(5)}
        assert len(outputs) == 1

    def test_changed_normalized_action_changes_digest(self) -> None:
        route_write = BacnetRouteMapping(
            service="WriteProperty",
            object_type="analogValue",
            property_identifier="presentValue",
            action="write",
            resource_type="point",
            resource_id_template="point-{object_instance}",
            name="write-av",
        )
        route_read = BacnetRouteMapping(
            service="ReadProperty",
            object_type="analogValue",
            property_identifier="presentValue",
            action="read",
            resource_type="point",
            resource_id_template="point-{object_instance}",
            name="read-av",
        )
        write_adapter = BacnetAdapter(
            mapping=BacnetMappingConfig(routes=[route_write]),
            context=AdapterContext(adapter_id="t"),
        )
        read_adapter = BacnetAdapter(
            mapping=BacnetMappingConfig(routes=[route_read]),
            context=AdapterContext(adapter_id="t"),
        )
        op_write = BacnetOperation(
            service="WriteProperty",
            object_type="analogValue",
            object_instance=4,
            property_identifier="presentValue",
        )
        op_read = BacnetOperation(
            service="ReadProperty",
            object_type="analogValue",
            object_instance=4,
            property_identifier="presentValue",
        )
        write_result = write_adapter.normalize(op_write)
        read_result = read_adapter.normalize(op_read)
        assert write_result.success and read_result.success
        write_digest = construct_adapter_evidence(write_result).digest.value
        read_digest = construct_adapter_evidence(read_result).digest.value
        assert write_digest != read_digest

    def test_changed_resource_identifier_changes_digest(self) -> None:
        result_a = _bacnet_result(object_instance=4)
        result_b = _bacnet_result(object_instance=5)
        assert result_a.success and result_b.success
        digest_a = construct_adapter_evidence(result_a).digest.value
        digest_b = construct_adapter_evidence(result_b).digest.value
        assert digest_a != digest_b

    def test_changed_approved_protocol_evidence_value_changes_digest(self) -> None:
        result_a = _bacnet_result(priority=1)
        result_b = _bacnet_result(priority=2)
        assert result_a.success and result_b.success
        digest_a = construct_adapter_evidence(result_a).digest.value
        digest_b = construct_adapter_evidence(result_b).digest.value
        assert digest_a != digest_b

    def test_sha256_digest_is_lowercase_hex_64_chars(self) -> None:
        result = _bacnet_result()
        assert result.success
        digest = construct_adapter_evidence(result).digest
        assert digest.algorithm == DIGEST_ALGORITHM_SHA256
        assert len(digest.value) == 64
        assert digest.value == digest.value.lower()
        int(digest.value, 16)  # raises ValueError if not valid hex

    def test_unsupported_algorithm_fails_explicitly(self) -> None:
        result = _bacnet_result()
        assert result.success
        for bad_algorithm in ("sha-1", "md5", "SHA-256", "", "sha256"):
            try:
                construct_adapter_evidence(result, digest_algorithm=bad_algorithm)
                raise AssertionError(f"expected failure for algorithm {bad_algorithm!r}")
            except UnsupportedDigestAlgorithmError:
                pass

    def test_no_silent_fallback_to_sha256_after_unsupported_algorithm(self) -> None:
        # An unsupported algorithm must raise — never return a
        # ConstructedAdapterEvidence computed with sha-256 instead.
        result = _bacnet_result()
        assert result.success
        try:
            returned = construct_adapter_evidence(result, digest_algorithm="md5")
        except UnsupportedDigestAlgorithmError:
            pass
        else:
            raise AssertionError(f"expected UnsupportedDigestAlgorithmError, got {returned!r}")

    def test_digest_never_equals_a_reference_id_shaped_value(self) -> None:
        # Documentation-level guard: digest values are hex, never a UUID
        # shape a producer runtime might mint for reference_id.
        result = _bacnet_result()
        assert result.success
        digest_value = construct_adapter_evidence(result).digest.value
        assert "-" not in digest_value


# ---------------------------------------------------------------------------
# 5. Boundary tests
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_module_does_not_import_basis_core(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        assert "basis_core" not in content

    def test_module_does_not_import_basis_gateway(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        assert "basis_gateway" not in content

    def test_module_does_not_import_basis_identity(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        assert "basis_identity" not in content

    def test_module_does_not_import_uuid(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        assert "import uuid" not in content
        assert "uuid4" not in content

    def test_module_does_not_read_a_clock(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        for forbidden in ("import time", "import datetime", "datetime.now", "time.time"):
            assert forbidden not in content

    def test_module_does_not_reference_os_environ(self) -> None:
        source_path = evidence_module.__file__
        assert source_path is not None
        with open(source_path) as f:
            content = f.read()
        assert "os.environ" not in content
        assert "import os" not in content

    def test_construct_adapter_evidence_does_not_touch_network(self) -> None:
        import socket

        original_getaddrinfo = socket.getaddrinfo
        calls: list[Any] = []

        def spy(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            return original_getaddrinfo(*args, **kwargs)

        socket.getaddrinfo = spy  # type: ignore[method-assign]
        try:
            for factory in ALL_PROTOCOL_RESULT_FACTORIES.values():
                result = factory()
                assert result.success
                construct_adapter_evidence(result)
        finally:
            socket.getaddrinfo = original_getaddrinfo  # type: ignore[method-assign]
        assert not calls, "construct_adapter_evidence triggered a network lookup"

    def test_construct_adapter_evidence_does_not_touch_filesystem(self, tmp_path: Any) -> None:
        import builtins

        original_open = builtins.open
        opened_paths: list[str] = []

        def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            opened_paths.append(str(file))
            return original_open(file, *args, **kwargs)

        builtins.open = spy_open  # type: ignore[assignment]
        try:
            result = _bacnet_result()
            assert result.success
            construct_adapter_evidence(result)
        finally:
            builtins.open = original_open  # type: ignore[assignment]
        assert not opened_paths, (
            f"construct_adapter_evidence touched the filesystem: {opened_paths}"
        )

    def test_module_defines_no_adapter_evidence_reference_assembly(self) -> None:
        public_names = {name for name in dir(evidence_module) if not name.startswith("_")}
        # Names that would indicate this PR overstepped into
        # reference-assembly / producer-runtime territory.
        forbidden_names = {
            "AdapterEvidenceReference",
            "assemble_adapter_evidence_reference",
            "mint_reference_id",
            "select_adapter_source",
            "assign_redaction_classification",
        }
        assert not (public_names & forbidden_names)

    def test_public_surface_is_exactly_the_documented_shape(self) -> None:
        # Exact equality, not merely "these names are present" — an
        # accidental addition (or removal) to evidence.__all__ must fail
        # this test.
        expected_all = [
            "EVIDENCE_PROFILE",
            "CANONICALIZATION_PROFILE",
            "DIGEST_ALGORITHM_SHA256",
            "AdapterEvidenceMaterial",
            "EvidenceDigest",
            "ConstructedAdapterEvidence",
            "construct_adapter_evidence",
            "EvidenceConstructionError",
            "UnsupportedEvidenceProtocolError",
            "UnexpectedEvidenceFieldError",
            "ProhibitedEvidenceValueError",
            "EvidenceCanonicalizationError",
            "UnsupportedDigestAlgorithmError",
        ]
        assert len(expected_all) == 13
        assert list(evidence_module.__all__) == expected_all
        for name in expected_all:
            assert hasattr(evidence_module, name), f"missing expected public name {name}"

    def test_prohibited_metadata_keys_constant_is_not_public(self) -> None:
        # Renamed to _PROHIBITED_METADATA_KEYS specifically so it is not a
        # compatibility-supported public constant: not in __all__, not
        # accessible as a non-underscore attribute, not exported from the
        # package root.
        import basis_adapters

        assert "PROHIBITED_METADATA_KEYS" not in evidence_module.__all__
        assert not hasattr(evidence_module, "PROHIBITED_METADATA_KEYS")
        assert not hasattr(basis_adapters, "PROHIBITED_METADATA_KEYS")
        assert hasattr(evidence_module, "_PROHIBITED_METADATA_KEYS")

    def test_package_root_all_matches_evidence_module_exports(self) -> None:
        import basis_adapters

        for name in evidence_module.__all__:
            assert name in basis_adapters.__all__, (
                f"{name} is in evidence.__all__ but missing from basis_adapters.__all__"
            )

    def test_exceptions_are_adapter_errors(self) -> None:
        for exc_type in (
            EvidenceConstructionError,
            UnsupportedEvidenceProtocolError,
            UnexpectedEvidenceFieldError,
            ProhibitedEvidenceValueError,
            EvidenceCanonicalizationError,
            UnsupportedDigestAlgorithmError,
        ):
            assert issubclass(exc_type, AdapterError)

    def test_construct_adapter_evidence_is_synchronous_pure_function(self) -> None:
        assert not inspect.iscoroutinefunction(construct_adapter_evidence)

    def test_dataclasses_are_frozen(self) -> None:
        result = _bacnet_result()
        assert result.success
        constructed = construct_adapter_evidence(result)
        for attr, obj in (
            ("digest", constructed),
            ("value", constructed.digest),
            ("action", constructed.material),
        ):
            try:
                setattr(obj, attr, "tampered")
                raise AssertionError(f"expected FrozenInstanceError setting {attr}")
            except Exception as exc:
                assert type(exc).__name__ == "FrozenInstanceError"


# ---------------------------------------------------------------------------
# 5b. Deep immutability of AdapterEvidenceMaterial.protocol_evidence
# ---------------------------------------------------------------------------


def _construct_with_nested_structures() -> Any:
    """
    A ConstructedAdapterEvidence whose metadata contains both a nested
    object and a nested array under an approved key (dnp3's `value`, which
    is typed `Any`), so mutation attempts can be exercised at every level:
    top-level protocol_evidence mapping, its metadata mapping, a nested
    object inside metadata, and a nested array inside metadata.
    """
    result = _dnp3_result(value={"tags": ["a", "b", "c"], "detail": {"code": 42}})
    assert result.success
    return construct_adapter_evidence(result)


def _assert_integrity(constructed: Any) -> None:
    """
    Re-derive canonical bytes and digest from the retained material and
    confirm they still match what construction originally produced — the
    required integrity check after every mutation attempt.
    """
    rebuilt_bytes = rfc8785.dumps(constructed.material.to_dict())
    assert rebuilt_bytes == constructed.canonical_bytes
    assert hashlib.sha256(rebuilt_bytes).hexdigest() == constructed.digest.value


class TestDeepImmutability:
    def test_top_level_protocol_evidence_mapping_is_immutable(self) -> None:
        constructed = _construct_with_nested_structures()
        try:
            constructed.material.protocol_evidence["protocol"] = "tampered"  # type: ignore[index]
            raise AssertionError("expected TypeError mutating protocol_evidence")
        except TypeError:
            pass
        _assert_integrity(constructed)

    def test_metadata_mapping_is_immutable(self) -> None:
        constructed = _construct_with_nested_structures()
        metadata = constructed.material.protocol_evidence["metadata"]
        try:
            metadata["value"] = "tampered"  # type: ignore[index]
            raise AssertionError("expected TypeError mutating protocol_evidence['metadata']")
        except TypeError:
            pass
        _assert_integrity(constructed)

    def test_nested_object_in_metadata_is_immutable(self) -> None:
        constructed = _construct_with_nested_structures()
        nested_object = constructed.material.protocol_evidence["metadata"]["value"]["detail"]
        try:
            nested_object["code"] = 999  # type: ignore[index]
            raise AssertionError("expected TypeError mutating a nested object in metadata")
        except TypeError:
            pass
        _assert_integrity(constructed)

    def test_nested_array_in_metadata_is_immutable(self) -> None:
        constructed = _construct_with_nested_structures()
        nested_array = constructed.material.protocol_evidence["metadata"]["value"]["tags"]
        assert isinstance(nested_array, tuple)
        try:
            nested_array[0] = "tampered"  # type: ignore[index]
            raise AssertionError("expected TypeError mutating a nested array in metadata")
        except TypeError:
            pass
        try:
            nested_array.append("tampered")  # type: ignore[attr-defined]
            raise AssertionError("expected AttributeError appending to a nested array")
        except AttributeError:
            pass
        _assert_integrity(constructed)

    def test_to_dict_output_mutation_does_not_affect_retained_material(self) -> None:
        constructed = _construct_with_nested_structures()
        mutable_copy = constructed.material.to_dict()

        # Mutating the fresh dict/list structure is fully permitted — it is
        # ordinary, unfrozen dict/list — and must not raise.
        mutable_copy["protocol"] = "tampered"
        mutable_copy["protocol_evidence"]["metadata"]["value"]["detail"]["code"] = 999
        mutable_copy["protocol_evidence"]["metadata"]["value"]["tags"].append("tampered")
        assert isinstance(mutable_copy["protocol_evidence"]["metadata"]["value"]["tags"], list)

        # None of that mutation is visible in a freshly-requested to_dict(),
        # the retained material, the canonical bytes, or the digest.
        fresh = constructed.material.to_dict()
        assert fresh["protocol"] != "tampered"
        assert fresh["protocol_evidence"]["metadata"]["value"]["detail"]["code"] == 42
        assert fresh["protocol_evidence"]["metadata"]["value"]["tags"] == ["a", "b", "c"]
        _assert_integrity(constructed)


# ---------------------------------------------------------------------------
# 6. Failure semantics — result absent / unsuccessful / structurally invalid
# ---------------------------------------------------------------------------


class TestFailureSemantics:
    def test_unsuccessful_result_rejected(self) -> None:
        failed = AdapterResult.fail("no route matched")
        try:
            construct_adapter_evidence(failed)
            raise AssertionError("expected EvidenceConstructionError")
        except EvidenceConstructionError:
            pass

    def test_non_adapter_result_input_rejected(self) -> None:
        try:
            construct_adapter_evidence("not-a-result")  # type: ignore[arg-type]
            raise AssertionError("expected EvidenceConstructionError")
        except EvidenceConstructionError:
            pass

    def test_empty_action_rejected(self) -> None:
        request = NormalizedAuthorizationRequest(
            action="",
            resource_type="point",
            resource_id="p1",
            protocol="bacnet",
            protocol_evidence=ProtocolOperation(
                protocol="bacnet", method="ReadProperty", path="p1"
            ),
        )
        result = AdapterResult.ok(request)
        try:
            construct_adapter_evidence(result)
            raise AssertionError("expected EvidenceConstructionError")
        except EvidenceConstructionError:
            pass

    def test_protocol_mismatch_between_request_and_evidence_rejected(self) -> None:
        request = NormalizedAuthorizationRequest(
            action="read",
            resource_type="point",
            resource_id="p1",
            protocol="bacnet",
            protocol_evidence=ProtocolOperation(protocol="modbus", method="Read", path="p1"),
        )
        result = AdapterResult.ok(request)
        try:
            construct_adapter_evidence(result)
            raise AssertionError("expected EvidenceConstructionError")
        except EvidenceConstructionError:
            pass


# ---------------------------------------------------------------------------
# 7. Isolation — public API import boundary (extends
#    TestAdapterIsolation in test_normalization_contract.py for the new
#    evidence module specifically)
# ---------------------------------------------------------------------------


class TestEvidenceModuleIsolation:
    def test_evidence_symbols_importable_from_package_root(self) -> None:
        import basis_adapters

        for name in (
            "EVIDENCE_PROFILE",
            "CANONICALIZATION_PROFILE",
            "DIGEST_ALGORITHM_SHA256",
            "AdapterEvidenceMaterial",
            "EvidenceDigest",
            "ConstructedAdapterEvidence",
            "construct_adapter_evidence",
            "EvidenceConstructionError",
            "UnsupportedEvidenceProtocolError",
            "UnexpectedEvidenceFieldError",
            "ProhibitedEvidenceValueError",
            "EvidenceCanonicalizationError",
            "UnsupportedDigestAlgorithmError",
        ):
            assert hasattr(basis_adapters, name), f"{name} missing from package root"

    def test_evidence_exceptions_canonically_defined_in_errors_module(self) -> None:
        # Exceptions are centralized in basis_adapters.errors (not defined a
        # second time in basis_adapters.evidence) — the package root and
        # basis_adapters.evidence must expose the exact same class objects
        # basis_adapters.errors defines, never a shadow/duplicate.
        import basis_adapters
        from basis_adapters import errors as errors_module

        exception_names = (
            "EvidenceConstructionError",
            "UnsupportedEvidenceProtocolError",
            "UnexpectedEvidenceFieldError",
            "ProhibitedEvidenceValueError",
            "EvidenceCanonicalizationError",
            "UnsupportedDigestAlgorithmError",
        )
        for name in exception_names:
            canonical = getattr(errors_module, name)
            assert canonical.__module__ == "basis_adapters.errors"
            assert getattr(evidence_module, name) is canonical, (
                f"basis_adapters.evidence.{name} is not the same object as "
                f"basis_adapters.errors.{name}"
            )
            assert getattr(basis_adapters, name) is canonical, (
                f"basis_adapters.{name} is not the same object as basis_adapters.errors.{name}"
            )

    def test_no_basis_core_or_gateway_import_across_loaded_modules(self) -> None:
        modules = [name for name in sys.modules if name.startswith("basis_adapters")]
        for mod_name in modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, f"{mod_name} must not import basis_core"
                assert "basis_gateway" not in content, f"{mod_name} must not import basis_gateway"
