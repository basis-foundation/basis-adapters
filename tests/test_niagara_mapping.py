"""
Niagara mapping configuration tests.

These tests verify that:
1. Valid Niagara route mappings construct successfully.
2. Invalid operations, actions, resource types, and templates are rejected
   eagerly (InvalidMappingError at construction time).
3. Evidence-only fields (value, facet, point_type, baja_type, nav_path,
   category, niagara_user, niagara_role) can never appear in resource ID
   templates — the identity boundary in particular: Niagara users and roles
   are never resource identity and never BASIS identity.
4. Route matching is first-match-wins with "*" wildcards and verbatim
   station comparison.
5. Default action resolution follows the Niagara operation→action map.
6. from_dict() parses and validates plain dictionaries.
"""

from __future__ import annotations

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.niagara.mapping import (
    VALID_NIAGARA_TEMPLATE_FIELDS,
    NiagaraMappingConfig,
    NiagaraOperation,
    NiagaraRouteMapping,
)


def make_route(**kwargs: object) -> NiagaraRouteMapping:
    defaults: dict[str, object] = {
        "operation": "READ_POINT",
        "station": "*",
        "action": "",
        "resource_type": "niagara_point",
        "resource_id_template": "niagara:station:{station}/point:{point}",
        "name": "",
    }
    defaults.update(kwargs)
    return NiagaraRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> NiagaraOperation:
    defaults: dict[str, object] = {
        "operation": "READ_POINT",
        "station": "station-east",
        "point": "AHU1-SupplyTemp",
    }
    defaults.update(kwargs)
    return NiagaraOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route construction — valid cases
# ---------------------------------------------------------------------------


class TestRouteConstruction:
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        assert route.operation == "READ_POINT"

    @pytest.mark.parametrize(
        "operation",
        [
            "READ_COMPONENT",
            "READ_POINT",
            "READ_SLOT",
            "READ_HISTORY",
            "READ_ALARM",
            "READ_SCHEDULE",
            "WRITE_POINT",
            "WRITE_SLOT",
            "UPDATE_SCHEDULE",
            "ACK_ALARM",
            "INVOKE_ACTION",
            "COMMAND_POINT",
            "OVERRIDE_POINT",
            "RELEASE_OVERRIDE",
            "BROWSE",
            "RESOLVE_ORD",
            "LIST_CHILDREN",
            "SUBSCRIBE_POINT",
            "SUBSCRIBE_ALARM",
            "SUBSCRIBE_HISTORY",
            "*",
        ],
    )
    def test_all_operations_accepted(self, operation: str) -> None:
        route = make_route(operation=operation)
        assert route.operation == operation

    @pytest.mark.parametrize(
        "action",
        ["read", "write", "control", "discover", "subscribe", "execute", "browse", ""],
    )
    def test_valid_actions_accepted(self, action: str) -> None:
        route = make_route(action=action)
        assert route.action == action

    def test_template_may_reference_all_valid_fields(self) -> None:
        template = "/".join(f"{{{f}}}" for f in sorted(VALID_NIAGARA_TEMPLATE_FIELDS))
        route = make_route(resource_id_template=template)
        assert route.resource_id_template == template

    def test_exact_station_route_accepted(self) -> None:
        route = make_route(station="station-east")
        assert route.station == "station-east"


# ---------------------------------------------------------------------------
# Route construction — invalid cases (fail eagerly)
# ---------------------------------------------------------------------------


class TestRouteValidation:
    def test_unknown_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized Niagara operation"):
            make_route(operation="FOX_LOGIN")

    def test_lowercase_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized Niagara operation"):
            make_route(operation="read_point")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="")

    def test_empty_station_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="station"):
            make_route(station="")

    def test_whitespace_station_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="station"):
            make_route(station="   ")

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="actuate")

    def test_execute_and_browse_actions_accepted_for_niagara(self) -> None:
        """Niagara reuses the pre-existing execute/browse verbs — no new
        action vocabulary was added."""
        assert make_route(action="execute").action == "execute"
        assert make_route(action="browse").action == "browse"

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type"):
            make_route(resource_type="")

    def test_empty_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template"):
            make_route(resource_id_template="")

    def test_malformed_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed token"):
            make_route(resource_id_template="niagara:station:{station")

    @pytest.mark.parametrize(
        "field_name",
        [
            "value",
            "facet",
            "point_type",
            "baja_type",
            "nav_path",
            "category",
            "niagara_user",
            "niagara_role",
            "metadata",
        ],
    )
    def test_evidence_fields_rejected_in_template(self, field_name: str) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template=f"niagara:station:{{station}}/{{{field_name}}}")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template="niagara:{nonexistent}")


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_empty_config_constructs(self) -> None:
        config = NiagaraMappingConfig()
        assert config.routes == []

    def test_duplicate_route_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            NiagaraMappingConfig(
                routes=[
                    make_route(name="dup"),
                    make_route(name="dup", operation="WRITE_POINT"),
                ]
            )

    def test_unnamed_routes_may_repeat(self) -> None:
        config = NiagaraMappingConfig(routes=[make_route(), make_route()])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_exact_match(self) -> None:
        route = make_route(operation="READ_POINT", station="station-east")
        config = NiagaraMappingConfig(routes=[route])
        assert config.match(make_op()) is route

    def test_wildcard_operation_matches(self) -> None:
        route = make_route(operation="*")
        config = NiagaraMappingConfig(routes=[route])
        assert config.match(make_op(operation="SUBSCRIBE_POINT")) is route

    def test_wildcard_station_matches(self) -> None:
        route = make_route(station="*")
        config = NiagaraMappingConfig(routes=[route])
        assert config.match(make_op(station="station-west")) is route

    def test_station_matched_verbatim(self) -> None:
        """An exact station route must not match a different station — no
        host resolution, no supervisor topology inference."""
        route = make_route(station="station-east")
        config = NiagaraMappingConfig(routes=[route])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(station="station-east-2"))

    def test_first_match_wins(self) -> None:
        specific = make_route(station="station-east", name="specific")
        broad = make_route(station="*", name="broad")
        config = NiagaraMappingConfig(routes=[specific, broad])
        assert config.match(make_op()) is specific

    def test_no_match_raises_unknown_route(self) -> None:
        config = NiagaraMappingConfig(routes=[make_route(operation="WRITE_POINT")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(operation="READ_POINT"))

    def test_empty_config_never_matches(self) -> None:
        config = NiagaraMappingConfig()
        with pytest.raises(UnknownRouteError):
            config.match(make_op())


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("READ_COMPONENT", "read"),
            ("READ_POINT", "read"),
            ("READ_SLOT", "read"),
            ("READ_HISTORY", "read"),
            ("READ_ALARM", "read"),
            ("READ_SCHEDULE", "read"),
            ("WRITE_POINT", "write"),
            ("WRITE_SLOT", "write"),
            ("UPDATE_SCHEDULE", "write"),
            ("ACK_ALARM", "execute"),
            ("INVOKE_ACTION", "execute"),
            ("COMMAND_POINT", "execute"),
            ("OVERRIDE_POINT", "execute"),
            ("RELEASE_OVERRIDE", "execute"),
            ("BROWSE", "browse"),
            ("RESOLVE_ORD", "browse"),
            ("LIST_CHILDREN", "browse"),
            ("SUBSCRIBE_POINT", "subscribe"),
            ("SUBSCRIBE_ALARM", "subscribe"),
            ("SUBSCRIBE_HISTORY", "subscribe"),
        ],
    )
    def test_default_action_map(self, operation: str, expected: str) -> None:
        route = make_route(operation="*", action="")
        config = NiagaraMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(operation=operation)) == expected

    def test_explicit_action_overrides_default(self) -> None:
        route = make_route(operation="ACK_ALARM", action="write")
        config = NiagaraMappingConfig(routes=[route])
        op = make_op(operation="ACK_ALARM", alarm="AHU1-HighSupplyTemp")
        assert config.resolve_action(route, op) == "write"


# ---------------------------------------------------------------------------
# Resource ID resolution
# ---------------------------------------------------------------------------


class TestResourceIdResolution:
    def test_point_template(self) -> None:
        route = make_route()
        config = NiagaraMappingConfig(routes=[route])
        assert (
            config.resolve_resource_id(route, make_op())
            == "niagara:station:station-east/point:AHU1-SupplyTemp"
        )

    def test_ord_template_preserves_ord_exactly(self) -> None:
        ord_value = "station:|slot:/Drivers/BacnetNetwork/AHU1"
        route = make_route(resource_id_template="niagara:station:{station}/ord:{ord}")
        config = NiagaraMappingConfig(routes=[route])
        op = make_op(ord=ord_value)
        assert (
            config.resolve_resource_id(route, op) == f"niagara:station:station-east/ord:{ord_value}"
        )

    def test_component_slot_template(self) -> None:
        route = make_route(
            resource_id_template="niagara:station:{station}/component:{component}/slot:{slot}"
        )
        config = NiagaraMappingConfig(routes=[route])
        op = make_op(component="AHU1", slot="status")
        assert (
            config.resolve_resource_id(route, op)
            == "niagara:station:station-east/component:AHU1/slot:status"
        )

    def test_history_alarm_schedule_templates(self) -> None:
        cases = [
            ("niagara:station:{station}/history:{history}", {"history": "H1"}, "history:H1"),
            ("niagara:station:{station}/alarm:{alarm}", {"alarm": "A1"}, "alarm:A1"),
            ("niagara:station:{station}/schedule:{schedule}", {"schedule": "S1"}, "schedule:S1"),
        ]
        for template, fields, suffix in cases:
            route = make_route(resource_id_template=template)
            config = NiagaraMappingConfig(routes=[route])
            op = make_op(**fields)
            assert config.resolve_resource_id(route, op) == f"niagara:station:station-east/{suffix}"

    def test_absent_optional_field_fails_closed(self) -> None:
        route = make_route(resource_id_template="niagara:station:{station}/ord:{ord}")
        config = NiagaraMappingConfig(routes=[route])
        with pytest.raises(InvalidMappingError, match="not available"):
            config.resolve_resource_id(route, make_op())  # no ord

    def test_resource_id_is_deterministic(self) -> None:
        route = make_route()
        config = NiagaraMappingConfig(routes=[route])
        op = make_op()
        assert config.resolve_resource_id(route, op) == config.resolve_resource_id(route, op)


# ---------------------------------------------------------------------------
# from_dict parsing
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_valid_dict_parses(self) -> None:
        config = NiagaraMappingConfig.from_dict(
            {
                "routes": [
                    {
                        "name": "read-any-point",
                        "operation": "READ_POINT",
                        "station": "*",
                        "action": "read",
                        "resource_type": "niagara_point",
                        "resource_id_template": "niagara:station:{station}/point:{point}",
                    }
                ]
            }
        )
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-any-point"

    def test_station_defaults_to_wildcard(self) -> None:
        config = NiagaraMappingConfig.from_dict(
            {
                "routes": [
                    {
                        "operation": "READ_POINT",
                        "resource_type": "niagara_point",
                        "resource_id_template": "niagara:station:{station}/point:{point}",
                    }
                ]
            }
        )
        assert config.routes[0].station == "*"

    def test_empty_routes_parses(self) -> None:
        config = NiagaraMappingConfig.from_dict({"routes": []})
        assert config.routes == []

    def test_non_list_routes_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a list"):
            NiagaraMappingConfig.from_dict({"routes": "nope"})

    def test_non_dict_route_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a dict"):
            NiagaraMappingConfig.from_dict({"routes": ["nope"]})

    def test_invalid_route_in_dict_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            NiagaraMappingConfig.from_dict(
                {
                    "routes": [
                        {
                            "operation": "NOT_A_NIAGARA_OPERATION",
                            "resource_type": "niagara_point",
                            "resource_id_template": "niagara:station:{station}/point:{point}",
                        }
                    ]
                }
            )
