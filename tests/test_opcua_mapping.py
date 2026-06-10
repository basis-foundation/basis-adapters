"""
OPC UA mapping configuration tests — Phase 7.

Covers route validation, duplicate-name rejection, matching (exact, wildcard,
attribute), first-match-wins ordering, action resolution, resource ID template
substitution, and from_dict parsing.
"""

from __future__ import annotations

from typing import Any

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.opcua.mapping import (
    VALID_OPCUA_ACTIONS,
    VALID_OPCUA_SERVICES,
    VALID_OPCUA_TEMPLATE_FIELDS,
    OpcuaMappingConfig,
    OpcuaOperation,
    OpcuaRouteMapping,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_route(**kwargs: object) -> OpcuaRouteMapping:
    defaults: dict[str, object] = {
        "service": "Read",
        "attribute_id": "Value",
        "action": "read",
        "resource_type": "opcua_node",
        "resource_id_template": "{node_id}:{attribute_id}",
        "name": "",
    }
    defaults.update(kwargs)
    return OpcuaRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> OpcuaOperation:
    defaults: dict[str, object] = {
        "service": "Read",
        "node_id": "ns=2;s=Building.AHU1.SupplyTemp",
        "attribute_id": "Value",
    }
    defaults.update(kwargs)
    return OpcuaOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route validation
# ---------------------------------------------------------------------------


class TestRouteValidation:
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        assert route.service == "Read"

    def test_all_valid_services_accepted(self) -> None:
        for service in VALID_OPCUA_SERVICES:
            template = "{node_id}:method:{method_id}" if service == "Call" else "{node_id}"
            route = make_route(service=service, action="", resource_id_template=template)
            assert route.service == service

    def test_wildcard_service_accepted(self) -> None:
        route = make_route(service="*")
        assert route.service == "*"

    def test_missing_service_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(service="")

    def test_unsupported_service_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized OPC UA service"):
            make_route(service="HistoryRead")

    def test_lowercase_service_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(service="read")

    def test_empty_attribute_id_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="attribute_id"):
            make_route(attribute_id="")

    def test_wildcard_attribute_id_accepted(self) -> None:
        route = make_route(attribute_id="*")
        assert route.attribute_id == "*"

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="launch")

    def test_empty_action_accepted_for_default_resolution(self) -> None:
        route = make_route(action="")
        assert route.action == ""

    def test_execute_action_accepted(self) -> None:
        route = make_route(
            service="Call",
            action="execute",
            resource_id_template="{node_id}:method:{method_id}",
        )
        assert route.action == "execute"

    def test_browse_action_accepted(self) -> None:
        route = make_route(service="Browse", action="browse", resource_id_template="{node_id}")
        assert route.action == "browse"

    def test_all_valid_actions_accepted(self) -> None:
        for action in VALID_OPCUA_ACTIONS:
            route = make_route(action=action)
            assert route.action == action

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type"):
            make_route(resource_type="")

    def test_whitespace_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type"):
            make_route(resource_type="   ")

    def test_empty_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template"):
            make_route(resource_id_template="")

    def test_malformed_template_unclosed_brace_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed"):
            make_route(resource_id_template="{node_id")

    def test_template_unknown_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template="{node_id}:{register_type}")

    def test_template_valid_fields_accepted(self) -> None:
        template = ":".join(f"{{{f}}}" for f in sorted(VALID_OPCUA_TEMPLATE_FIELDS))
        route = make_route(resource_id_template=template)
        assert route.resource_id_template == template

    def test_call_route_without_method_id_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="method_id"):
            make_route(service="Call", action="execute", resource_id_template="{node_id}")

    def test_call_route_with_method_id_template_accepted(self) -> None:
        route = make_route(
            service="Call",
            action="execute",
            resource_id_template="{node_id}:method:{method_id}",
        )
        assert route.service == "Call"


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_empty_config_constructs(self) -> None:
        config = OpcuaMappingConfig(routes=[])
        assert config.routes == []

    def test_duplicate_route_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            OpcuaMappingConfig(
                routes=[make_route(name="dup"), make_route(name="dup", service="Write")]
            )

    def test_multiple_unnamed_routes_allowed(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(), make_route(service="Write")])
        assert len(config.routes) == 2

    def test_distinct_names_allowed(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(name="a"), make_route(name="b")])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:
    def test_exact_service_match(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(service="Read", name="r")])
        route = config.match(make_op(service="Read"))
        assert route.name == "r"

    def test_exact_service_mismatch_raises(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(service="Write")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(service="Read"))

    def test_wildcard_service_matches_any(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(service="*", attribute_id="*")])
        for service in ("Read", "Write", "Subscribe", "Browse"):
            route = config.match(make_op(service=service))
            assert route.service == "*"

    def test_exact_attribute_match(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(attribute_id="Value")])
        route = config.match(make_op(attribute_id="Value"))
        assert route.attribute_id == "Value"

    def test_attribute_mismatch_raises(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(attribute_id="Value")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(attribute_id="DisplayName"))

    def test_exact_attribute_does_not_match_absent_attribute(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(attribute_id="Value")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(attribute_id=None))

    def test_wildcard_attribute_matches_absent_attribute(self) -> None:
        config = OpcuaMappingConfig(
            routes=[make_route(attribute_id="*", resource_id_template="{node_id}")]
        )
        route = config.match(make_op(attribute_id=None))
        assert route.attribute_id == "*"

    def test_first_match_wins(self) -> None:
        config = OpcuaMappingConfig(
            routes=[
                make_route(service="*", attribute_id="*", name="first"),
                make_route(service="Read", attribute_id="Value", name="second"),
            ]
        )
        route = config.match(make_op())
        assert route.name == "first"

    def test_first_match_wins_with_specific_route_first(self) -> None:
        config = OpcuaMappingConfig(
            routes=[
                make_route(service="Read", attribute_id="Value", name="specific"),
                make_route(service="*", attribute_id="*", name="fallback"),
            ]
        )
        assert config.match(make_op()).name == "specific"
        assert config.match(make_op(service="Browse", attribute_id=None)).name == "fallback"

    def test_no_routes_raises(self) -> None:
        config = OpcuaMappingConfig(routes=[])
        with pytest.raises(UnknownRouteError):
            config.match(make_op())


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    def test_explicit_action_used(self) -> None:
        config = OpcuaMappingConfig(routes=[make_route(action="control")])
        route = config.match(make_op())
        assert config.resolve_action(route, make_op()) == "control"

    @pytest.mark.parametrize(
        ("service", "expected"),
        [
            ("Read", "read"),
            ("Write", "write"),
            ("Call", "execute"),
            ("Subscribe", "subscribe"),
            ("Browse", "browse"),
        ],
    )
    def test_default_action_map(self, service: str, expected: str) -> None:
        template = "{node_id}:method:{method_id}" if service == "Call" else "{node_id}"
        route = make_route(service=service, action="", resource_id_template=template)
        config = OpcuaMappingConfig(routes=[route])
        op = make_op(service=service, method_id="ns=2;s=M" if service == "Call" else None)
        assert config.resolve_action(route, op) == expected


# ---------------------------------------------------------------------------
# Resource ID template substitution
# ---------------------------------------------------------------------------


class TestResourceIdTemplates:
    def test_node_and_attribute_substitution(self) -> None:
        route = make_route(resource_id_template="{node_id}:{attribute_id}")
        config = OpcuaMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op())
        assert rid == "ns=2;s=Building.AHU1.SupplyTemp:Value"

    def test_method_substitution(self) -> None:
        route = make_route(
            service="Call",
            attribute_id="*",
            action="execute",
            resource_id_template="{node_id}:method:{method_id}",
        )
        config = OpcuaMappingConfig(routes=[route])
        op = make_op(
            service="Call",
            node_id="ns=2;s=Building.AHU1",
            attribute_id=None,
            method_id="ns=2;s=Building.AHU1.Reset",
        )
        rid = config.resolve_resource_id(route, op)
        assert rid == "ns=2;s=Building.AHU1:method:ns=2;s=Building.AHU1.Reset"

    def test_service_substitution(self) -> None:
        route = make_route(resource_id_template="{service}:{node_id}")
        config = OpcuaMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op())
        assert rid == "Read:ns=2;s=Building.AHU1.SupplyTemp"

    def test_namespace_index_substitution(self) -> None:
        route = make_route(resource_id_template="ns{namespace_index}:{node_id}")
        config = OpcuaMappingConfig(routes=[route])
        rid = config.resolve_resource_id(route, make_op(namespace_index=2))
        assert rid == "ns2:ns=2;s=Building.AHU1.SupplyTemp"

    def test_browse_name_and_parent_substitution(self) -> None:
        route = make_route(resource_id_template="{parent_node_id}/{browse_name}")
        config = OpcuaMappingConfig(routes=[route])
        rid = config.resolve_resource_id(
            route, make_op(browse_name="SupplyTemp", parent_node_id="ns=2;s=Building.AHU1")
        )
        assert rid == "ns=2;s=Building.AHU1/SupplyTemp"

    def test_template_referencing_absent_optional_field_fails(self) -> None:
        route = make_route(attribute_id="*", resource_id_template="{node_id}:{method_id}")
        config = OpcuaMappingConfig(routes=[route])
        with pytest.raises(InvalidMappingError, match="not available"):
            config.resolve_resource_id(route, make_op(method_id=None))

    def test_template_referencing_absent_attribute_fails(self) -> None:
        route = make_route(attribute_id="*", resource_id_template="{node_id}:{attribute_id}")
        config = OpcuaMappingConfig(routes=[route])
        with pytest.raises(InvalidMappingError, match="not available"):
            config.resolve_resource_id(route, make_op(attribute_id=None))


# ---------------------------------------------------------------------------
# from_dict parsing
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_valid_config_parses(self) -> None:
        data: dict[str, Any] = {
            "routes": [
                {
                    "name": "read-node-value",
                    "service": "Read",
                    "attribute_id": "Value",
                    "action": "read",
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}:{attribute_id}",
                }
            ]
        }
        config = OpcuaMappingConfig.from_dict(data)
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-node-value"

    def test_missing_routes_key_yields_empty_config(self) -> None:
        config = OpcuaMappingConfig.from_dict({})
        assert config.routes == []

    def test_routes_not_a_list_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a list"):
            OpcuaMappingConfig.from_dict({"routes": {"service": "Read"}})

    def test_route_not_a_dict_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a dict"):
            OpcuaMappingConfig.from_dict({"routes": ["Read"]})

    def test_missing_service_rejected(self) -> None:
        data = {
            "routes": [
                {
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}",
                }
            ]
        }
        with pytest.raises(InvalidMappingError):
            OpcuaMappingConfig.from_dict(data)

    def test_attribute_id_defaults_to_wildcard(self) -> None:
        data = {
            "routes": [
                {
                    "service": "Read",
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}",
                }
            ]
        }
        config = OpcuaMappingConfig.from_dict(data)
        assert config.routes[0].attribute_id == "*"

    def test_duplicate_names_rejected_via_from_dict(self) -> None:
        data = {
            "routes": [
                {
                    "name": "dup",
                    "service": "Read",
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}",
                },
                {
                    "name": "dup",
                    "service": "Write",
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}",
                },
            ]
        }
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            OpcuaMappingConfig.from_dict(data)

    def test_annotation_keys_ignored(self) -> None:
        data = {
            "_comment": "annotation",
            "routes": [
                {
                    "service": "Read",
                    "attribute_id": "Value",
                    "resource_type": "opcua_node",
                    "resource_id_template": "{node_id}",
                }
            ],
        }
        config = OpcuaMappingConfig.from_dict(data)
        assert len(config.routes) == 1
