"""
Tests for MQTT mapping configuration: route validation, duplicate detection,
matching semantics, action resolution, resource ID resolution, and from_dict
parsing. Mapping validation is eager — InvalidMappingError at construction
time, not at normalization time.
"""

from __future__ import annotations

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.mqtt.mapping import (
    VALID_MQTT_TEMPLATE_FIELDS,
    MqttMappingConfig,
    MqttOperation,
    MqttRouteMapping,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_route(**kwargs: object) -> MqttRouteMapping:
    defaults: dict[str, object] = {
        "operation": "PUBLISH",
        "topic": "*",
        "action": "write",
        "resource_type": "mqtt_topic",
        "resource_id_template": "mqtt:{topic}",
        "name": "",
    }
    defaults.update(kwargs)
    return MqttRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> MqttOperation:
    defaults: dict[str, object] = {
        "operation": "PUBLISH",
        "topic": "building/ahu-1/setpoint",
    }
    defaults.update(kwargs)
    return MqttOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route validation
# ---------------------------------------------------------------------------


class TestMqttRouteMappingValidation:
    def test_valid_publish_route_constructs(self) -> None:
        route = make_route(operation="PUBLISH")
        assert route.operation == "PUBLISH"

    def test_valid_subscribe_route_constructs(self) -> None:
        route = make_route(operation="SUBSCRIBE", action="subscribe")
        assert route.operation == "SUBSCRIBE"

    def test_wildcard_operation_route_constructs(self) -> None:
        route = make_route(operation="*")
        assert route.operation == "*"

    def test_unknown_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="CONNECT")

    def test_lowercase_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="publish")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="")

    def test_empty_topic_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(topic="")

    def test_whitespace_topic_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(topic="   ")

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(action="fly")

    def test_empty_action_allowed_for_default_map(self) -> None:
        route = make_route(action="")
        assert route.action == ""

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_type="")

    def test_empty_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="")

    def test_malformed_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="mqtt:{topic")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="mqtt:{node_id}")

    def test_all_valid_template_fields_accepted(self) -> None:
        template = ":".join(f"{{{f}}}" for f in sorted(VALID_MQTT_TEMPLATE_FIELDS))
        route = make_route(resource_id_template=template)
        assert route.resource_id_template == template


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestMqttMappingConfigValidation:
    def test_empty_config_constructs(self) -> None:
        config = MqttMappingConfig(routes=[])
        assert config.routes == []

    def test_duplicate_route_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig(
                routes=[make_route(name="dup"), make_route(name="dup")],
            )

    def test_unnamed_routes_do_not_collide(self) -> None:
        config = MqttMappingConfig(routes=[make_route(), make_route()])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMqttMappingMatch:
    def test_exact_operation_and_topic_match(self) -> None:
        route = make_route(operation="PUBLISH", topic="building/ahu-1/setpoint")
        config = MqttMappingConfig(routes=[route])
        matched = config.match(make_op(topic="building/ahu-1/setpoint"))
        assert matched is route

    def test_wildcard_operation_matches_any(self) -> None:
        route = make_route(operation="*")
        config = MqttMappingConfig(routes=[route])
        assert config.match(make_op(operation="PUBLISH")) is route
        assert config.match(make_op(operation="SUBSCRIBE")) is route

    def test_wildcard_topic_matches_any(self) -> None:
        route = make_route(topic="*")
        config = MqttMappingConfig(routes=[route])
        assert config.match(make_op(topic="a/b/c")) is route

    def test_topic_matching_is_literal_not_mqtt_filter(self) -> None:
        """A route topic with an MQTT wildcard matches only the literally
        identical operation topic — no MQTT filter semantics."""
        route = make_route(operation="SUBSCRIBE", topic="building/+/telemetry")
        config = MqttMappingConfig(routes=[route])
        # Literal match works.
        matched = config.match(make_op(operation="SUBSCRIBE", topic="building/+/telemetry"))
        assert matched is route
        # A concrete topic the filter would cover does NOT match.
        with pytest.raises(UnknownRouteError):
            config.match(make_op(operation="SUBSCRIBE", topic="building/ahu-1/telemetry"))

    def test_first_match_wins(self) -> None:
        first = make_route(name="first")
        second = make_route(name="second")
        config = MqttMappingConfig(routes=[first, second])
        assert config.match(make_op()) is first

    def test_no_match_raises_unknown_route(self) -> None:
        route = make_route(operation="SUBSCRIBE")
        config = MqttMappingConfig(routes=[route])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(operation="PUBLISH"))

    def test_empty_config_raises_unknown_route(self) -> None:
        config = MqttMappingConfig(routes=[])
        with pytest.raises(UnknownRouteError):
            config.match(make_op())


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestMqttActionResolution:
    def test_explicit_route_action_wins(self) -> None:
        route = make_route(action="control")
        config = MqttMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op()) == "control"

    def test_publish_defaults_to_write(self) -> None:
        route = make_route(action="")
        config = MqttMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(operation="PUBLISH")) == "write"

    def test_subscribe_defaults_to_subscribe(self) -> None:
        route = make_route(operation="*", action="")
        config = MqttMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(operation="SUBSCRIBE")) == "subscribe"


# ---------------------------------------------------------------------------
# Resource ID resolution
# ---------------------------------------------------------------------------


class TestMqttResourceIdResolution:
    def test_topic_substitution(self) -> None:
        route = make_route(resource_id_template="mqtt:{topic}")
        config = MqttMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(topic="a/b"))
        assert rid == "mqtt:a/b"

    def test_operation_and_qos_substitution(self) -> None:
        route = make_route(resource_id_template="{operation}:{topic}:qos:{qos}")
        config = MqttMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(qos=1))
        assert rid == "PUBLISH:building/ahu-1/setpoint:qos:1"

    def test_payload_type_substitution(self) -> None:
        route = make_route(resource_id_template="mqtt:{topic}:{payload_type}")
        config = MqttMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(payload_type="json"))
        assert rid == "mqtt:building/ahu-1/setpoint:json"

    def test_client_id_substitution(self) -> None:
        route = make_route(resource_id_template="mqtt:{client_id}:{topic}")
        config = MqttMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(client_id="c-1"))
        assert rid == "mqtt:c-1:building/ahu-1/setpoint"

    def test_missing_client_id_raises(self) -> None:
        route = make_route(resource_id_template="mqtt:{client_id}:{topic}")
        config = MqttMappingConfig(routes=[route])
        with pytest.raises(InvalidMappingError):
            config.resolve_resource_id(route, make_op(client_id=None))

    def test_wildcard_topic_substituted_verbatim(self) -> None:
        route = make_route(resource_id_template="mqtt:{topic}")
        config = MqttMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(topic="building/#"))
        assert rid == "mqtt:building/#"


# ---------------------------------------------------------------------------
# from_dict parsing
# ---------------------------------------------------------------------------


class TestMqttMappingFromDict:
    def test_valid_config_parses(self) -> None:
        config = MqttMappingConfig.from_dict(
            {
                "routes": [
                    {
                        "name": "publish-any",
                        "operation": "PUBLISH",
                        "topic": "*",
                        "action": "write",
                        "resource_type": "mqtt_topic",
                        "resource_id_template": "mqtt:{topic}",
                    }
                ]
            }
        )
        assert len(config.routes) == 1
        assert config.routes[0].operation == "PUBLISH"

    def test_empty_routes_parses(self) -> None:
        config = MqttMappingConfig.from_dict({"routes": []})
        assert config.routes == []

    def test_missing_routes_key_parses_as_empty(self) -> None:
        config = MqttMappingConfig.from_dict({})
        assert config.routes == []

    def test_routes_not_a_list_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig.from_dict({"routes": "nope"})

    def test_route_not_a_dict_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig.from_dict({"routes": ["nope"]})

    def test_invalid_route_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig.from_dict(
                {
                    "routes": [
                        {
                            "operation": "CONNECT",
                            "topic": "*",
                            "resource_type": "mqtt_topic",
                            "resource_id_template": "mqtt:{topic}",
                        }
                    ]
                }
            )

    def test_duplicate_names_rejected(self) -> None:
        route = {
            "name": "dup",
            "operation": "PUBLISH",
            "topic": "*",
            "resource_type": "mqtt_topic",
            "resource_id_template": "mqtt:{topic}",
        }
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig.from_dict({"routes": [route, dict(route)]})

    def test_annotation_keys_ignored(self) -> None:
        config = MqttMappingConfig.from_dict(
            {
                "_comment": "ignored",
                "routes": [
                    {
                        "_error": "ignored too",
                        "operation": "SUBSCRIBE",
                        "topic": "*",
                        "resource_type": "mqtt_topic",
                        "resource_id_template": "mqtt:{topic}",
                    }
                ],
            }
        )
        assert len(config.routes) == 1

    def test_example_mapping_file_parses(self) -> None:
        import json
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "examples" / "mqtt" / "mapping.example.json"
        config = MqttMappingConfig.from_dict(json.loads(path.read_text()))
        assert len(config.routes) == 4

    def test_invalid_example_mapping_file_rejected(self) -> None:
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "examples"
            / "mqtt"
            / "mapping-invalid.example.json"
        )
        with pytest.raises(InvalidMappingError):
            MqttMappingConfig.from_dict(json.loads(path.read_text()))
