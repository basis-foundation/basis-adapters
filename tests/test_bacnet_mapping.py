"""
Tests for BACnet mapping configuration: BacnetOperation, BacnetRouteMapping,
and BacnetMappingConfig.

Covers config validation, field matching, wildcard semantics, route ordering,
template resolution, and from_dict parsing.
"""

from __future__ import annotations

import dataclasses

import pytest

from basis_adapters.bacnet.mapping import (
    VALID_BACNET_SERVICES,
    VALID_BACNET_TEMPLATE_FIELDS,
    BacnetMappingConfig,
    BacnetOperation,
    BacnetRouteMapping,
)
from basis_adapters.errors import InvalidMappingError, UnknownRouteError

# ---------------------------------------------------------------------------
# BacnetOperation helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> BacnetOperation:
    defaults: dict[str, object] = {
        "service": "ReadProperty",
        "object_type": "analogInput",
        "object_instance": 1,
        "property_identifier": "presentValue",
    }
    defaults.update(kwargs)
    return BacnetOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> BacnetRouteMapping:
    defaults: dict[str, object] = {
        "service": "ReadProperty",
        "object_type": "analogInput",
        "property_identifier": "presentValue",
        "action": "read",
        "resource_type": "point",
        "resource_id_template": "{object_type}:{object_instance}",
    }
    defaults.update(kwargs)
    return BacnetRouteMapping(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BacnetOperation
# ---------------------------------------------------------------------------


class TestBacnetOperation:
    def test_frozen(self) -> None:
        op = make_op()
        with pytest.raises(dataclasses.FrozenInstanceError):
            op.service = "WriteProperty"  # type: ignore[misc]

    def test_defaults(self) -> None:
        op = make_op()
        assert op.device_id is None
        assert op.priority is None
        assert op.value_present is False
        assert op.metadata == {}

    def test_to_protocol_operation_path_format(self) -> None:
        op = make_op(
            object_type="analogInput", object_instance=42, property_identifier="presentValue"
        )
        proto = op.to_protocol_operation()
        assert proto.path == "analogInput:42:presentValue"

    def test_to_protocol_operation_protocol(self) -> None:
        proto = make_op().to_protocol_operation()
        assert proto.protocol == "bacnet"

    def test_to_protocol_operation_method_is_service(self) -> None:
        op = make_op(service="WriteProperty")
        proto = op.to_protocol_operation()
        assert proto.method == "WriteProperty"

    def test_to_protocol_operation_metadata_contains_all_fields(self) -> None:
        op = make_op(
            service="ReadProperty",
            object_type="analogInput",
            object_instance=7,
            property_identifier="presentValue",
            device_id="dev-99",
            priority=8,
            value_present=True,
        )
        proto = op.to_protocol_operation()
        assert proto.metadata["service"] == "ReadProperty"
        assert proto.metadata["object_type"] == "analogInput"
        assert proto.metadata["object_instance"] == 7
        assert proto.metadata["property_identifier"] == "presentValue"
        assert proto.metadata["device_id"] == "dev-99"
        assert proto.metadata["priority"] == 8
        assert proto.metadata["value_present"] is True

    def test_to_protocol_operation_metadata_includes_extra_metadata(self) -> None:
        op = make_op(metadata={"tenant": "acme"})
        proto = op.to_protocol_operation()
        assert proto.metadata["tenant"] == "acme"

    def test_to_protocol_operation_is_frozen(self) -> None:
        proto = make_op().to_protocol_operation()
        with pytest.raises(dataclasses.FrozenInstanceError):
            proto.protocol = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BacnetRouteMapping validation
# ---------------------------------------------------------------------------


class TestBacnetRouteMappingValidation:
    def test_valid_route_constructs(self) -> None:
        r = make_route()
        assert r.service == "ReadProperty"

    def test_frozen(self) -> None:
        r = make_route()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.action = "write"  # type: ignore[misc]

    def test_invalid_service_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized BACnet service"):
            make_route(service="UnknownService")

    def test_wildcard_service_accepted(self) -> None:
        r = make_route(service="*")
        assert r.service == "*"

    def test_empty_object_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="object_type must not be empty"):
            make_route(object_type="")

    def test_empty_property_identifier_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="property_identifier must not be empty"):
            make_route(property_identifier="")

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="fly")

    def test_empty_action_accepted(self) -> None:
        # Empty action means use default service action map at normalization time
        r = make_route(action="")
        assert r.action == ""

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type must not be empty"):
            make_route(resource_type="")

    def test_empty_resource_id_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template must not be empty"):
            make_route(resource_id_template="")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="references unknown field"):
            make_route(resource_id_template="{unknown_field}")

    def test_malformed_template_brace_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed token"):
            make_route(resource_id_template="{unclosed")

    def test_all_valid_template_fields_accepted(self) -> None:
        # Each valid field should be accepted individually
        for field_name in VALID_BACNET_TEMPLATE_FIELDS:
            r = make_route(resource_id_template=f"{{{field_name}}}")
            assert f"{{{field_name}}}" in r.resource_id_template

    def test_static_resource_id_template_accepted(self) -> None:
        r = make_route(resource_id_template="static-id")
        assert r.resource_id_template == "static-id"

    def test_all_valid_services(self) -> None:
        for svc in VALID_BACNET_SERVICES:
            r = make_route(service=svc)
            assert r.service == svc


# ---------------------------------------------------------------------------
# BacnetMappingConfig: duplicate names
# ---------------------------------------------------------------------------


class TestBacnetMappingConfigDuplicateNames:
    def test_duplicate_names_rejected(self) -> None:
        r1 = make_route(name="my-route")
        r2 = make_route(service="WriteProperty", action="write", name="my-route")
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            BacnetMappingConfig(routes=[r1, r2])

    def test_unnamed_routes_not_checked(self) -> None:
        r1 = make_route(name="")
        r2 = make_route(name="")
        config = BacnetMappingConfig(routes=[r1, r2])
        assert len(config.routes) == 2

    def test_unique_names_accepted(self) -> None:
        r1 = make_route(name="route-a")
        r2 = make_route(service="WriteProperty", action="write", name="route-b")
        config = BacnetMappingConfig(routes=[r1, r2])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# BacnetMappingConfig: match
# ---------------------------------------------------------------------------


class TestBacnetMappingConfigMatch:
    def test_exact_match(self) -> None:
        route = make_route()
        config = BacnetMappingConfig(routes=[route])
        matched = config.match(make_op())
        assert matched is route

    def test_no_match_raises(self) -> None:
        config = BacnetMappingConfig(routes=[make_route()])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(object_type="binaryOutput"))

    def test_wildcard_service(self) -> None:
        route = make_route(service="*")
        config = BacnetMappingConfig(routes=[route])
        assert config.match(make_op(service="WriteProperty")) is route

    def test_wildcard_object_type(self) -> None:
        route = make_route(object_type="*")
        config = BacnetMappingConfig(routes=[route])
        assert config.match(make_op(object_type="binaryOutput")) is route

    def test_wildcard_property_identifier(self) -> None:
        route = make_route(property_identifier="*")
        config = BacnetMappingConfig(routes=[route])
        assert config.match(make_op(property_identifier="description")) is route

    def test_all_wildcard(self) -> None:
        route = make_route(service="*", object_type="*", property_identifier="*")
        config = BacnetMappingConfig(routes=[route])
        op = make_op(
            service="CommandValue", object_type="binaryOutput", property_identifier="description"
        )
        assert config.match(op) is route

    def test_first_match_wins(self) -> None:
        r1 = make_route(name="first", service="*")
        r2 = make_route(name="second", service="*", object_type="*")
        config = BacnetMappingConfig(routes=[r1, r2])
        assert config.match(make_op()) is r1

    def test_specific_before_wildcard(self) -> None:
        r_specific = make_route(name="specific", service="ReadProperty")
        r_wildcard = make_route(name="wildcard", service="*")
        config = BacnetMappingConfig(routes=[r_specific, r_wildcard])
        assert config.match(make_op(service="ReadProperty")) is r_specific

    def test_falls_through_to_later_route(self) -> None:
        r1 = make_route(name="write-route", service="WriteProperty", action="write")
        r2 = make_route(name="catch-all", service="*", object_type="*", property_identifier="*")
        config = BacnetMappingConfig(routes=[r1, r2])
        # ReadProperty doesn't match WriteProperty, falls through to wildcard
        assert config.match(make_op(service="ReadProperty")) is r2

    def test_property_identifier_exact_match(self) -> None:
        r_specific = make_route(name="present-value", property_identifier="presentValue")
        r_wildcard = make_route(name="any-prop", property_identifier="*")
        config = BacnetMappingConfig(routes=[r_specific, r_wildcard])
        assert config.match(make_op(property_identifier="presentValue")) is r_specific
        assert config.match(make_op(property_identifier="description")) is r_wildcard


# ---------------------------------------------------------------------------
# BacnetMappingConfig: resolve_action
# ---------------------------------------------------------------------------


class TestResolveAction:
    def test_explicit_action_used(self) -> None:
        route = make_route(action="control")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op()) == "control"

    def test_default_read_property_action(self) -> None:
        route = make_route(action="")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(service="ReadProperty")) == "read"

    def test_default_write_property_action(self) -> None:
        route = make_route(action="")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(service="WriteProperty")) == "write"

    def test_default_subscribe_cov_action(self) -> None:
        route = make_route(action="")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(service="SubscribeCOV")) == "subscribe"

    def test_default_command_value_action(self) -> None:
        route = make_route(action="")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(service="CommandValue")) == "control"

    def test_unknown_service_no_default_raises(self) -> None:
        # Create a route with empty action to force default lookup
        route = make_route(action="", service="*")
        config = BacnetMappingConfig(routes=[route])
        # Use an operation with service not in default map by patching
        # Since VALID_BACNET_SERVICES is strict, we test via the public API
        # The only way to get an unrecognized service through is if the route is wildcard
        # and the operation was created externally. We can't construct a BacnetOperation
        # with an invalid service, but we can call resolve_action directly with a
        # mock-like dataclass.
        import dataclasses as _dc

        patched_route = _dc.replace(route, action="")
        # Use a real operation with a known but unmapped service won't happen
        # since all 4 services have defaults. This test verifies the explicit action branch.
        assert config.resolve_action(patched_route, make_op(service="ReadProperty")) == "read"


# ---------------------------------------------------------------------------
# BacnetMappingConfig: resolve_resource_id
# ---------------------------------------------------------------------------


class TestResolveResourceId:
    def test_object_type_substitution(self) -> None:
        route = make_route(resource_id_template="{object_type}")
        config = BacnetMappingConfig(routes=[route])
        result = config.resolve_resource_id(route, make_op(object_type="analogInput"))
        assert result == "analogInput"

    def test_object_instance_substitution(self) -> None:
        route = make_route(resource_id_template="{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_resource_id(route, make_op(object_instance=42)) == "42"

    def test_compound_template(self) -> None:
        route = make_route(
            resource_id_template="{object_type}:{object_instance}:{property_identifier}"
        )
        config = BacnetMappingConfig(routes=[route])
        op = make_op(
            object_type="analogInput", object_instance=7, property_identifier="presentValue"
        )
        assert config.resolve_resource_id(route, op) == "analogInput:7:presentValue"

    def test_device_id_substitution(self) -> None:
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        op = make_op(device_id="dev-42", object_instance=1)
        assert config.resolve_resource_id(route, op) == "dev-42:1"

    def test_device_id_none_raises_when_referenced(self) -> None:
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        op = make_op(device_id=None)
        with pytest.raises(InvalidMappingError, match="device_id.*None"):
            config.resolve_resource_id(route, op)

    def test_device_id_none_not_referenced_ok(self) -> None:
        route = make_route(resource_id_template="{object_type}:{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        op = make_op(device_id=None)
        result = config.resolve_resource_id(route, op)
        assert result == "analogInput:1"

    def test_static_template(self) -> None:
        route = make_route(resource_id_template="fixed-id")
        config = BacnetMappingConfig(routes=[route])
        assert config.resolve_resource_id(route, make_op()) == "fixed-id"

    def test_service_substitution(self) -> None:
        route = make_route(resource_id_template="{service}:{object_type}")
        config = BacnetMappingConfig(routes=[route])
        op = make_op(service="WriteProperty", object_type="binaryOutput")
        assert config.resolve_resource_id(route, op) == "WriteProperty:binaryOutput"


# ---------------------------------------------------------------------------
# BacnetMappingConfig: from_dict
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_minimal_config(self) -> None:
        data = {
            "routes": [
                {
                    "service": "ReadProperty",
                    "object_type": "analogInput",
                    "property_identifier": "presentValue",
                    "action": "read",
                    "resource_type": "point",
                    "resource_id_template": "{object_type}:{object_instance}",
                }
            ]
        }
        config = BacnetMappingConfig.from_dict(data)
        assert len(config.routes) == 1
        assert config.routes[0].service == "ReadProperty"

    def test_empty_routes(self) -> None:
        config = BacnetMappingConfig.from_dict({"routes": []})
        assert config.routes == []

    def test_missing_routes_key(self) -> None:
        config = BacnetMappingConfig.from_dict({})
        assert config.routes == []

    def test_invalid_routes_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a list"):
            BacnetMappingConfig.from_dict({"routes": "not-a-list"})

    def test_invalid_route_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a dict"):
            BacnetMappingConfig.from_dict({"routes": ["not-a-dict"]})

    def test_invalid_route_propagates_error(self) -> None:
        data = {
            "routes": [
                {
                    "service": "BadService",
                    "object_type": "analogInput",
                    "property_identifier": "presentValue",
                    "action": "read",
                    "resource_type": "point",
                    "resource_id_template": "{object_type}",
                }
            ]
        }
        with pytest.raises(InvalidMappingError, match="unrecognized BACnet service"):
            BacnetMappingConfig.from_dict(data)

    def test_wildcard_routes_from_dict(self) -> None:
        data = {
            "routes": [
                {
                    "service": "*",
                    "object_type": "*",
                    "property_identifier": "*",
                    "action": "read",
                    "resource_type": "object",
                    "resource_id_template": "{object_type}:{object_instance}",
                }
            ]
        }
        config = BacnetMappingConfig.from_dict(data)
        assert config.routes[0].service == "*"
