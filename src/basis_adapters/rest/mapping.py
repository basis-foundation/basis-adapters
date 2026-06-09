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

Query strings are stripped from the path before matching (everything
after and including `?`). Trailing slashes are NOT normalized — patterns
must match the path exactly as provided (after query string removal).

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown routes raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- resource_id_template capture references are validated against path captures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError

# Recognized normalized action verbs.
VALID_ACTIONS = frozenset({"read", "write", "control", "discover", "subscribe"})

# Recognized HTTP methods plus the wildcard sentinel.
# Non-standard methods are rejected to prevent silent misconfiguration.
VALID_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT", "*"}
)

# HTTP methods that default to a normalized action when no explicit action_map entry exists.
_DEFAULT_ACTION_MAP: dict[str, str] = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "discover",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "write",
    "TRACE": "read",
    "CONNECT": "read",
}

# Regex that extracts {param_name} tokens from a path pattern or resource_id_template.
_CAPTURE_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Regex that finds malformed brace tokens (unmatched or non-identifier content).
_MALFORMED_BRACE_RE = re.compile(r"\{[^}]*$|\{[^}\w][^}]*\}")


def _extract_captures(pattern: str) -> set[str]:
    """Return the set of capture parameter names in a `{param}` pattern string."""
    return set(_CAPTURE_TOKEN_RE.findall(pattern))


def _validate_path_pattern(pattern: str, route_label: str) -> None:
    """
    Validate that a path_pattern is structurally sound.

    Raises:
        InvalidMappingError: On any structural problem.
    """
    if not pattern or not pattern.strip():
        raise InvalidMappingError(f"Route '{route_label}': path_pattern must not be empty")
    if not pattern.startswith("/"):
        raise InvalidMappingError(
            f"Route '{route_label}': path_pattern must start with '/' (got '{pattern}')"
        )
    if _MALFORMED_BRACE_RE.search(pattern):
        raise InvalidMappingError(
            f"Route '{route_label}': path_pattern contains malformed capture token in '{pattern}'"
        )
    # Check for duplicate capture names in the same pattern.
    raw_captures = _CAPTURE_TOKEN_RE.findall(pattern)
    seen: set[str] = set()
    for cap in raw_captures:
        if cap in seen:
            raise InvalidMappingError(
                f"Route '{route_label}': path_pattern has duplicate capture name '{{{cap}}}'"
            )
        seen.add(cap)


def _validate_resource_id_template(
    template: str, path_captures: set[str], route_label: str
) -> None:
    """
    Validate that a resource_id_template is structurally sound and only references
    capture parameters that exist in the path_pattern.

    Raises:
        InvalidMappingError: If the template is empty, malformed, or references unknown captures.
    """
    if not template or not template.strip():
        raise InvalidMappingError(f"Route '{route_label}': resource_id_template must not be empty")
    if _MALFORMED_BRACE_RE.search(template):
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template contains malformed token in '{template}'"
        )
    template_refs = _extract_captures(template)
    unknown = template_refs - path_captures
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references capture(s) "
            f"{sorted(unknown)} that are not defined in path_pattern '{path_captures}'"
        )


@dataclass(frozen=True)
class RouteMapping:
    """
    Maps a (method, path_pattern) pair to normalized authorization semantics.

    Attributes:
        methods: HTTP methods this route applies to, e.g. ["GET", "HEAD"].
            Use ["*"] to match any method. Only recognized HTTP methods are accepted.
        path_pattern: Path pattern with optional `{param}` captures. Must start with '/'.
        resource_type: Normalized resource category, e.g. "point", "device".
        resource_id_template: Template for the resource ID. May reference
            captured path params with `{param}`. All referenced captures must
            exist in path_pattern. Static values (e.g. "*") are also valid.
        action_map: Per-method action overrides. If a method is not listed,
            the default action map is consulted. Values must be valid action verbs.
        name: Optional human-readable name for this route (for diagnostics).
            Used for duplicate-name detection at the config level.
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
        label = self.name or self.path_pattern or "<unnamed>"

        # Methods
        if not self.methods:
            raise InvalidMappingError(f"Route '{label}': methods must not be empty")
        for method in self.methods:
            upper = method.upper() if isinstance(method, str) else method
            if upper not in VALID_HTTP_METHODS:
                raise InvalidMappingError(
                    f"Route '{label}': unrecognized HTTP method '{method}'. "
                    f"Valid methods: {sorted(VALID_HTTP_METHODS)}"
                )

        # Path pattern
        _validate_path_pattern(self.path_pattern, label)

        # Resource type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # Resource ID template — captures must be a subset of path captures
        path_captures = _extract_captures(self.path_pattern)
        _validate_resource_id_template(self.resource_id_template, path_captures, label)

        # Action map values
        for method, action in self.action_map.items():
            if not action or not action.strip():
                raise InvalidMappingError(
                    f"Route '{label}': action for method '{method}' must not be empty"
                )
            if action not in VALID_ACTIONS:
                raise InvalidMappingError(
                    f"Route '{label}': invalid action '{action}' for method '{method}'. "
                    f"Valid actions: {sorted(VALID_ACTIONS)}"
                )


def _pattern_to_regex(path_pattern: str) -> re.Pattern[str]:
    """Convert a path pattern like /devices/{device_id} to a compiled regex."""
    # Escape everything except our {param} tokens, then replace them with named groups.
    escaped = re.escape(path_pattern)
    # re.escape turns { → \{ and } → \}, so we match on those.
    regex_str = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>[^/]+)", escaped)
    return re.compile(r"^" + regex_str + r"$")


def _strip_query_string(path: str) -> str:
    """Strip query string (everything from '?' onward) from a path."""
    idx = path.find("?")
    return path[:idx] if idx >= 0 else path


@dataclass
class RestMappingConfig:
    """
    A validated collection of RouteMapping entries for the REST adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[RouteMapping] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._check_duplicate_names()
        # Pre-compile patterns for fast matching.
        self._compiled: list[tuple[RouteMapping, re.Pattern[str]]] = [
            (route, _pattern_to_regex(route.path_pattern)) for route in self.routes
        ]

    def _check_duplicate_names(self) -> None:
        seen: set[str] = set()
        for route in self.routes:
            if route.name:
                if route.name in seen:
                    raise InvalidMappingError(
                        f"Duplicate route name '{route.name}' in mapping config. "
                        "Route names must be unique."
                    )
                seen.add(route.name)

    def match(self, method: str, path: str) -> tuple[RouteMapping, dict[str, str]]:
        """
        Find the first matching route for the given method and path.

        Query strings are stripped from the path before matching. Trailing
        slashes are not normalized — patterns must match the path exactly.

        Returns:
            A (RouteMapping, captures) tuple where captures is a dict of
            named path parameters extracted from the path.

        Raises:
            UnknownRouteError: If no route matches.
        """
        upper_method = method.upper()
        clean_path = _strip_query_string(path)
        for route, pattern in self._compiled:
            # Check method match.
            route_methods = [m.upper() for m in route.methods]
            if "*" not in route_methods and upper_method not in route_methods:
                continue
            m = pattern.match(clean_path)
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
                has an entry for the method.
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
                (This should not occur if RouteMapping validation passed, but is
                included as a defensive check.)
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
