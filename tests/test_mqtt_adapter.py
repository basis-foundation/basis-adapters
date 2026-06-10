"""
Tests for MqttAdapter normalization behavior.

Covers PUBLISH and SUBSCRIBE normalization, wildcard route matching,
exact-topic matching, template substitution, MQTT wildcard topic
preservation, operation validation (fail closed), protocol evidence
preservation, and failure result shapes.
"""

from __future__ import annotations

from basis_adapters.models import AdapterContext, AdapterResult
from basis_adapters.mqtt.adapter import MqttAdapter
from basis_adapters.mqtt.mapping import MqttMappingConfig, MqttOperation, MqttRouteMapping

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> MqttOperation:
    defaults: dict[str, object] = {
        "operation": "PUBLISH",
        "topic": "building/ahu-1/setpoint",
        "qos": 0,
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


def make_adapter(*routes: MqttRouteMapping, adapter_id: str = "test") -> MqttAdapter:
    config = MqttMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return MqttAdapter(mapping=config, context=ctx)


# ---------------------------------------------------------------------------
# Publish normalization
# ---------------------------------------------------------------------------


class TestPublishNormalization:
    def test_publish_normalizes_to_write_by_default(self) -> None:
        adapter = make_adapter(make_route(operation="PUBLISH"))
        result = adapter.normalize(make_op(operation="PUBLISH"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_publish_resource_id_includes_topic(self) -> None:
        adapter = make_adapter(make_route(operation="PUBLISH"))
        result = adapter.normalize(make_op(topic="building/ahu-1/setpoint"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:building/ahu-1/setpoint"

    def test_publish_explicit_route_action_wins(self) -> None:
        adapter = make_adapter(make_route(operation="PUBLISH", action="control"))
        result = adapter.normalize(make_op(operation="PUBLISH"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "control"

    def test_publish_with_retain_true_is_valid(self) -> None:
        adapter = make_adapter(make_route(operation="PUBLISH"))
        result = adapter.normalize(make_op(operation="PUBLISH", retain=True))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["retain"] is True


# ---------------------------------------------------------------------------
# Subscribe normalization
# ---------------------------------------------------------------------------


class TestSubscribeNormalization:
    def test_subscribe_normalizes_to_subscribe_by_default(self) -> None:
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"

    def test_subscribe_resource_id_includes_topic(self) -> None:
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/ahu-1/telemetry"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:building/ahu-1/telemetry"


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_exact_topic_route_matches_identical_topic(self) -> None:
        route = make_route(operation="PUBLISH", topic="building/ahu-1/setpoint")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(topic="building/ahu-1/setpoint"))
        assert result.success

    def test_exact_topic_route_does_not_match_other_topic(self) -> None:
        route = make_route(operation="PUBLISH", topic="building/ahu-1/setpoint")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(topic="building/ahu-2/setpoint"))
        assert not result.success

    def test_operation_mismatch_fails_closed(self) -> None:
        route = make_route(operation="PUBLISH")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(operation="SUBSCRIBE"))
        assert not result.success

    def test_first_match_wins(self) -> None:
        first = make_route(operation="PUBLISH", action="write", name="first")
        second = make_route(operation="PUBLISH", action="control", name="second")
        adapter = make_adapter(first, second)
        result = adapter.normalize(make_op(operation="PUBLISH"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"


# ---------------------------------------------------------------------------
# Resource ID template
# ---------------------------------------------------------------------------


class TestResourceIdTemplate:
    def test_qos_in_resource_id(self) -> None:
        route = make_route(resource_id_template="mqtt:{topic}:qos:{qos}")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(qos=2))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:building/ahu-1/setpoint:qos:2"

    def test_client_id_in_resource_id(self) -> None:
        route = make_route(resource_id_template="mqtt:{client_id}:{topic}")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(client_id="bms-controller-7"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:bms-controller-7:building/ahu-1/setpoint"

    def test_client_id_template_fails_closed_when_client_id_absent(self) -> None:
        route = make_route(resource_id_template="mqtt:{client_id}:{topic}")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(client_id=None))
        assert not result.success
        assert result.error is not None

    def test_different_topics_produce_different_resource_ids(self) -> None:
        adapter = make_adapter(make_route())
        r1 = adapter.normalize(make_op(topic="building/ahu-1/setpoint"))
        r2 = adapter.normalize(make_op(topic="building/ahu-2/setpoint"))
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.resource_id != r2.request.resource_id


# ---------------------------------------------------------------------------
# Wildcard topics — preserved, never expanded
# ---------------------------------------------------------------------------


class TestWildcardTopicPreservation:
    def test_plus_wildcard_topic_preserved_in_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/+/telemetry"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:building/+/telemetry"

    def test_hash_wildcard_topic_preserved_in_resource_id(self) -> None:
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/#"))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "mqtt:building/#"

    def test_wildcard_topic_preserved_verbatim_in_evidence(self) -> None:
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/+/telemetry"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "building/+/telemetry"
        assert result.request.protocol_evidence.metadata["topic"] == "building/+/telemetry"

    def test_wildcard_topic_not_expanded_to_concrete_topics(self) -> None:
        """A wildcard subscription produces exactly one normalized request."""
        adapter = make_adapter(make_route(operation="SUBSCRIBE"))
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/#"))
        assert result.success
        assert result.request is not None
        # The wildcard remains a single opaque string; no expansion happened.
        assert "#" in result.request.resource_id

    def test_exact_route_topic_does_not_filter_match_wildcards(self) -> None:
        """A route with a concrete topic must not match a wildcard filter
        covering it — matching is literal, not MQTT filter semantics."""
        route = make_route(operation="SUBSCRIBE", topic="building/ahu-1/telemetry")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(operation="SUBSCRIBE", topic="building/+/telemetry"))
        assert not result.success


# ---------------------------------------------------------------------------
# Operation validation — fail closed
# ---------------------------------------------------------------------------


class TestOperationValidation:
    def test_empty_topic_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(topic=""))
        assert not result.success
        assert result.error is not None

    def test_whitespace_topic_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(topic="   "))
        assert not result.success

    def test_unsupported_operation_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="CONNECT"))
        assert not result.success
        assert result.error is not None

    def test_lowercase_operation_fails_no_silent_coercion(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="publish"))
        assert not result.success

    def test_invalid_qos_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(qos=3))
        assert not result.success
        assert result.error is not None

    def test_negative_qos_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(qos=-1))
        assert not result.success

    def test_boolean_qos_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(qos=True))
        assert not result.success

    def test_non_boolean_retain_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(retain="yes"))
        assert not result.success

    def test_subscribe_with_retain_true_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="SUBSCRIBE", retain=True))
        assert not result.success
        assert result.error is not None

    def test_invalid_payload_type_fails(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(payload_type="xml"))
        assert not result.success

    def test_empty_client_id_fails_when_present(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(client_id=""))
        assert not result.success

    def test_empty_protocol_version_fails_when_present(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(protocol_version=""))
        assert not result.success


# ---------------------------------------------------------------------------
# Protocol field
# ---------------------------------------------------------------------------


class TestProtocolField:
    def test_protocol_is_mqtt(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol == "mqtt"


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

    def test_evidence_protocol_is_mqtt(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.protocol == "mqtt"

    def test_evidence_method_is_operation_name(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(operation="PUBLISH"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "PUBLISH"

    def test_evidence_path_is_topic(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(topic="building/ahu-1/setpoint"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "building/ahu-1/setpoint"

    def test_evidence_metadata_contains_topic(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(topic="building/ahu-1/setpoint"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["topic"] == "building/ahu-1/setpoint"

    def test_evidence_metadata_contains_client_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(client_id="bms-controller-7"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["client_id"] == "bms-controller-7"

    def test_evidence_metadata_contains_qos(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(qos=2))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["qos"] == 2

    def test_evidence_metadata_contains_retain(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(retain=True))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["retain"] is True

    def test_evidence_metadata_contains_payload_type(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(payload_type="json"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["payload_type"] == "json"

    def test_evidence_metadata_contains_protocol_version(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(protocol_version="5.0"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["protocol_version"] == "5.0"

    def test_extra_metadata_preserved_in_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(metadata={"broker": "site-a"}))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["broker"] == "site-a"


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

    def test_client_id_is_not_subject_hint(self) -> None:
        """client_id is evidence, never identity — it must not leak into
        subject_hint."""
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(client_id="bms-controller-7"))
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
        result = adapter.normalize(make_op(operation="CONNECT", topic="", qos=99))
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
        config = MqttMappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="mqtt-primary")
        adapter = MqttAdapter(mapping=config, context=ctx)
        assert adapter.adapter_id == "mqtt-primary"
