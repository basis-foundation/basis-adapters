"""
KNX mapping configuration tests.

These tests verify that:
1. Valid KNX route mappings construct successfully.
2. Invalid operations, actions, resource types, and templates are rejected
   eagerly (InvalidMappingError at construction time).
3. Evidence-only fields (value, payload_type, priority, datapoint_type) can
   never appear in resource ID templates.
4. Route matching is first-match-wins with "*" wildcards and verbatim group
   address comparison.
5. Default action resolution follows the KNX operation→action map.
6. from_dict() parses and validates plain dictionaries.
7. Address/DPT format helpers accept valid KNX notation and reject malformed
   input.
"""

from __future__ import annotations

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.knx.mapping import (
    VALID_KNX_TEMPLATE_FIELDS,
    KnxMappingConfig,
    KnxOperation,
    KnxRouteMapping,
    is_valid_datapoint_type,
    is_valid_group_address,
    is_valid_individual_address,
)


def make_route(**kwargs: object) -> KnxRouteMapping:
    defaults: dict[str, object] = {
        "operation": "GROUP_VALUE_READ",
        "group_address": "*",
        "action": "",
        "resource_type": "knx_group_address",
        "resource_id_template": "knx:group:{group_address}",
        "name": "",
    }
    defaults.update(kwargs)
    return KnxRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> KnxOperation:
    defaults: dict[str, object] = {
        "operation": "GROUP_VALUE_READ",
        "group_address": "1/2/3",
    }
    defaults.update(kwargs)
    return KnxOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route construction — valid cases
# ---------------------------------------------------------------------------


class TestRouteConstruction:
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        assert route.operation == "GROUP_VALUE_READ"

    @pytest.mark.parametrize(
        "operation",
        ["GROUP_VALUE_READ", "GROUP_VALUE_WRITE", "GROUP_VALUE_RESPONSE", "OBSERVE", "*"],
    )
    def test_all_operations_accepted(self, operation: str) -> None:
        route = make_route(operation=operation)
        assert route.operation == operation

    @pytest.mark.parametrize("action", ["read", "write", "control", "discover", "subscribe", ""])
    def test_valid_actions_accepted(self, action: str) -> None:
        route = make_route(action=action)
        assert route.action == action

    def test_template_may_reference_all_valid_fields(self) -> None:
        template = "/".join(f"{{{f}}}" for f in sorted(VALID_KNX_TEMPLATE_FIELDS))
        route = make_route(resource_id_template=template)
        assert route.resource_id_template == template

    def test_exact_group_address_route_accepted(self) -> None:
        route = make_route(group_address="1/2/3")
        assert route.group_address == "1/2/3"


# ---------------------------------------------------------------------------
# Route construction — invalid cases (fail eagerly)
# ---------------------------------------------------------------------------


class TestRouteValidation:
    def test_unknown_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized KNX operation"):
            make_route(operation="DEVICE_DESCRIPTOR_READ")

    def test_lowercase_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized KNX operation"):
            make_route(operation="group_value_read")

    def test_empty_operation_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            make_route(operation="")

    def test_empty_group_address_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="group_address"):
            make_route(group_address="")

    def test_whitespace_group_address_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="group_address"):
            make_route(group_address="   ")

    def test_invalid_action_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="actuate")

    def test_execute_action_rejected_for_knx(self) -> None:
        """KNX uses only the shared action set — no execute routes."""
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="execute")

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type"):
            make_route(resource_type="")

    def test_empty_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template"):
            make_route(resource_id_template="")

    def test_malformed_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed token"):
            make_route(resource_id_template="knx:group:{group_address")

    @pytest.mark.parametrize(
        "field_name", ["value", "payload_type", "priority", "datapoint_type", "metadata"]
    )
    def test_evidence_fields_rejected_in_template(self, field_name: str) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template=f"knx:group:{{group_address}}/{{{field_name}}}")

    def test_unknown_template_field_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template="knx:{nonexistent}")


# ---------------------------------------------------------------------------
# Config construction
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_empty_config_constructs(self) -> None:
        config = KnxMappingConfig()
        assert config.routes == []

    def test_duplicate_route_names_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            KnxMappingConfig(
                routes=[
                    make_route(name="dup"),
                    make_route(name="dup", operation="GROUP_VALUE_WRITE"),
                ]
            )

    def test_unnamed_routes_may_repeat(self) -> None:
        config = KnxMappingConfig(routes=[make_route(), make_route()])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_exact_match(self) -> None:
        route = make_route(operation="GROUP_VALUE_READ", group_address="1/2/3")
        config = KnxMappingConfig(routes=[route])
        assert config.match(make_op()) is route

    def test_wildcard_operation_matches(self) -> None:
        route = make_route(operation="*")
        config = KnxMappingConfig(routes=[route])
        assert config.match(make_op(operation="OBSERVE")) is route

    def test_wildcard_group_address_matches(self) -> None:
        route = make_route(group_address="*")
        config = KnxMappingConfig(routes=[route])
        assert config.match(make_op(group_address="31/7/255")) is route

    def test_group_address_matched_verbatim_not_expanded(self) -> None:
        """An exact group-address route must not match a different address —
        no topology or range interpretation."""
        route = make_route(group_address="1/2/3")
        config = KnxMappingConfig(routes=[route])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(group_address="1/2/4"))

    def test_two_level_and_three_level_not_conflated(self) -> None:
        """'1/2' and '1/2/0' are different verbatim identifiers."""
        route = make_route(group_address="1/2")
        config = KnxMappingConfig(routes=[route])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(group_address="1/2/0"))

    def test_first_match_wins(self) -> None:
        specific = make_route(group_address="1/2/3", name="specific")
        broad = make_route(group_address="*", name="broad")
        config = KnxMappingConfig(routes=[specific, broad])
        assert config.match(make_op()) is specific

    def test_no_match_raises_unknown_route(self) -> None:
        config = KnxMappingConfig(routes=[make_route(operation="GROUP_VALUE_WRITE")])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(operation="GROUP_VALUE_READ"))

    def test_empty_config_never_matches(self) -> None:
        config = KnxMappingConfig()
        with pytest.raises(UnknownRouteError):
            config.match(make_op())


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    @pytest.mark.parametrize(
        ("operation", "expected"),
        [
            ("GROUP_VALUE_READ", "read"),
            ("GROUP_VALUE_WRITE", "write"),
            ("GROUP_VALUE_RESPONSE", "read"),
            ("OBSERVE", "subscribe"),
        ],
    )
    def test_default_action_map(self, operation: str, expected: str) -> None:
        route = make_route(operation="*", action="")
        config = KnxMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(operation=operation)) == expected

    def test_explicit_action_overrides_default(self) -> None:
        route = make_route(operation="GROUP_VALUE_WRITE", action="control")
        config = KnxMappingConfig(routes=[route])
        op = make_op(operation="GROUP_VALUE_WRITE")
        assert config.resolve_action(route, op) == "control"


# ---------------------------------------------------------------------------
# Resource ID resolution
# ---------------------------------------------------------------------------


class TestResourceIdResolution:
    def test_group_address_template(self) -> None:
        route = make_route()
        config = KnxMappingConfig(routes=[route])
        assert config.resolve_resource_id(route, make_op()) == "knx:group:1/2/3"

    def test_communication_object_template(self) -> None:
        route = make_route(
            resource_id_template="knx:group:{group_address}/object:{communication_object}"
        )
        config = KnxMappingConfig(routes=[route])
        op = make_op(communication_object=4)
        assert config.resolve_resource_id(route, op) == "knx:group:1/2/3/object:4"

    def test_device_template(self) -> None:
        route = make_route(
            resource_id_template="knx:device:{device_address}/object:{communication_object}"
        )
        config = KnxMappingConfig(routes=[route])
        op = make_op(device_address="1.1.7", communication_object=2)
        assert config.resolve_resource_id(route, op) == "knx:device:1.1.7/object:2"

    def test_absent_optional_field_fails_closed(self) -> None:
        route = make_route(
            resource_id_template="knx:group:{group_address}/object:{communication_object}"
        )
        config = KnxMappingConfig(routes=[route])
        with pytest.raises(InvalidMappingError, match="not available"):
            config.resolve_resource_id(route, make_op())  # no communication_object

    def test_resource_id_is_deterministic(self) -> None:
        route = make_route()
        config = KnxMappingConfig(routes=[route])
        op = make_op()
        assert config.resolve_resource_id(route, op) == config.resolve_resource_id(route, op)


# ---------------------------------------------------------------------------
# from_dict parsing
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_valid_dict_parses(self) -> None:
        config = KnxMappingConfig.from_dict(
            {
                "routes": [
                    {
                        "name": "read-any",
                        "operation": "GROUP_VALUE_READ",
                        "group_address": "*",
                        "action": "read",
                        "resource_type": "knx_group_address",
                        "resource_id_template": "knx:group:{group_address}",
                    }
                ]
            }
        )
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-any"

    def test_group_address_defaults_to_wildcard(self) -> None:
        config = KnxMappingConfig.from_dict(
            {
                "routes": [
                    {
                        "operation": "GROUP_VALUE_READ",
                        "resource_type": "knx_group_address",
                        "resource_id_template": "knx:group:{group_address}",
                    }
                ]
            }
        )
        assert config.routes[0].group_address == "*"

    def test_empty_routes_parses(self) -> None:
        config = KnxMappingConfig.from_dict({"routes": []})
        assert config.routes == []

    def test_non_list_routes_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a list"):
            KnxMappingConfig.from_dict({"routes": "nope"})

    def test_non_dict_route_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a dict"):
            KnxMappingConfig.from_dict({"routes": ["nope"]})

    def test_invalid_route_in_dict_rejected(self) -> None:
        with pytest.raises(InvalidMappingError):
            KnxMappingConfig.from_dict(
                {
                    "routes": [
                        {
                            "operation": "NOT_A_KNX_OPERATION",
                            "resource_type": "knx_group_address",
                            "resource_id_template": "knx:group:{group_address}",
                        }
                    ]
                }
            )


# ---------------------------------------------------------------------------
# Address and DPT format helpers
# ---------------------------------------------------------------------------


class TestGroupAddressFormat:
    @pytest.mark.parametrize(
        "address",
        ["0/0/0", "1/2/3", "31/7/255", "1/200", "31/2047", "0", "2563", "65535"],
    )
    def test_valid_group_addresses(self, address: str) -> None:
        assert is_valid_group_address(address)

    @pytest.mark.parametrize(
        "address",
        [
            "32/0/0",  # main out of range (three-level)
            "1/8/3",  # middle out of range
            "1/2/256",  # sub out of range (three-level)
            "32/0",  # main out of range (two-level)
            "1/2048",  # sub out of range (two-level)
            "65536",  # free style out of range
            "1/2/3/4",  # too many levels
            "a/b/c",  # non-numeric
            "1.2.3",  # individual-address notation
            "-1/2/3",  # negative
            "",  # empty
            "1//3",  # empty level
        ],
    )
    def test_invalid_group_addresses(self, address: str) -> None:
        assert not is_valid_group_address(address)


class TestIndividualAddressFormat:
    @pytest.mark.parametrize("address", ["0.0.0", "1.1.5", "15.15.255"])
    def test_valid_individual_addresses(self, address: str) -> None:
        assert is_valid_individual_address(address)

    @pytest.mark.parametrize(
        "address",
        ["16.1.5", "1.16.5", "1.1.256", "1.1", "1.1.5.7", "1/1/5", "a.b.c", "", "1-1-5"],
    )
    def test_invalid_individual_addresses(self, address: str) -> None:
        assert not is_valid_individual_address(address)


class TestDatapointTypeFormat:
    @pytest.mark.parametrize("dpt", ["1.001", "9.001", "5.1", "232.600", "14.1200"])
    def test_valid_datapoint_types(self, dpt: str) -> None:
        assert is_valid_datapoint_type(dpt)

    @pytest.mark.parametrize("dpt", ["dpt-1", "1_001", "1.", ".001", "1", "1.001.1", "", "x.y"])
    def test_invalid_datapoint_types(self, dpt: str) -> None:
        assert not is_valid_datapoint_type(dpt)
