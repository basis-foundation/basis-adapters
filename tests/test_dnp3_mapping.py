"""
Tests for DNP3 mapping configuration validation and matching.

Covers route validation (eager, fail-fast), config construction, duplicate
name detection, from_dict parsing, route matching, action resolution, and
resource ID template rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basis_adapters.dnp3.mapping import (
    VALID_DNP3_TEMPLATE_FIELDS,
    Dnp3MappingConfig,
    Dnp3Operation,
    Dnp3RouteMapping,
)
from basis_adapters.errors import InvalidMappingError, UnknownRouteError

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


def make_route(**kwargs: object) -> Dnp3RouteMapping:
    defaults: dict[str, object] = {
        "operation": "READ",
        "point_type": "analog_input",
        "action": "read",
        "resource_type": "dnp3_point",
        "resource_id_template": "dnp3:outstation:{outstation_id}/analog_input/{point_index}",
        "name": "",
    }
    defaults.update(kwargs)
    return Dnp3RouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> Dnp3Operation:
    defaults: dict[str, object] = {
        "operation": "READ",
        "outstation_id": "os-14",
        "point_type": "analog_input",
        "point_index": 3,
    }
    defaults.update(kwargs)
    return Dnp3Operation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route validation — eager, fail fast
# ---------------------------------------------------------------------------


class TestRouteValidation:
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        assert route.operation == "READ"

    def test_wildcard_operation_allowed(self) -> None:
        route = make_route(operation="*")
        assert route.operation == "*"

    def test_unknown_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="WRITE_FREEZE")

    def test_lowercase_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="read")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="")

    def test_unknown_point_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(point_type="thermocouple")

    def test_wildcard_point_type_allowed(self) -> None:
        route = make_route(point_type="*")
        assert route.point_type == "*"

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(action="actuate")

    def test_execute_action_allowed(self) -> None:
        route = make_route(
            operation="SELECT",
            action="execute",
            resource_id_template="dnp3:outstation:{outstation_id}/binary_output/{point_index}",
        )
        assert route.action == "execute"

    def test_browse_action_rejected_for_dnp3(self) -> None:
        """'browse' is an OPC UA verb — DNP3 routes do not accept it."""
        with pytest.raises(InvalidMappingError):
            make_route(action="browse")

    def test_empty_action_allowed_for_default_mapping(self) -> None:
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
            make_route(resource_id_template="dnp3:outstation:{outstation_id")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="dnp3:{node_id}")

    def test_value_template_field_rejected(self) -> None:
        """Command values are evidence, never resource identity."""
        assert "value" not in VALID_DNP3_TEMPLATE_FIELDS
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="dnp3:outstation:{outstation_id}/{point_index}/{value}")

    @pytest.mark.parametrize("operation", ["SELECT", "OPERATE", "DIRECT_OPERATE", "CONTROL"])
    def test_control_route_without_point_index_rejected(self, operation: str) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(
                operation=operation,
                point_type="binary_output",
                action="execute",
                resource_id_template="dnp3:outstation:{outstation_id}",
            )

    def test_read_route_without_point_index_allowed(self) -> None:
        route = make_route(
            operation="READ",
            point_type="*",
            resource_id_template="dnp3:outstation:{outstation_id}/group/{object_group}",
        )
        assert route.operation == "READ"


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_empty_config_allowed(self) -> None:
        config = Dnp3MappingConfig(routes=[])
        assert config.routes == []

    def test_duplicate_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            Dnp3MappingConfig(routes=[make_route(name="dup"), make_route(name="dup")])

    def test_empty_names_not_duplicates(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(name=""), make_route(name="")])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_parses_valid_config(self) -> None:
        config = Dnp3MappingConfig.from_dict(
            {
                "routes": [
                    {
                        "name": "read-analog",
                        "operation": "READ",
                        "point_type": "analog_input",
                        "action": "read",
                        "resource_type": "dnp3_point",
                        "resource_id_template": (
                            "dnp3:outstation:{outstation_id}/analog_input/{point_index}"
                        ),
                    }
                ]
            }
        )
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-analog"

    def test_point_type_defaults_to_wildcard(self) -> None:
        config = Dnp3MappingConfig.from_dict(
            {
                "routes": [
                    {
                        "operation": "READ",
                        "resource_type": "dnp3_point",
                        "resource_id_template": "dnp3:outstation:{outstation_id}",
                    }
                ]
            }
        )
        assert config.routes[0].point_type == "*"

    def test_routes_must_be_list(self) -> None:
        with pytest.raises(InvalidMappingError):
            Dnp3MappingConfig.from_dict({"routes": "not-a-list"})

    def test_route_must_be_dict(self) -> None:
        with pytest.raises(InvalidMappingError):
            Dnp3MappingConfig.from_dict({"routes": ["not-a-dict"]})

    def test_invalid_route_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            Dnp3MappingConfig.from_dict(
                {
                    "routes": [
                        {
                            "operation": "BOGUS",
                            "resource_type": "dnp3_point",
                            "resource_id_template": "dnp3:outstation:{outstation_id}",
                        }
                    ]
                }
            )

    def test_example_mapping_file_parses(self) -> None:
        with (EXAMPLES / "dnp3" / "mapping.example.json").open() as f:
            config = Dnp3MappingConfig.from_dict(json.load(f))
        assert len(config.routes) > 0

    def test_invalid_example_mapping_file_rejected(self) -> None:
        with (EXAMPLES / "dnp3" / "mapping-invalid.example.json").open() as f:
            data = json.load(f)
        with pytest.raises(InvalidMappingError):
            Dnp3MappingConfig.from_dict(data)

    def test_each_invalid_example_route_rejected_individually(self) -> None:
        """Every route in the invalid example demonstrates a distinct error."""
        with (EXAMPLES / "dnp3" / "mapping-invalid.example.json").open() as f:
            data = json.load(f)
        for raw_route in data["routes"]:
            with pytest.raises(InvalidMappingError):
                Dnp3MappingConfig.from_dict({"routes": [raw_route]})


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:
    def test_exact_match(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(name="r1")])
        route = config.match(make_op())
        assert route.name == "r1"

    def test_wildcard_operation_matches(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(operation="*", name="any")])
        route = config.match(make_op(operation="READ"))
        assert route.name == "any"

    def test_wildcard_point_type_matches_absent(self) -> None:
        config = Dnp3MappingConfig(
            routes=[
                make_route(
                    operation="READ",
                    point_type="*",
                    resource_id_template="dnp3:outstation:{outstation_id}/group/{object_group}",
                    name="group-read",
                )
            ]
        )
        route = config.match(make_op(point_type=None, point_index=None, object_group=30))
        assert route.name == "group-read"

    def test_exact_point_type_does_not_match_absent(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(point_type="analog_input")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(point_type=None))

    def test_no_match_raises_unknown_route(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(operation="READ")])
        with pytest.raises(UnknownRouteError):
            config.match(
                make_op(operation="DIRECT_OPERATE", point_type="binary_output", point_index=7)
            )

    def test_first_match_wins(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(name="first"), make_route(name="second")])
        assert config.match(make_op()).name == "first"


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    def test_explicit_action_wins(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route(action="discover")])
        route = config.routes[0]
        assert config.resolve_action(route, make_op()) == "discover"

    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("READ", "read"),
            ("SELECT", "execute"),
            ("OPERATE", "execute"),
            ("DIRECT_OPERATE", "execute"),
            ("CONTROL", "execute"),
            ("ENABLE_UNSOLICITED", "subscribe"),
        ],
    )
    def test_default_action_map(self, operation: str, expected: str) -> None:
        config = Dnp3MappingConfig(routes=[make_route(operation="*", action="")])
        route = config.routes[0]
        op = make_op(operation=operation, point_index=7, point_type="binary_output")
        assert config.resolve_action(route, op) == expected


# ---------------------------------------------------------------------------
# Resource ID rendering
# ---------------------------------------------------------------------------


class TestResourceIdRendering:
    def test_renders_point_template(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route()])
        route = config.routes[0]
        rid = config.resolve_resource_id(route, make_op())
        assert rid == "dnp3:outstation:os-14/analog_input/3"

    def test_renders_group_variation_template(self) -> None:
        template = "dnp3:outstation:{outstation_id}/group/{object_group}/variation/{variation}"
        config = Dnp3MappingConfig(
            routes=[make_route(point_type="*", resource_id_template=template)]
        )
        route = config.routes[0]
        rid = config.resolve_resource_id(
            route, make_op(point_type=None, point_index=None, object_group=30, variation=5)
        )
        assert rid == "dnp3:outstation:os-14/group/30/variation/5"

    def test_absent_optional_field_fails_closed(self) -> None:
        config = Dnp3MappingConfig(routes=[make_route()])
        route = config.routes[0]
        with pytest.raises(InvalidMappingError):
            config.resolve_resource_id(route, make_op(outstation_id=None, destination_address=10))

    def test_master_id_renderable_when_present(self) -> None:
        template = "dnp3:{master_id}:outstation:{outstation_id}/{point_type}/{point_index}"
        config = Dnp3MappingConfig(routes=[make_route(resource_id_template=template)])
        route = config.routes[0]
        rid = config.resolve_resource_id(route, make_op(master_id="master-1"))
        assert rid == "dnp3:master-1:outstation:os-14/analog_input/3"
