"""
REST adapter mapping configuration.

A mapping config is a list of RouteMapping entries. Each entry describes
how a specific HTTP method + path pattern should be normalized into a
BASIS authorization request.

Path patterns support a single named capture group syntax: `{param}`.
For example, `/devices/{device_id}/points/{point_id}` matches
`/devices/ahu-1/points/supply-temp` and captures:
    device_id = "ahu-1"
    point_id  = "supply-temp"

Captured values may be referenced in `resource_id` templates using the
same `{param}` syntax.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time.
- Adapters do not evaluate policy; they only map operations to semantics.
- Unknown routes raise UnknownRouteError — adapters fail closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError

# Recognized normalized action verbs.
VALID_ACTIONS = frozenset({"read", "write", "control", "discover", "subscribe"})

# HTTP methods that default to "read" when no explicit action_map entry exists.
_DEFAULT_ACTION_MAP: dict[str, str] = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "discover",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "write",
}


@dataclass(frozen=True)
class RouteMapping:
    """
    Maps a (method, path_pattern) pair to normalized authorization semantics.

    Attributes:
        methods: HTTP methods this route applies to, e.g. ["GET", "HEAD"].
            Use ["*"] to match any method.
        path_pattern: Path pattern with optional `{param}` captures.
        resource_type: Normalized resource category, e.g. "point", "device".
        resource_id_template: Template for the resource ID. May reference
            captured path params with `{param}`. E.g. `"{device_id}:{point_id}"`.
        action_map: Per-method action overrides. If a method is not listed,
            the default action map is consulted.
        name: Optional human-readable name for this route (for diagnostics).
    """

    methods: list[str]
    path_pattern: str
    resource_type: str
    resource_id_template: str
    action_map: dict[str, str] = field(default_factory=dict)
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.methods:
            raise InvalidMappingError(
                f"Route '{self.name or self.path_pattern}': methods must not be empty"
            )
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(
                f"Route '{self.name or self.path_pattern}': resource_type must not be empty"
            )
        if not self.resource_id_template or not self.resource_id_template.strip():
            raise InvalidMappingError(
                f"Route '{self.name or self.path_pattern}': resource_id_template must not be empty"
            )
        for method, action in self.action_map.items():
            if action not in VALID_ACTIONS:
                raise InvalidMappingError(
                    f"Route '{self.name or self.path_pattern}': "
                    f"invalid action '{action}' for method '{method}'. "
                    f"Valid actions: {sorted(VALID_ACTIONS)}"
                )


def _pattern_to_regex(path_pattern: str) -> re.Pattern[str]:
    """Convert a path pattern like /devices/{device_id} to a compiled regex."""
    # Escape everything except our {param} tokens, then replace them with named groups.
    escaped = re.escape(path_pattern)
    # re.escape turns { → \{ and } → \}, so we match on those.
    regex_str = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", escaped)
    return re.compile(r"^" + regex_str + r"$")


@dataclass
class RestMappingConfig:
    """
    A validated collection of RouteMapping entries for the REST adapter.

    Routes are evaluated in order; the first match wins.
    """

    routes: list[RouteMapping] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Pre-compile patterns for fast matching.
        self._compiled: list[tuple[RouteMapping, re.Pattern[str]]] = [
            (route, _pattern_to_regex(route.path_pattern)) for route in self.routes
        ]

    def match(self, method: str, path: str) -> tuple[RouteMapping, dict[str, str]]:
        """
        Find the first matching route for the given method and path.

        Returns:
            A (RouteMapping, captures) tuple where captures is a dict of
            named path parameters extracted from the path.

        Raises:
            UnknownRouteError: If no route matches.
        """
        upper_method = method.upper()
        for route, pattern in self._compiled:
            # Check method match.
            route_methods = [m.upper() for m in route.methods]
            if "*" not in route_methods and upper_method not in route_methods:
                continue
            m = pattern.match(path)
            if m:
                return route, m.groupdict()
        raise UnknownRouteError(f"No route matched: {method.upper()} {path}")

    def resolve_action(self, route: RouteMapping, method: str) -> str:
        """
        Determine the normalized action for the given route and HTTP method.

        Consults the route's action_map first, then falls back to the
        global default action map.

        Raises:
            InvalidMappingError: If neither the route nor the default map
                has an entry for the method and no fallback exists.
        """
        upper = method.upper()
        if upper in route.action_map:
            return route.action_map[upper]
        if upper in _DEFAULT_ACTION_MAP:
            return _DEFAULT_ACTION_MAP[upper]
        raise InvalidMappingError(
            f"No action mapping for method '{upper}' on route '{route.name or route.path_pattern}'"
        )

    def resolve_resource_id(self, route: RouteMapping, captures: dict[str, str]) -> str:
        """
        Render the resource_id_template using the captured path parameters.

        Raises:
            InvalidMappingError: If a template placeholder has no corresponding capture.
        """
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"undefined capture {exc} for route '{route.name or route.path_pattern}'"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RestMappingConfig:
        """
        Parse a mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[RouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    RouteMapping(
                        methods=raw.get("methods", []),
                        path_pattern=raw.get("path_pattern", ""),
                        resource_type=raw.get("resource_type", ""),
                        resource_id_template=raw.get("resource_id_template", ""),
                        action_map=raw.get("action_map", {}),
                        name=raw.get("name", ""),
                    )
                )
            except InvalidMappingError:
                raise
            except Exception as exc:
                raise InvalidMappingError(f"Route at index {i} is invalid: {exc}") from exc

        return cls(routes=routes)
