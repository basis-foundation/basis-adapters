"""
Tests for IEC 61850 mapping configuration validation and matching.

Covers route validation (eager, fail-fast), config construction, duplicate
name detection, from_dict parsing, route matching, action resolution, and
resource ID template rendering.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.iec61850.mapping import (
    VALID_IEC61850_TEMPLATE_FIELDS,
    Iec61850MappingConfig,
    Iec61850Operation,
    Iec61850RouteMapping,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

DO_TEMPLATE = "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/do:{data_object}"
DA_TEMPLATE = DO_TEMPLATE + "/da:{data_attribute}"
RCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/rcb:{report_control_block}"
)
GCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}/gcb:{goose_control_block}"
)
SVCB_TEMPLATE = (
    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
    "/svcb:{sampled_values_control_block}"
)


def make_route(**kwargs: object) -> Iec61850RouteMapping:
    defaults: dict[str, object] = {
        "operation": "READ",
        "logical_node": "*",
        "action": "read",
        "resource_type": "iec61850_data_attribute",
        "resource_id_template": DA_TEMPLATE,
        "name": "",
    }
    defaults.update(kwargs)
    return Iec61850RouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> Iec61850Operation:
    defaults: dict[str, object] = {
        "operation": "READ",
        "ied_name": "ied-sub1",
        "logical_device": "MEAS",
        "logical_node": "MMXU1",
        "data_object": "TotW",
        "data_attribute": "mag",
    }
    defaults.update(kwargs)
    return Iec61850Operation(**defaults)  # type: ignore[arg-type]


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
            make_route(operation="GET_DIRECTORY")

    def test_lowercase_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="read")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="")

    def test_empty_logical_node_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(logical_node="")

    def test_wildcard_logical_node_allowed(self) -> None:
        route = make_route(logical_node="*")
        assert route.logical_node == "*"

    def test_exact_logical_node_allowed(self) -> None:
        route = make_route(logical_node="CSWI1")
        assert route.logical_node == "CSWI1"

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(action="actuate")

    def test_execute_action_allowed(self) -> None:
        route = make_route(operation="SELECT", action="execute", resource_id_template=DO_TEMPLATE)
        assert route.action == "execute"

    def test_browse_action_rejected_for_iec61850(self) -> None:
        """'browse' is an OPC UA verb — IEC 61850 routes do not accept it."""
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
            make_route(resource_id_template="iec61850:ied:{ied_name")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template="iec61850:{node_id}")

    @pytest.mark.parametrize(
        "evidence_field", ["value", "quality", "timestamp", "origin", "cause", "control_model"]
    )
    def test_evidence_only_template_field_rejected(self, evidence_field: str) -> None:
        """Values, quality, timestamps, origin, cause, and control model are
        evidence, never resource identity."""
        assert evidence_field not in VALID_IEC61850_TEMPLATE_FIELDS
        with pytest.raises(InvalidMappingError):
            make_route(resource_id_template=DA_TEMPLATE + "/{" + evidence_field + "}")

    @pytest.mark.parametrize(
        "operation", ["SELECT", "SELECT_WITH_VALUE", "OPERATE", "DIRECT_OPERATE", "CANCEL"]
    )
    def test_control_route_without_data_object_rejected(self, operation: str) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(
                operation=operation,
                action="execute",
                resource_id_template=(
                    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
                ),
            )

    @pytest.mark.parametrize(
        ("operation", "template"),
        [
            ("ENABLE_REPORTING", RCB_TEMPLATE),
            ("ENABLE_GOOSE", GCB_TEMPLATE),
            ("ENABLE_SAMPLED_VALUES", SVCB_TEMPLATE),
        ],
    )
    def test_subscription_route_with_control_block_allowed(
        self, operation: str, template: str
    ) -> None:
        route = make_route(operation=operation, action="subscribe", resource_id_template=template)
        assert route.operation == operation

    @pytest.mark.parametrize(
        "operation", ["ENABLE_REPORTING", "ENABLE_GOOSE", "ENABLE_SAMPLED_VALUES"]
    )
    def test_subscription_route_without_control_block_rejected(self, operation: str) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(
                operation=operation,
                action="subscribe",
                resource_id_template=(
                    "iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}"
                ),
            )

    def test_read_route_without_data_object_allowed(self) -> None:
        route = make_route(
            operation="READ",
            resource_id_template="iec61850:ied:{ied_name}/ld:{logical_device}/ln:{logical_node}",
        )
        assert route.operation == "READ"


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_empty_config_allowed(self) -> None:
        config = Iec61850MappingConfig(routes=[])
        assert config.routes == []

    def test_duplicate_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            Iec61850MappingConfig(routes=[make_route(name="dup"), make_route(name="dup")])

    def test_empty_names_not_duplicates(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(name=""), make_route(name="")])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_parses_valid_config(self) -> None:
        config = Iec61850MappingConfig.from_dict(
            {
                "routes": [
                    {
                        "name": "read-da",
                        "operation": "READ",
                        "logical_node": "*",
                        "action": "read",
                        "resource_type": "iec61850_data_attribute",
                        "resource_id_template": DA_TEMPLATE,
                    }
                ]
            }
        )
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-da"

    def test_logical_node_defaults_to_wildcard(self) -> None:
        config = Iec61850MappingConfig.from_dict(
            {
                "routes": [
                    {
                        "operation": "READ",
                        "resource_type": "iec61850_data_object",
                        "resource_id_template": "iec61850:ied:{ied_name}",
                    }
                ]
            }
        )
        assert config.routes[0].logical_node == "*"

    def test_routes_must_be_list(self) -> None:
        with pytest.raises(InvalidMappingError):
            Iec61850MappingConfig.from_dict({"routes": "not-a-list"})

    def test_route_must_be_dict(self) -> None:
        with pytest.raises(InvalidMappingError):
            Iec61850MappingConfig.from_dict({"routes": ["not-a-dict"]})

    def test_invalid_route_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            Iec61850MappingConfig.from_dict(
                {
                    "routes": [
                        {
                            "operation": "BOGUS",
                            "resource_type": "iec61850_data_object",
                            "resource_id_template": "iec61850:ied:{ied_name}",
                        }
                    ]
                }
            )

    def test_example_mapping_file_parses(self) -> None:
        with (EXAMPLES / "iec61850" / "mapping.example.json").open() as f:
            config = Iec61850MappingConfig.from_dict(json.load(f))
        assert len(config.routes) > 0

    def test_invalid_example_mapping_file_rejected(self) -> None:
        with (EXAMPLES / "iec61850" / "mapping-invalid.example.json").open() as f:
            data = json.load(f)
        with pytest.raises(InvalidMappingError):
            Iec61850MappingConfig.from_dict(data)

    def test_each_invalid_example_route_rejected_individually(self) -> None:
        """Every route in the invalid example demonstrates a distinct error."""
        with (EXAMPLES / "iec61850" / "mapping-invalid.example.json").open() as f:
            data = json.load(f)
        for raw_route in data["routes"]:
            with pytest.raises(InvalidMappingError):
                Iec61850MappingConfig.from_dict({"routes": [raw_route]})


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:
    def test_exact_match(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(name="r1")])
        route = config.match(make_op())
        assert route.name == "r1"

    def test_wildcard_operation_matches(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(operation="*", name="any")])
        route = config.match(make_op(operation="READ"))
        assert route.name == "any"

    def test_exact_logical_node_matches(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(logical_node="MMXU1", name="exact")])
        route = config.match(make_op())
        assert route.name == "exact"

    def test_wildcard_logical_node_matches_absent(self) -> None:
        config = Iec61850MappingConfig(
            routes=[
                make_route(
                    operation="READ",
                    logical_node="*",
                    resource_id_template="iec61850:ied:{ied_name}",
                    name="ied-read",
                )
            ]
        )
        route = config.match(make_op(logical_node=None, data_object=None, data_attribute=None))
        assert route.name == "ied-read"

    def test_exact_logical_node_does_not_match_absent(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(logical_node="MMXU1")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(logical_node=None, data_object=None, data_attribute=None))

    def test_no_match_raises_unknown_route(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(operation="READ")])
        with pytest.raises(UnknownRouteError):
            config.match(
                make_op(operation="DIRECT_OPERATE", data_object="Pos", data_attribute=None)
            )

    def test_first_match_wins(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(name="first"), make_route(name="second")])
        assert config.match(make_op()).name == "first"


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    def test_explicit_action_wins(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route(action="discover")])
        route = config.routes[0]
        assert config.resolve_action(route, make_op()) == "discover"

    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("READ", "read"),
            ("WRITE", "write"),
            ("SELECT", "execute"),
            ("SELECT_WITH_VALUE", "execute"),
            ("OPERATE", "execute"),
            ("DIRECT_OPERATE", "execute"),
            ("CANCEL", "execute"),
            ("ENABLE_REPORTING", "subscribe"),
            ("ENABLE_GOOSE", "subscribe"),
            ("ENABLE_SAMPLED_VALUES", "subscribe"),
        ],
    )
    def test_default_action_map(self, operation: str, expected: str) -> None:
        config = Iec61850MappingConfig(routes=[make_route(operation="*", action="")])
        route = config.routes[0]
        op = make_op(operation=operation)
        assert config.resolve_action(route, op) == expected


# ---------------------------------------------------------------------------
# Resource ID rendering
# ---------------------------------------------------------------------------


class TestResourceIdRendering:
    def test_renders_data_attribute_template(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route()])
        route = config.routes[0]
        rid = config.resolve_resource_id(route, make_op())
        assert rid == "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag"

    def test_renders_control_block_template(self) -> None:
        config = Iec61850MappingConfig(
            routes=[
                make_route(
                    operation="ENABLE_REPORTING",
                    action="subscribe",
                    resource_id_template=RCB_TEMPLATE,
                )
            ]
        )
        route = config.routes[0]
        rid = config.resolve_resource_id(
            route,
            make_op(
                operation="ENABLE_REPORTING",
                logical_node="LLN0",
                data_object=None,
                data_attribute=None,
                report_control_block="urcbMX01",
            ),
        )
        assert rid == "iec61850:ied:ied-sub1/ld:MEAS/ln:LLN0/rcb:urcbMX01"

    def test_absent_optional_field_fails_closed(self) -> None:
        config = Iec61850MappingConfig(routes=[make_route()])
        route = config.routes[0]
        with pytest.raises(InvalidMappingError):
            config.resolve_resource_id(route, make_op(data_attribute=None))

    def test_dataset_renderable_when_present(self) -> None:
        template = "iec61850:ied:{ied_name}/dataset:{dataset}"
        config = Iec61850MappingConfig(routes=[make_route(resource_id_template=template)])
        route = config.routes[0]
        rid = config.resolve_resource_id(route, make_op(dataset="MeasFlt"))
        assert rid == "iec61850:ied:ied-sub1/dataset:MeasFlt"

    def test_functional_constraint_renderable_when_present(self) -> None:
        template = DA_TEMPLATE + "/fc:{functional_constraint}"
        config = Iec61850MappingConfig(routes=[make_route(resource_id_template=template)])
        route = config.routes[0]
        rid = config.resolve_resource_id(route, make_op(functional_constraint="MX"))
        assert rid == "iec61850:ied:ied-sub1/ld:MEAS/ln:MMXU1/do:TotW/da:mag/fc:MX"
