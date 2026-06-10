"""
MQTT adapter contract preservation tests.

These tests verify that the MQTT adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md and the cross-protocol
normalization contract in docs/contracts/normalization-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no broker, no policy evaluation.
8. MQTT serializes to the same canonical shape as the other protocols.
9. client_id is evidence only — never identity.
"""

from __future__ import annotations

import sys

from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.mqtt.adapter import MqttAdapter
from basis_adapters.mqtt.mapping import MqttMappingConfig, MqttOperation, MqttRouteMapping

# Canonical field sets shared with test_normalization_contract.py.
CANONICAL_FIELDS: frozenset[str] = frozenset(
    {"protocol", "action", "resource_type", "resource_id", "protocol_evidence", "subject_hint"}
)
CANONICAL_EVIDENCE_FIELDS: frozenset[str] = frozenset({"protocol", "method", "path", "metadata"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> MqttOperation:
    defaults: dict[str, object] = {
        "operation": "PUBLISH",
        "topic": "building/ahu-1/setpoint",
        "qos": 1,
    }
    defaults.update(kwargs)
    return MqttOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> MqttRouteMapping:
    defaults: dict[str, object] = {
        "operation": "*",
        "topic": "*",
        "action": "",
        "resource_type": "mqtt_topic",
        "resource_id_template": "mqtt:{topic}",
        "name": "",
    }
    defaults.update(kwargs)
    return MqttRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: MqttRouteMapping, adapter_id: str = "contract-test") -> MqttAdapter:
    config = MqttMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return MqttAdapter(mapping=config, context=ctx)


def normalized_mqtt() -> NormalizedAuthorizationRequest:
    adapter = make_adapter(make_route())
    result = adapter.normalize(make_op())
    assert result.success, f"MQTT normalization failed: {result.error}"
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
            make_op(operation="CONNECT"),
            make_op(topic=""),
            make_op(qos=7),
            make_op(operation="SUBSCRIBE", retain=True),
            make_op(payload_type="xml"),
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

    def test_evidence_protocol_is_mqtt(self) -> None:
        req = normalized_mqtt()
        assert req.protocol_evidence.protocol == "mqtt"

    def test_evidence_preserved_regardless_of_route_config(self) -> None:
        # Even with a wildcard route, evidence is always the original operation.
        adapter = make_adapter(make_route(operation="*", topic="*"))
        result = adapter.normalize(
            make_op(topic="plant/chiller-3/status", client_id="scada-hmi-1", qos=2)
        )
        assert result.success
        assert result.request is not None
        ev = result.request.protocol_evidence
        assert ev.metadata["topic"] == "plant/chiller-3/status"
        assert ev.metadata["client_id"] == "scada-hmi-1"
        assert ev.metadata["qos"] == 2

    def test_wildcard_topic_preserved_verbatim_in_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/#"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "building/#"
        assert result.request.protocol_evidence.metadata["topic"] == "building/#"


# ---------------------------------------------------------------------------
# 3. Isolation — no basis_core, no gateway, no broker
# ---------------------------------------------------------------------------


class TestMqttAdapterIsolation:
    def test_mqtt_does_not_import_basis_core(self) -> None:
        mqtt_modules = [n for n in sys.modules if n.startswith("basis_adapters.mqtt")]
        for mod_name in mqtt_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_core" not in content, (
                    f"Module {mod_name!r} must not import basis_core"
                )

    def test_mqtt_does_not_import_basis_gateway(self) -> None:
        mqtt_modules = [n for n in sys.modules if n.startswith("basis_adapters.mqtt")]
        for mod_name in mqtt_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "basis_gateway" not in content, (
                    f"Module {mod_name!r} must not import basis_gateway"
                )

    def test_mqtt_does_not_import_mqtt_client_libraries(self) -> None:
        """The adapter is pure normalization — no paho-mqtt or other client libs."""
        mqtt_modules = [n for n in sys.modules if n.startswith("basis_adapters.mqtt")]
        for mod_name in mqtt_modules:
            mod = sys.modules[mod_name]
            source = getattr(mod, "__file__", None) or ""
            if source.endswith(".py"):
                with open(source) as f:
                    content = f.read()
                assert "import paho" not in content, (
                    f"Module {mod_name!r} must not import an MQTT client library"
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


class TestMqttCanonicalShape:
    def test_to_dict_top_level_fields_exactly_canonical(self) -> None:
        d = normalized_mqtt().to_dict()
        assert set(d.keys()) == CANONICAL_FIELDS

    def test_protocol_is_mqtt(self) -> None:
        d = normalized_mqtt().to_dict()
        assert d["protocol"] == "mqtt"

    def test_evidence_fields_exactly_canonical(self) -> None:
        d = normalized_mqtt().to_dict()
        assert set(d["protocol_evidence"].keys()) == CANONICAL_EVIDENCE_FIELDS

    def test_no_decision_fields(self) -> None:
        forbidden = {"decision", "allow", "deny", "permitted", "authorized", "result"}
        d = normalized_mqtt().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_verified_identity_fields(self) -> None:
        forbidden = {"subject", "principal", "identity", "user_id", "verified_subject"}
        d = normalized_mqtt().to_dict()
        assert not (forbidden & set(d.keys()))

    def test_no_mqtt_specific_top_level_fields(self) -> None:
        """MQTT detail (topic, qos, retain, client_id) must stay inside
        protocol_evidence — never as top-level siblings of action/resource_id."""
        d = normalized_mqtt().to_dict()
        mqtt_specific = {"topic", "qos", "retain", "client_id", "payload_type", "operation"}
        assert not (mqtt_specific & set(d.keys()))

    def test_subject_hint_is_none_when_absent(self) -> None:
        d = normalized_mqtt().to_dict()
        assert d["subject_hint"] is None

    def test_serialization_is_deterministic(self) -> None:
        req = normalized_mqtt()
        assert req.to_dict() == req.to_dict()

    def test_evidence_metadata_contains_mqtt_fields(self) -> None:
        d = normalized_mqtt().to_dict()
        meta = d["protocol_evidence"]["metadata"]
        assert "operation" in meta
        assert "topic" in meta
        assert "client_id" in meta
        assert "qos" in meta
        assert "retain" in meta
        assert "payload_type" in meta
        assert "protocol_version" in meta


# ---------------------------------------------------------------------------
# 5. client_id is evidence, never identity
# ---------------------------------------------------------------------------


class TestClientIdIsNotIdentity:
    def test_client_id_never_becomes_subject_hint(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(client_id="bms-controller-7"))
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_only_from_explicit_metadata(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(
            make_op(
                client_id="bms-controller-7",
                metadata={"subject_hint": "operator@example.internal"},
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "operator@example.internal"
