"""
Tests for ModbusAdapter normalization behavior.

Covers all supported Modbus functions, wildcard matching, exact matching,
template substitution, protocol evidence preservation, and failure result shapes.
"""

from __future__ import annotations

from basis_adapters.modbus.adapter import ModbusAdapter
from basis_adapters.modbus.mapping import ModbusMappingConfig, ModbusOperation, ModbusRouteMapping
from basis_adapters.models import AdapterContext, AdapterResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> ModbusOperation:
    defaults: dict[str, object] = {
        "function": "ReadHoldingRegisters",
        "unit_id": 1,
        "address": 40001,
        "quantity": 1,
    }
    defaults.update(kwargs)
    return ModbusOperation(**defaults)  # type: ignore[arg-type]


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


def make_adapter(*routes: ModbusRouteMapping, adapter_id: str = "test") -> ModbusAdapter:
    config = ModbusMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return ModbusAdapter(mapping=config, context=ctx)


# ---------------------------------------------------------------------------
# Function normalization — read functions
# ---------------------------------------------------------------------------


class TestReadFunctions:
    def test_read_holding_registers_normalizes_to_read(self) -> None:
        adapter = make_adapter(make_route(function="ReadHoldingRegisters"))
        result = adapter.normalize(make_op(function="ReadHoldingRegisters"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_input_registers_normalizes_to_read(self) -> None:
        route = make_route(function="ReadInputRegisters", register_type="input_register")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="ReadInputRegisters"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_coils_normalizes_to_read(self) -> None:
        route = make_route(function="ReadCoils", register_type="coil")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="ReadCoils", address=100))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_read_discrete_inputs_normalizes_to_read(self) -> None:
        route = make_route(function="ReadDiscreteInputs", register_type="discrete_input")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="ReadDiscreteInputs", address=200))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"


# ---------------------------------------------------------------------------
# Function normalization — write functions
# ---------------------------------------------------------------------------


class TestWriteFunctions:
    def test_write_single_register_normalizes_to_write(self) -> None:
        route = make_route(
            function="WriteSingleRegister", register_type="holding_register", action="write"
        )
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="WriteSingleRegister", value_present=True))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_write_multiple_registers_normalizes_to_write(self) -> None:
        route = make_route(
            function="WriteMultipleRegisters", register_type="holding_register", action="write"
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(function="WriteMultipleRegisters", quantity=5, value_present=True)
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_write_single_coil_normalizes_to_write(self) -> None:
        route = make_route(function="WriteSingleCoil", register_type="coil", action="write")
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(function="WriteSingleCoil", address=50, value_present=True)
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_write_multiple_coils_normalizes_to_write(self) -> None:
        route = make_route(function="WriteMultipleCoils", register_type="coil", action="write")
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(function="WriteMultipleCoils", address=50, quantity=8, value_present=True)
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"


# ---------------------------------------------------------------------------
# Resource ID template
# ---------------------------------------------------------------------------


class TestResourceIdTemplate:
    def test_unit_register_type_address_in_resource_id(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:{register_type}:{address}")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(unit_id=1, address=40001))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "unit:1:holding_register:40001"

    def test_quantity_in_resource_id(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:addr:{address}:qty:{quantity}")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(unit_id=3, address=100, quantity=4))
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "unit:3:addr:100:qty:4"

    def test_different_units_produce_different_resource_ids(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:{register_type}:{address}")
        adapter = make_adapter(route)
        r1 = adapter.normalize(make_op(unit_id=1, address=40001))
        r2 = adapter.normalize(make_op(unit_id=2, address=40001))
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.resource_id != r2.request.resource_id

    def test_different_addresses_produce_different_resource_ids(self) -> None:
        route = make_route(resource_id_template="unit:{unit_id}:{register_type}:{address}")
        adapter = make_adapter(route)
        r1 = adapter.normalize(make_op(unit_id=1, address=40001))
        r2 = adapter.normalize(make_op(unit_id=1, address=40002))
        assert r1.success and r2.success
        assert r1.request is not None and r2.request is not None
        assert r1.request.resource_id != r2.request.resource_id


# ---------------------------------------------------------------------------
# Protocol field
# ---------------------------------------------------------------------------


class TestProtocolField:
    def test_protocol_is_modbus(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol == "modbus"


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

    def test_evidence_protocol_is_modbus(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.protocol == "modbus"

    def test_evidence_method_is_function_name(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(function="ReadHoldingRegisters"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "ReadHoldingRegisters"

    def test_evidence_path_encodes_unit_and_address(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(unit_id=5, address=40010))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "unit:5:addr:40010"

    def test_evidence_metadata_contains_unit_id(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(unit_id=7))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["unit_id"] == 7

    def test_evidence_metadata_contains_address(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(address=40099))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["address"] == 40099

    def test_evidence_metadata_contains_quantity(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(quantity=10))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["quantity"] == 10

    def test_evidence_metadata_contains_value_present(self) -> None:
        route = make_route(
            function="WriteSingleRegister", register_type="holding_register", action="write"
        )
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="WriteSingleRegister", value_present=True))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value_present"] is True

    def test_source_address_preserved_in_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(source_address="192.0.2.1"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["source_address"] == "192.0.2.1"

    def test_transaction_id_preserved_in_evidence(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(transaction_id=42))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["transaction_id"] == 42


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


# ---------------------------------------------------------------------------
# Failure cases — fail closed
# ---------------------------------------------------------------------------


class TestFailureCases:
    def test_unknown_function_returns_failure(self) -> None:
        route = make_route(function="WriteSingleRegister", register_type="holding_register")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(function="ReadHoldingRegisters"))
        assert not result.success
        assert result.request is None
        assert result.error is not None

    def test_no_routes_returns_failure(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op())
        assert not result.success
        assert result.request is None

    def test_normalize_never_raises(self) -> None:
        adapter = make_adapter()
        # Should return failure result, not raise.
        result = adapter.normalize(make_op(function="ReadHoldingRegisters"))
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
        config = ModbusMappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="modbus-primary")
        adapter = ModbusAdapter(mapping=config, context=ctx)
        assert adapter.adapter_id == "modbus-primary"
