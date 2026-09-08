"""
Tests for the REST adapter normalization logic.

Covers all required scenarios:
- GET normalizes to read
- POST/PUT/PATCH normalize to write or control depending on mapping
- Unknown route fails closed (returns failure result, does not raise)
- Invalid mapping fails at config time (raises InvalidMappingError)
- Normalized request includes protocol evidence
- Adapter does not call gateway or basis-core (structural/design test)
"""

import inspect

import pytest

from basis_adapters.errors import InvalidMappingError
from basis_adapters.models import AdapterContext, ProtocolOperation
from basis_adapters.rest.adapter import RestAdapter
from basis_adapters.rest.mapping import RestMappingConfig, RouteMapping

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def standard_config() -> RestMappingConfig:
    return RestMappingConfig(
        routes=[
            RouteMapping(
                methods=["GET", "HEAD"],
                path_pattern="/devices/{device_id}/points/{point_id}",
                resource_type="point",
                resource_id_template="{device_id}:{point_id}",
                name="read-point",
            ),
            RouteMapping(
                methods=["POST", "PUT", "PATCH"],
                path_pattern="/devices/{device_id}/points/{point_id}",
                resource_type="point",
                resource_id_template="{device_id}:{point_id}",
                action_map={"POST": "write", "PUT": "write", "PATCH": "write"},
                name="write-point",
            ),
            RouteMapping(
                methods=["POST"],
                path_pattern="/devices/{device_id}/commands/{command}",
                resource_type="device",
                resource_id_template="{device_id}",
                action_map={"POST": "control"},
                name="control-device",
            ),
        ]
    )


@pytest.fixture()
def ctx() -> AdapterContext:
    return AdapterContext(adapter_id="rest-test")


@pytest.fixture()
def adapter(standard_config: RestMappingConfig, ctx: AdapterContext) -> RestAdapter:
    return RestAdapter(mapping=standard_config, context=ctx)


# ---------------------------------------------------------------------------
# GET → read
# ---------------------------------------------------------------------------


class TestGetNormalizesToRead:
    def test_get_produces_read_action(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
        )
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "read"

    def test_get_normalizes_resource_type_to_point(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.resource_type == "point"

    def test_get_normalizes_resource_id(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.resource_id == "ahu-1:supply-temp"

    def test_head_also_normalizes_to_read(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="HEAD", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "read"


# ---------------------------------------------------------------------------
# POST / PUT / PATCH → write or control
# ---------------------------------------------------------------------------


class TestMutatingMethodsNormalization:
    @pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
    def test_method_normalizes_to_write_on_point(self, adapter: RestAdapter, method: str) -> None:
        op = ProtocolOperation(
            protocol="rest",
            method=method,
            path="/devices/ahu-1/points/supply-temp",
        )
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "write"

    def test_post_to_command_normalizes_to_control(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest",
            method="POST",
            path="/devices/ahu-1/commands/reset",
        )
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "control"
        assert result.request.resource_type == "device"
        assert result.request.resource_id == "ahu-1"


# ---------------------------------------------------------------------------
# OPTIONS → browse (default), with "discover" retained as a compatible alias
# ---------------------------------------------------------------------------


class TestOptionsNormalization:
    def test_options_default_action_is_browse(self) -> None:
        # OPTIONS's implicit (no explicit action_map entry) default is
        # "browse", conforming to the canonical action vocabulary used by
        # OPC UA Browse / Niagara BROWSE. Explicit
        # `action_map={"OPTIONS": "discover"}` remains a supported
        # compatibility alias — see test_options_explicit_discover_honored.
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["OPTIONS"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="options-device",
                )
            ]
        )
        adapter = RestAdapter(mapping=config, context=AdapterContext(adapter_id="rest-test"))
        op = ProtocolOperation(protocol="rest", method="OPTIONS", path="/devices/ahu-1")
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "browse"

    def test_options_explicit_discover_honored(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["OPTIONS"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    action_map={"OPTIONS": "discover"},
                    name="options-device-explicit",
                )
            ]
        )
        adapter = RestAdapter(mapping=config, context=AdapterContext(adapter_id="rest-test"))
        op = ProtocolOperation(protocol="rest", method="OPTIONS", path="/devices/ahu-1")
        result = adapter.normalize(op)
        assert result.success is True
        assert result.request is not None
        assert result.request.action == "discover"


# ---------------------------------------------------------------------------
# Fail closed on unknown routes
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_unknown_path_returns_failure(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(protocol="rest", method="GET", path="/unknown/endpoint")
        result = adapter.normalize(op)
        assert result.success is False
        assert result.request is None
        assert result.error is not None
        assert "No route matched" in result.error

    def test_unmapped_method_returns_failure(self, adapter: RestAdapter) -> None:
        """DELETE is not configured — adapter must fail closed."""
        op = ProtocolOperation(
            protocol="rest", method="DELETE", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.success is False

    def test_failure_result_has_no_request(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(protocol="rest", method="GET", path="/nonexistent")
        result = adapter.normalize(op)
        assert result.request is None

    def test_adapter_does_not_raise_on_unknown_route(self, adapter: RestAdapter) -> None:
        """normalize() must never raise — errors are captured into AdapterResult."""
        op = ProtocolOperation(protocol="rest", method="GET", path="/nonexistent")
        result = adapter.normalize(op)  # must not raise
        assert not result.success


# ---------------------------------------------------------------------------
# Invalid mapping fails at config time
# ---------------------------------------------------------------------------


class TestInvalidMappingFailsAtConfigTime:
    def test_invalid_action_raises_at_route_creation(self) -> None:
        with pytest.raises(InvalidMappingError):
            RouteMapping(
                methods=["POST"],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
                action_map={"POST": "invalid-action"},
            )

    def test_empty_resource_type_raises_at_route_creation(self) -> None:
        with pytest.raises(InvalidMappingError):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices",
                resource_type="  ",
                resource_id_template="*",
            )

    def test_invalid_from_dict_raises(self) -> None:
        data = {
            "routes": [
                {
                    "methods": [],
                    "path_pattern": "/x",
                    "resource_type": "x",
                    "resource_id_template": "x",
                }
            ]
        }
        with pytest.raises(InvalidMappingError):
            RestMappingConfig.from_dict(data)


# ---------------------------------------------------------------------------
# Protocol evidence is always attached
# ---------------------------------------------------------------------------


class TestProtocolEvidence:
    def test_protocol_evidence_is_attached(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence is op

    def test_protocol_field_is_rest(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol == "rest"

    def test_original_method_and_path_preserved_in_evidence(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(protocol="rest", method="POST", path="/devices/ahu-1/commands/reset")
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence.method == "POST"
        assert result.request.protocol_evidence.path == "/devices/ahu-1/commands/reset"

    def test_subject_hint_forwarded_from_metadata(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
            metadata={"subject_hint": "user@example.com"},
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.subject_hint == "user@example.com"

    def test_no_subject_hint_when_metadata_empty(self, adapter: RestAdapter) -> None:
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.subject_hint is None


# ---------------------------------------------------------------------------
# Adapter does not call gateway or basis-core (structural test)
# ---------------------------------------------------------------------------


class TestAdapterIsolation:
    def test_adapter_module_does_not_import_gateway(self) -> None:
        """The REST adapter must not depend on basis-gateway."""
        from basis_adapters.rest import adapter as adapter_module

        source = inspect.getsource(adapter_module)
        assert "basis_gateway" not in source
        assert "import requests" not in source

    def test_adapter_module_does_not_import_basis_core(self) -> None:
        """The REST adapter must not depend on basis-core."""
        from basis_adapters.rest import adapter as adapter_module

        source = inspect.getsource(adapter_module)
        assert "basis_core" not in source

    def test_mapping_module_does_not_import_gateway(self) -> None:
        from basis_adapters.rest import mapping as mapping_module

        source = inspect.getsource(mapping_module)
        assert "basis_gateway" not in source

    def test_adapter_id_exposed(self, adapter: RestAdapter) -> None:
        assert adapter.adapter_id == "rest-test"
