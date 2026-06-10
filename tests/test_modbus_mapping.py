"""
Tests for Modbus mapping configuration — ModbusRouteMapping and ModbusMappingConfig.

Covers:
- ModbusRouteMapping validation (eager, at construction time)
- ModbusMappingConfig duplicate-name detection
- ModbusMappingConfig.match() — exact, wildcard, first-match-wins, no-match
- ModbusMappingConfig.resolve_action() — explicit, default, missing
- ModbusMappingConfig.resolve_resource_id() — template substitution
- ModbusMappingConfig.from_dict() — JSON deserialization
"""

from __future__ import annotations

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.modbus.mapping import (
    VALID_MODBUS_FUNCTIONS,
    VALID_MODBUS_TEMPLATE_FIELDS,
    ModbusMappingConfig,
    ModbusOperation,
    ModbusRouteMapping,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_route(**kwargs: object) -> ModbusRouteMapping:
    defaults: dict[str, object] = {
        "function": "ReadHoldingRegisters",
        "register_type": "holding_register",
        "action": "read",
        "resource_type": "modbus_register",
        "resource_id_template": "unit:{unit_id}:{register_type}:{address}",
        "name": "",
    }
    defaults.update(kwargs)
    return ModbusRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> ModbusOperation:
    defaults: dict[str, object] = {
        "function": "ReadHoldingRegisters",
        "unit_id": 1,
        "address": 40001,
        "quantity": 1,
    }
    defaults.update(kwargs)
    return ModbusOperation(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ModbusRouteMapping validation
# ---------------------------------------------------------------------------


class TestModbusRouteMappingValidation:
    def test_valid_route_constructs(self) -> None:
        route = make_route()
        assert route.function == "ReadHoldingRegisters"
        assert route.register_type == "holding_register"
        assert route.action == "read"
        assert route.resource_type == "modbus_register"

    def test_wildcard_function_accepted(self) -> None:
        route = make_route(function="*")
        assert route.function == "*"

    def test_wildcard_register_type_accepted(self) -> None:
        route = make_route(register_type="*")
        assert route.register_type == "*"

    def test_all_valid_functions_accepted(self) -> None:
        for fn in VALID_MODBUS_FUNCTIONS:
            route = make_route(function=fn)
            assert route.function == fn

    def test_invalid_function_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized Modbus function"):
            make_route(function="ReadUnknownRegisters")

    def test_empty_function_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized Modbus function"):
            make_route(function="")

    def test_empty_register_type_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="register_type must not be empty"):
            make_route(register_type="")

    def test_invalid_action_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action"):
            make_route(action="approve")

    def test_empty_resource_type_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type must not be empty"):
            make_route(resource_type="")

    def test_empty_template_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template must not be empty"):
            make_route(resource_id_template="")

    def test_unknown_template_field_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="unknown field"):
            make_route(resource_id_template="unit:{unit_id}:{device_mac}:{address}")

    def test_malformed_template_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed token"):
            make_route(resource_id_template="unit:{unit_id}:{")

    def test_empty_action_accepted_for_default_lookup(self) -> None:
        # Empty action means: use the default function→action map at normalize time.
        route = make_route(action="")
        assert route.action == ""

    def test_all_valid_template_fields_accepted(self) -> None:
        template = ":".join(f"{{{f}}}" for f in sorted(VALID_MODBUS_TEMPLATE_FIELDS))
        route = make_route(resource_id_template=template)
        assert route.resource_id_template == template


class TestModbusMappingConfigValidation:
    def test_duplicate_names_rejected(self) -> None:
        r1 = make_route(name="read-regs")
        r2 = make_route(
            function="ReadInputRegisters", register_type="input_register", name="read-regs"
        )
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            ModbusMappingConfig(routes=[r1, r2])

    def test_no_name_duplicates_allowed_when_names_empty(self) -> None:
        r1 = make_route(name="")
        r2 = make_route(name="")
        config = ModbusMappingConfig(routes=[r1, r2])
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestModbusMappingMatch:
    def test_exact_function_match(self) -> None:
        route = make_route(function="ReadHoldingRegisters", register_type="*")
        config = ModbusMappingConfig(routes=[route])
        matched = config.match(make_op(function="ReadHoldingRegisters"))
        assert matched is route

    def test_exact_register_type_match(self) -> None:
        route = make_route(function="*", register_type="holding_register")
        config = ModbusMappingConfig(routes=[route])
        matched = config.match(make_op(function="ReadHoldingRegisters"))
        assert matched is route

    def test_wildcard_function_matches_any(self) -> None:
        route = make_route(function="*", register_type="*")
        config = ModbusMappingConfig(routes=[route])
        for fn in VALID_MODBUS_FUNCTIONS:
            op = make_op(function=fn)
            assert config.match(op) is route

    def test_first_match_wins(self) -> None:
        specific = make_route(
            function="ReadHoldingRegisters", register_type="holding_register", name="specific"
        )
        catchall = make_route(function="*", register_type="*", name="catchall")
        config = ModbusMappingConfig(routes=[specific, catchall])
        matched = config.match(make_op(function="ReadHoldingRegisters"))
        assert matched is specific

    def test_catchall_used_when_specific_not_matched(self) -> None:
        specific = make_route(
            function="WriteSingleRegister", register_type="holding_register", name="specific"
        )
        catchall = make_route(function="*", register_type="*", name="catchall")
        config = ModbusMappingConfig(routes=[specific, catchall])
        matched = config.match(make_op(function="ReadHoldingRegisters"))
        assert matched is catchall

    def test_no_match_raises_unknown_route_error(self) -> None:
        route = make_route(function="WriteSingleRegister", register_type="holding_register")
        config = ModbusMappingConfig(routes=[route])
        with pytest.raises(UnknownRouteError):
            config.match(make_op(function="ReadHoldingRegisters"))

    def test_register_type_inferred_from_function_for_matching(self) -> None:
        route = make_route(function="*", register_type="coil")
        config = ModbusMappingConfig(routes=[route])
        # WriteSingleCoil → effective register type = "coil"
        op = make_op(function="WriteSingleCoil", address=100)
        matched = config.match(op)
        assert matched is route

    def test_explicit_register_type_on_operation_used_for_matching(self) -> None:
        route = make_route(function="*", register_type="custom_type")
        config = ModbusMappingConfig(routes=[route])
        op = make_op(function="ReadHoldingRegisters", register_type="custom_type")
        matched = config.match(op)
        assert matched is route


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestModbusActionResolution:
    def test_explicit_action_used(self) -> None:
        route = make_route(action="control")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op()) == "control"

    def test_default_read_holding_to_read(self) -> None:
        route = make_route(action="")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="ReadHoldingRegisters")) == "read"

    def test_default_write_single_register_to_write(self) -> None:
        route = make_route(action="", function="WriteSingleRegister", register_type="*")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="WriteSingleRegister")) == "write"

    def test_default_write_multiple_registers_to_write(self) -> None:
        route = make_route(action="", function="WriteMultipleRegisters", register_type="*")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="WriteMultipleRegisters")) == "write"

    def test_default_read_coils_to_read(self) -> None:
        route = make_route(action="", function="ReadCoils", register_type="coil")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="ReadCoils")) == "read"

    def test_default_write_single_coil_to_write(self) -> None:
        route = make_route(action="", function="WriteSingleCoil", register_type="coil")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="WriteSingleCoil")) == "write"

    def test_default_read_input_registers_to_read(self) -> None:
        route = make_route(action="", function="ReadInputRegisters", register_type="input_register")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="ReadInputRegisters")) == "read"

    def test_default_read_discrete_inputs_to_read(self) -> None:
        route = make_route(action="", function="ReadDiscreteInputs", register_type="discrete_input")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="ReadDiscreteInputs")) == "read"

    def test_default_write_multiple_coils_to_write(self) -> None:
        route = make_route(action="", function="WriteMultipleCoils", register_type="coil")
        config = ModbusMappingConfig(routes=[route])
        assert config.resolve_action(route, make_op(function="WriteMultipleCoils")) == "write"


# ---------------------------------------------------------------------------
# Resource ID template resolution
# ---------------------------------------------------------------------------


class TestModbusResourceIdResolution:
    def test_unit_register_type_address_template(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:{register_type}:{address}")
        config = ModbusMappingConfig(routes=[route])
        op = make_op(unit_id=1, address=40001)
        result = config.resolve_resource_id(route, op)
        assert result == "unit:1:holding_register:40001"

    def test_quantity_included_in_template(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:addr:{address}:qty:{quantity}")
        config = ModbusMappingConfig(routes=[route])
        op = make_op(unit_id=3, address=100, quantity=5)
        result = config.resolve_resource_id(route, op)
        assert result == "unit:3:addr:100:qty:5"

    def test_function_in_template(self) -> None:
        route = make_route(resource_id_template="{function}:{unit_id}:{address}")
        config = ModbusMappingConfig(routes=[route])
        op = make_op(unit_id=2, address=200)
        result = config.resolve_resource_id(route, op)
        assert result == "ReadHoldingRegisters:2:200"

    def test_static_resource_id_template(self) -> None:
        route = make_route(resource_id_template="modbus-registers")
        config = ModbusMappingConfig(routes=[route])
        result = config.resolve_resource_id(route, make_op())
        assert result == "modbus-registers"

    def test_explicit_register_type_on_op_used_in_template(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:{register_type}:{address}")
        config = ModbusMappingConfig(routes=[route])
        op = make_op(unit_id=1, address=100, register_type="custom_type")
        result = config.resolve_resource_id(route, op)
        assert result == "unit:1:custom_type:100"


# ---------------------------------------------------------------------------
# from_dict deserialization
# ---------------------------------------------------------------------------


class TestModbusMappingFromDict:
    def test_valid_dict_parses(self) -> None:
        data = {
            "routes": [
                {
                    "name": "read-holding",
                    "function": "ReadHoldingRegisters",
                    "register_type": "holding_register",
                    "action": "read",
                    "resource_type": "modbus_register",
                    "resource_id_template": "unit:{unit_id}:{register_type}:{address}",
                }
            ]
        }
        config = ModbusMappingConfig.from_dict(data)
        assert len(config.routes) == 1
        assert config.routes[0].name == "read-holding"

    def test_routes_not_list_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="'routes' must be a list"):
            ModbusMappingConfig.from_dict({"routes": "not-a-list"})

    def test_route_not_dict_raises(self) -> None:
        with pytest.raises(InvalidMappingError):
            ModbusMappingConfig.from_dict({"routes": ["not-a-dict"]})

    def test_invalid_route_raises(self) -> None:
        data = {
            "routes": [
                {
                    "function": "BadFunction",
                    "register_type": "holding_register",
                    "action": "read",
                    "resource_type": "modbus_register",
                    "resource_id_template": "unit:{unit_id}:{address}",
                }
            ]
        }
        with pytest.raises(InvalidMappingError, match="unrecognized Modbus function"):
            ModbusMappingConfig.from_dict(data)

    def test_empty_routes_list_accepted(self) -> None:
        config = ModbusMappingConfig.from_dict({"routes": []})
        assert config.routes == []
