"""
REST adapter contract tests — Phase 2.

Covers edge cases and explicit contract behaviors:
- Trailing slash behavior (not normalized — must match exactly)
- Query string stripping before path matching
- Path capture substitution corner cases
- Unsupported HTTP method failure
- Unknown route failure
- Duplicate route name rejection
- Invalid mapping failure modes (Phase 2 additions)
- Protocol evidence retention
- Adapter failure result shape
- Adapter isolation (no basis_core, no gateway imports)

These tests document the contract and are intended to be stable. If a test
here breaks, it means the contract changed — not just an implementation detail.
"""

from __future__ import annotations

import inspect

import pytest

from basis_adapters.errors import AdapterError, InvalidMappingError, UnknownRouteError
from basis_adapters.models import AdapterContext, AdapterResult, ProtocolOperation
from basis_adapters.rest.adapter import RestAdapter
from basis_adapters.rest.mapping import (
    VALID_ACTIONS,
    VALID_HTTP_METHODS,
    RestMappingConfig,
    RouteMapping,
    _strip_query_string,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(*routes: RouteMapping) -> RestAdapter:
    config = RestMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id="contract-test")
    return RestAdapter(mapping=config, context=ctx)


def _point_route(
    methods: list[str] | None = None,
    name: str = "read-point",
    action_map: dict[str, str] | None = None,
) -> RouteMapping:
    return RouteMapping(
        methods=methods or ["GET"],
        path_pattern="/devices/{device_id}/points/{point_id}",
        resource_type="point",
        resource_id_template="{device_id}:{point_id}",
        name=name,
        action_map=action_map or {},
    )


# ---------------------------------------------------------------------------
# Query string stripping
# ---------------------------------------------------------------------------


class TestQueryStringHandling:
    """
    Contract: query strings are stripped before path matching.
    The original ProtocolOperation (with the full path) is always preserved
    in protocol_evidence.
    """

    def test_path_with_query_string_matches_route(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp?format=json",
        )
        result = adapter.normalize(op)
        assert result.success is True

    def test_query_string_does_not_affect_resource_id(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp?unit=celsius&precision=2",
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.resource_id == "ahu-1:supply-temp"

    def test_original_path_preserved_in_evidence(self) -> None:
        """Query string stripping must not alter protocol_evidence."""
        adapter = _make_adapter(_point_route())
        original_path = "/devices/ahu-1/points/supply-temp?format=json"
        op = ProtocolOperation(protocol="rest", method="GET", path=original_path)
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence.path == original_path

    def test_path_only_no_query_string(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.success is True

    def test_strip_query_string_helper(self) -> None:
        assert _strip_query_string("/devices/ahu-1?x=1") == "/devices/ahu-1"
        assert _strip_query_string("/devices/ahu-1") == "/devices/ahu-1"
        assert _strip_query_string("/a?") == "/a"
        assert _strip_query_string("/?a=1&b=2") == "/"

    def test_unknown_route_with_query_string_fails_closed(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/unknown?key=val")
        result = adapter.normalize(op)
        assert result.success is False


# ---------------------------------------------------------------------------
# Trailing slash behavior
# ---------------------------------------------------------------------------


class TestTrailingSlashBehavior:
    """
    Contract: trailing slashes are NOT normalized. A pattern must match the
    path exactly (after query string removal). /devices/ahu-1 and
    /devices/ahu-1/ are different paths.
    """

    def test_exact_path_matches(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="read-device",
                )
            ]
        )
        route, captures = config.match("GET", "/devices/ahu-1")
        assert captures["device_id"] == "ahu-1"

    def test_trailing_slash_does_not_match_pattern_without_slash(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="read-device",
                )
            ]
        )
        with pytest.raises(UnknownRouteError):
            config.match("GET", "/devices/ahu-1/")

    def test_pattern_with_trailing_slash_matches_path_with_slash(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}/",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="read-device-slash",
                )
            ]
        )
        route, captures = config.match("GET", "/devices/ahu-1/")
        assert captures["device_id"] == "ahu-1"

    def test_pattern_with_trailing_slash_does_not_match_path_without(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}/",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="read-device-slash",
                )
            ]
        )
        with pytest.raises(UnknownRouteError):
            config.match("GET", "/devices/ahu-1")


# ---------------------------------------------------------------------------
# Capture substitution
# ---------------------------------------------------------------------------


class TestCaptureSubstitution:
    def test_single_capture(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                )
            ]
        )
        route, captures = config.match("GET", "/devices/ahu-1")
        resource_id = config.resolve_resource_id(route, captures)
        assert resource_id == "ahu-1"

    def test_multi_segment_capture(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/floors/{floor}/zones/{zone}/points/{point}",
                    resource_type="point",
                    resource_id_template="{floor}:{zone}:{point}",
                )
            ]
        )
        route, captures = config.match("GET", "/floors/2/zones/north/points/temp")
        resource_id = config.resolve_resource_id(route, captures)
        assert resource_id == "2:north:temp"

    def test_static_resource_id_ignores_captures(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}/points",
                    resource_type="point",
                    resource_id_template="*",
                )
            ]
        )
        route, captures = config.match("GET", "/devices/ahu-1/points")
        resource_id = config.resolve_resource_id(route, captures)
        assert resource_id == "*"

    def test_capture_with_special_chars_in_value(self) -> None:
        """Capture values may contain hyphens and underscores."""
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                )
            ]
        )
        route, captures = config.match("GET", "/devices/ahu-unit_01")
        assert captures["device_id"] == "ahu-unit_01"

    def test_capture_does_not_cross_segment_boundary(self) -> None:
        """{device_id} must not capture across '/' separators."""
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                )
            ]
        )
        with pytest.raises(UnknownRouteError):
            config.match("GET", "/devices/ahu-1/extra")


# ---------------------------------------------------------------------------
# Unsupported / unknown methods
# ---------------------------------------------------------------------------


class TestMethodHandling:
    def test_unsupported_method_in_route_raises_at_config_time(self) -> None:
        with pytest.raises(InvalidMappingError, match="unrecognized HTTP method"):
            RouteMapping(
                methods=["FROBNICATE"],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
            )

    def test_valid_methods_accepted(self) -> None:
        for method in ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "*"]:
            route = RouteMapping(
                methods=[method],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
            )
            assert method in route.methods

    def test_all_valid_methods_constant_is_consistent(self) -> None:
        """VALID_HTTP_METHODS and VALID_ACTIONS are non-empty frozensets."""
        assert len(VALID_HTTP_METHODS) > 0
        assert len(VALID_ACTIONS) > 0

    def test_method_not_in_any_route_returns_failure(self) -> None:
        adapter = _make_adapter(_point_route(methods=["GET"]))
        op = ProtocolOperation(
            protocol="rest", method="DELETE", path="/devices/ahu-1/points/supply-temp"
        )
        result = adapter.normalize(op)
        assert result.success is False
        assert result.error is not None

    def test_wildcard_method_matches_any(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["*"],
                    path_pattern="/health",
                    resource_type="service",
                    resource_id_template="health",
                )
            ]
        )
        for method in ["GET", "POST", "DELETE", "OPTIONS", "PATCH"]:
            route, _ = config.match(method, "/health")
            assert route.resource_type == "service"


# ---------------------------------------------------------------------------
# Unknown route (fail closed)
# ---------------------------------------------------------------------------


class TestUnknownRouteFail:
    def test_unknown_path_returns_failure_result(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/totally/unknown")
        result = adapter.normalize(op)
        assert result.success is False
        assert result.request is None
        assert result.error is not None

    def test_error_message_mentions_method_and_path(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/totally/unknown")
        result = adapter.normalize(op)
        assert result.error is not None
        assert "GET" in result.error
        assert "/totally/unknown" in result.error

    def test_normalize_never_raises(self) -> None:
        adapter = _make_adapter(_point_route())
        for path in ["/", "/a", "/a/b/c/d/e", "", "///"]:
            result = adapter.normalize(ProtocolOperation(protocol="rest", method="GET", path=path))
            assert isinstance(result, AdapterResult)


# ---------------------------------------------------------------------------
# Duplicate route name rejection
# ---------------------------------------------------------------------------


class TestDuplicateRouteName:
    def test_duplicate_name_raises_at_config_time(self) -> None:
        with pytest.raises(InvalidMappingError, match="Duplicate route name"):
            RestMappingConfig(
                routes=[
                    RouteMapping(
                        methods=["GET"],
                        path_pattern="/devices/{device_id}",
                        resource_type="device",
                        resource_id_template="{device_id}",
                        name="read-device",
                    ),
                    RouteMapping(
                        methods=["HEAD"],
                        path_pattern="/devices/{device_id}",
                        resource_type="device",
                        resource_id_template="{device_id}",
                        name="read-device",  # duplicate
                    ),
                ]
            )

    def test_anonymous_routes_do_not_trigger_duplicate_check(self) -> None:
        """Routes with empty names are exempt from duplicate detection."""
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/a",
                    resource_type="x",
                    resource_id_template="*",
                    name="",
                ),
                RouteMapping(
                    methods=["POST"],
                    path_pattern="/b",
                    resource_type="x",
                    resource_id_template="*",
                    name="",
                ),
            ]
        )
        assert len(config.routes) == 2

    def test_unique_names_accepted(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/{device_id}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="read-device",
                ),
                RouteMapping(
                    methods=["POST"],
                    path_pattern="/devices/{device_id}/commands/{cmd}",
                    resource_type="device",
                    resource_id_template="{device_id}",
                    name="control-device",
                    action_map={"POST": "control"},
                ),
            ]
        )
        assert len(config.routes) == 2


# ---------------------------------------------------------------------------
# Phase 2 mapping validation additions
# ---------------------------------------------------------------------------


class TestPhase2Validation:
    def test_path_pattern_must_start_with_slash(self) -> None:
        with pytest.raises(InvalidMappingError, match="must start with '/'"):
            RouteMapping(
                methods=["GET"],
                path_pattern="devices/{device_id}",
                resource_type="device",
                resource_id_template="{device_id}",
            )

    def test_path_pattern_must_not_be_empty(self) -> None:
        with pytest.raises(InvalidMappingError, match="must not be empty"):
            RouteMapping(
                methods=["GET"],
                path_pattern="",
                resource_type="device",
                resource_id_template="*",
            )

    def test_malformed_capture_in_path_pattern_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed capture"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices/{device_id",  # missing closing brace
                resource_type="device",
                resource_id_template="fallback",
            )

    def test_duplicate_capture_name_in_path_pattern_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="duplicate capture name"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices/{device_id}/sub/{device_id}",
                resource_type="device",
                resource_id_template="{device_id}",
            )

    def test_resource_id_template_referencing_unknown_capture_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="references capture"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices/{device_id}",
                resource_type="device",
                resource_id_template="{building_id}:{device_id}",
            )

    def test_empty_action_in_action_map_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="must not be empty"):
            RouteMapping(
                methods=["POST"],
                path_pattern="/devices/{device_id}",
                resource_type="device",
                resource_id_template="{device_id}",
                action_map={"POST": ""},
            )

    def test_static_resource_id_template_is_valid(self) -> None:
        """Templates with no {param} references are valid."""
        route = RouteMapping(
            methods=["GET"],
            path_pattern="/devices",
            resource_type="device",
            resource_id_template="*",
        )
        assert route.resource_id_template == "*"

    def test_malformed_capture_in_resource_id_template_rejected(self) -> None:
        with pytest.raises(InvalidMappingError, match="malformed"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices/{device_id}",
                resource_type="device",
                resource_id_template="{device_id",  # missing closing brace
            )

    def test_valid_complex_route_accepted(self) -> None:
        """Comprehensive smoke test for a valid complex route."""
        route = RouteMapping(
            methods=["GET", "HEAD", "*"],
            path_pattern="/buildings/{building}/floors/{floor}/points/{point_id}",
            resource_type="point",
            resource_id_template="{building}:{floor}:{point_id}",
            name="read-nested-point",
            action_map={"HEAD": "discover"},
        )
        assert route.name == "read-nested-point"


# ---------------------------------------------------------------------------
# Protocol evidence retention
# ---------------------------------------------------------------------------


class TestProtocolEvidenceContract:
    def test_evidence_is_exact_original_operation(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
            metadata={"subject_hint": "user@example.com", "request_id": "abc123"},
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence is op

    def test_evidence_metadata_is_preserved(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
            metadata={"x_forwarded_for": "10.0.0.1"},
        )
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["x_forwarded_for"] == "10.0.0.1"

    def test_evidence_protocol_field_matches_operation(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/devices/a/points/b")
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol == "rest"
        assert result.request.protocol_evidence.protocol == "rest"

    def test_query_string_preserved_in_evidence(self) -> None:
        """Query strings are stripped for matching but preserved in evidence."""
        adapter = _make_adapter(_point_route())
        path_with_qs = "/devices/ahu-1/points/supply-temp?unit=celsius"
        op = ProtocolOperation(protocol="rest", method="GET", path=path_with_qs)
        result = adapter.normalize(op)
        assert result.request is not None
        assert result.request.protocol_evidence.path == path_with_qs


# ---------------------------------------------------------------------------
# Failure result shape
# ---------------------------------------------------------------------------


class TestFailureResultShape:
    def test_failure_has_no_request(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/unknown")
        result = adapter.normalize(op)
        assert result.success is False
        assert result.request is None

    def test_failure_has_error_string(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/unknown")
        result = adapter.normalize(op)
        assert isinstance(result.error, str)
        assert len(result.error) > 0

    def test_failure_is_adapter_result_instance(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/unknown")
        result = adapter.normalize(op)
        assert isinstance(result, AdapterResult)

    def test_success_has_no_error(self) -> None:
        adapter = _make_adapter(_point_route())
        op = ProtocolOperation(protocol="rest", method="GET", path="/devices/x/points/y")
        result = adapter.normalize(op)
        assert result.success is True
        assert result.error is None

    def test_adapter_error_hierarchy(self) -> None:
        """UnknownRouteError and InvalidMappingError are both AdapterErrors."""
        assert issubclass(UnknownRouteError, AdapterError)
        assert issubclass(InvalidMappingError, AdapterError)


# ---------------------------------------------------------------------------
# Adapter isolation (structural)
# ---------------------------------------------------------------------------


class TestAdapterIsolation:
    def test_adapter_module_has_no_basis_core_import(self) -> None:
        import basis_adapters.rest.adapter as m

        source = inspect.getsource(m)
        assert "basis_core" not in source

    def test_adapter_module_has_no_gateway_import(self) -> None:
        import basis_adapters.rest.adapter as m

        source = inspect.getsource(m)
        assert "basis_gateway" not in source

    def test_adapter_module_has_no_network_calls(self) -> None:
        import basis_adapters.rest.adapter as m

        source = inspect.getsource(m)
        assert "import requests" not in source
        assert "import httpx" not in source
        assert "import urllib" not in source
        assert "socket.connect" not in source

    def test_mapping_module_has_no_basis_core_import(self) -> None:
        import basis_adapters.rest.mapping as m

        source = inspect.getsource(m)
        assert "basis_core" not in source

    def test_mapping_module_has_no_gateway_import(self) -> None:
        import basis_adapters.rest.mapping as m

        source = inspect.getsource(m)
        assert "basis_gateway" not in source

    def test_models_module_has_no_basis_core_import(self) -> None:
        import basis_adapters.models as m

        source = inspect.getsource(m)
        assert "basis_core" not in source
