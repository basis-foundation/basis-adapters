"""
Tests for the REST mapping configuration.

Covers:
- Route matching by method and path pattern
- Action resolution (explicit override vs. default map)
- Resource ID template rendering
- Failure modes: unknown route, invalid mapping config
"""

import pytest

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.rest.mapping import RestMappingConfig, RouteMapping

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def point_config() -> RestMappingConfig:
    """A minimal mapping config for device point operations."""
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
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
                name="discover-devices",
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestRouteMatching:
    def test_get_matches_read_point_route(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("GET", "/devices/ahu-1/points/supply-temp")
        assert route.name == "read-point"
        assert captures == {"device_id": "ahu-1", "point_id": "supply-temp"}

    def test_post_matches_write_point_route(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("POST", "/devices/ahu-1/points/supply-temp")
        assert route.name == "write-point"

    def test_put_matches_write_point_route(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("PUT", "/devices/ahu-1/points/supply-temp")
        assert route.name == "write-point"

    def test_patch_matches_write_point_route(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("PATCH", "/devices/ahu-1/points/supply-temp")
        assert route.name == "write-point"

    def test_post_command_matches_control_route(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("POST", "/devices/ahu-1/commands/reset")
        assert route.name == "control-device"
        assert captures == {"device_id": "ahu-1", "command": "reset"}

    def test_method_is_case_insensitive(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("get", "/devices/ahu-1/points/supply-temp")
        assert route.name == "read-point"

    def test_first_match_wins(self, point_config: RestMappingConfig) -> None:
        """GET on a point path matches read-point, not write-point."""
        route, _ = point_config.match("GET", "/devices/ahu-1/points/supply-temp")
        assert route.name == "read-point"

    def test_unknown_route_raises(self, point_config: RestMappingConfig) -> None:
        with pytest.raises(UnknownRouteError, match="No route matched"):
            point_config.match("GET", "/unknown/path")

    def test_method_mismatch_raises(self, point_config: RestMappingConfig) -> None:
        """DELETE is not configured for points — must fail closed."""
        with pytest.raises(UnknownRouteError):
            point_config.match("DELETE", "/devices/ahu-1/points/supply-temp")

    def test_partial_path_does_not_match(self, point_config: RestMappingConfig) -> None:
        with pytest.raises(UnknownRouteError):
            point_config.match("GET", "/devices/ahu-1/points")

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
        for method in ["GET", "POST", "PUT", "DELETE", "OPTIONS"]:
            route, _ = config.match(method, "/health")
            assert route.resource_type == "service"


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


class TestActionResolution:
    def test_explicit_action_map_overrides_default(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("POST", "/devices/ahu-1/commands/reset")
        action = point_config.resolve_action(route, "POST")
        assert action == "control"

    def test_default_get_maps_to_read(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("GET", "/devices/ahu-1/points/supply-temp")
        action = point_config.resolve_action(route, "GET")
        assert action == "read"

    def test_default_post_maps_to_write_when_no_override(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["POST"],
                    path_pattern="/items",
                    resource_type="item",
                    resource_id_template="collection",
                )
            ]
        )
        route, _ = config.match("POST", "/items")
        action = config.resolve_action(route, "POST")
        assert action == "write"

    def test_explicit_write_action_on_post(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("POST", "/devices/ahu-1/points/supply-temp")
        action = point_config.resolve_action(route, "POST")
        assert action == "write"

    def test_explicit_write_action_on_put(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("PUT", "/devices/ahu-1/points/supply-temp")
        action = point_config.resolve_action(route, "PUT")
        assert action == "write"

    def test_explicit_write_action_on_patch(self, point_config: RestMappingConfig) -> None:
        route, _ = point_config.match("PATCH", "/devices/ahu-1/points/supply-temp")
        action = point_config.resolve_action(route, "PATCH")
        assert action == "write"

    def test_options_defaults_to_browse(self) -> None:
        # OPTIONS's default (implicit) action is "browse" per the canonical
        # action vocabulary — matching OPC UA Browse / Niagara BROWSE
        # defaults. Explicit `action_map={"OPTIONS": "discover"}` remains a
        # fully supported compatibility alias (see
        # test_explicit_discover_action_still_honored).
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["OPTIONS"],
                    path_pattern="/devices",
                    resource_type="device",
                    resource_id_template="*",
                )
            ]
        )
        route, _ = config.match("OPTIONS", "/devices")
        action = config.resolve_action(route, "OPTIONS")
        assert action == "browse"

    def test_explicit_discover_action_still_honored(self) -> None:
        # "discover" is a compatibility alias: explicit action_map entries
        # that set it continue to work verbatim even though the implicit
        # OPTIONS default changed.
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["OPTIONS"],
                    path_pattern="/devices",
                    resource_type="device",
                    resource_id_template="*",
                    action_map={"OPTIONS": "discover"},
                )
            ]
        )
        route, _ = config.match("OPTIONS", "/devices")
        action = config.resolve_action(route, "OPTIONS")
        assert action == "discover"

    def test_explicit_browse_action_map_entry_is_valid(self) -> None:
        # "browse" is a normalized action verb in its own right (not just an
        # implicit default): an explicit action_map entry naming it must be
        # accepted by validation and honored verbatim, e.g. for a route that
        # wants "browse" on a method other than OPTIONS.
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices/tree",
                    resource_type="device",
                    resource_id_template="*",
                    action_map={"GET": "browse"},
                )
            ]
        )
        route, _ = config.match("GET", "/devices/tree")
        action = config.resolve_action(route, "GET")
        assert action == "browse"


# ---------------------------------------------------------------------------
# Resource ID template rendering
# ---------------------------------------------------------------------------


class TestResourceIdTemplate:
    def test_renders_single_capture(self) -> None:
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

    def test_renders_compound_capture(self, point_config: RestMappingConfig) -> None:
        route, captures = point_config.match("GET", "/devices/ahu-1/points/supply-temp")
        resource_id = point_config.resolve_resource_id(route, captures)
        assert resource_id == "ahu-1:supply-temp"

    def test_static_resource_id(self) -> None:
        config = RestMappingConfig(
            routes=[
                RouteMapping(
                    methods=["GET"],
                    path_pattern="/devices",
                    resource_type="device",
                    resource_id_template="*",
                )
            ]
        )
        route, captures = config.match("GET", "/devices")
        resource_id = config.resolve_resource_id(route, captures)
        assert resource_id == "*"


# ---------------------------------------------------------------------------
# Mapping validation
# ---------------------------------------------------------------------------


class TestMappingValidation:
    def test_empty_methods_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="methods must not be empty"):
            RouteMapping(
                methods=[],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
            )

    def test_empty_resource_type_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_type must not be empty"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices",
                resource_type="",
                resource_id_template="*",
            )

    def test_empty_resource_id_template_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="resource_id_template must not be empty"):
            RouteMapping(
                methods=["GET"],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="",
            )

    def test_invalid_action_in_action_map_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="invalid action 'fly'"):
            RouteMapping(
                methods=["POST"],
                path_pattern="/devices",
                resource_type="device",
                resource_id_template="*",
                action_map={"POST": "fly"},
            )

    def test_from_dict_valid(self) -> None:
        data = {
            "routes": [
                {
                    "methods": ["GET"],
                    "path_pattern": "/devices/{device_id}",
                    "resource_type": "device",
                    "resource_id_template": "{device_id}",
                }
            ]
        }
        config = RestMappingConfig.from_dict(data)
        assert len(config.routes) == 1

    def test_from_dict_invalid_route_raises(self) -> None:
        data = {
            "routes": [
                {
                    "methods": [],  # invalid
                    "path_pattern": "/devices",
                    "resource_type": "device",
                    "resource_id_template": "*",
                }
            ]
        }
        with pytest.raises(InvalidMappingError):
            RestMappingConfig.from_dict(data)

    def test_from_dict_routes_not_list_raises(self) -> None:
        with pytest.raises(InvalidMappingError, match="must be a list"):
            RestMappingConfig.from_dict({"routes": "not-a-list"})
