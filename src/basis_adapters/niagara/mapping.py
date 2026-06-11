"""
Niagara adapter mapping configuration.

A Niagara mapping config is a list of NiagaraRouteMapping entries. Each entry
describes how a specific Niagara platform operation (and optional station)
should be normalized into a BASIS authorization request.

Niagara operations are matched by two fields:
  - operation  e.g. "READ_POINT", "OVERRIDE_POINT", "*"
  - station    e.g. "station-east", "*"

The wildcard sentinel "*" matches any value for that field. Station names are
matched verbatim — no host resolution, no supervisor topology inference.
Routes are evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {operation}  - Niagara operation name
  {station}    - Station name (always present)
  {ord}        - Niagara ORD, verbatim (if present)
  {component}  - Component name (if present)
  {slot}       - Slot/property name (if present)
  {point}      - Point name (if present)
  {schedule}   - Schedule name (if present)
  {alarm}      - Alarm identifier (if present)
  {history}    - History identifier (if present)

Fields marked "if present" are optional on the operation. A template that
references an optional field which is absent at normalization time fails
closed at render time.

Values, facets, point types, baja types, nav paths, categories, Niagara users,
and Niagara roles are deliberately NOT template fields: they are protocol
evidence, never resource identity. Niagara users and roles in particular are
platform context, not BASIS identity — identity resolution belongs to
basis-gateway.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against
  VALID_NIAGARA_TEMPLATE_FIELDS.
- Niagara reuses the existing canonical action vocabulary including the
  "execute" and "browse" verbs introduced for OPC UA. No new action verbs
  were added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# Niagara operations supported by this adapter (platform-intent names).
# These model representative Niagara platform operation categories — they do
# not attempt to model the full Niagara platform, Fox/Foxs services, the Baja
# runtime, or station workflows.
VALID_NIAGARA_OPERATIONS = frozenset(
    {
        # Read
        "READ_COMPONENT",
        "READ_POINT",
        "READ_SLOT",
        "READ_HISTORY",
        "READ_ALARM",
        "READ_SCHEDULE",
        # Write
        "WRITE_POINT",
        "WRITE_SLOT",
        "UPDATE_SCHEDULE",
        # Invoke / command (and alarm acknowledgement, modeled as an action)
        "ACK_ALARM",
        "INVOKE_ACTION",
        "COMMAND_POINT",
        "OVERRIDE_POINT",
        "RELEASE_OVERRIDE",
        # Browse / navigation
        "BROWSE",
        "RESOLVE_ORD",
        "LIST_CHILDREN",
        # Subscribe / observe
        "SUBSCRIBE_POINT",
        "SUBSCRIBE_ALARM",
        "SUBSCRIBE_HISTORY",
    }
)

# Normalized action verbs accepted for Niagara routes. Niagara reuses the
# shared action vocabulary extended with "execute" (action/command invocation)
# and "browse" (station navigation) — both introduced for OPC UA. No new
# verbs were added for Niagara.
VALID_NIAGARA_ACTIONS = VALID_ACTIONS | frozenset({"execute", "browse"})

# Default action mapping from Niagara operation to normalized action verb.
# ACK_ALARM normalizes to "execute": acknowledgement is treated as an
# action/event on the alarm, not a data write. OVERRIDE_POINT and
# RELEASE_OVERRIDE normalize to "execute": they are operational commands,
# not data writes — the adapter implements no priority-array or override
# state behavior. RESOLVE_ORD and LIST_CHILDREN normalize to "browse":
# they are navigation intents, the same semantics as OPC UA Browse.
_DEFAULT_OPERATION_ACTION_MAP: dict[str, str] = {
    "READ_COMPONENT": "read",
    "READ_POINT": "read",
    "READ_SLOT": "read",
    "READ_HISTORY": "read",
    "READ_ALARM": "read",
    "READ_SCHEDULE": "read",
    "WRITE_POINT": "write",
    "WRITE_SLOT": "write",
    "UPDATE_SCHEDULE": "write",
    "ACK_ALARM": "execute",
    "INVOKE_ACTION": "execute",
    "COMMAND_POINT": "execute",
    "OVERRIDE_POINT": "execute",
    "RELEASE_OVERRIDE": "execute",
    "BROWSE": "browse",
    "RESOLVE_ORD": "browse",
    "LIST_CHILDREN": "browse",
    "SUBSCRIBE_POINT": "subscribe",
    "SUBSCRIBE_ALARM": "subscribe",
    "SUBSCRIBE_HISTORY": "subscribe",
}

# Fields that may be referenced in resource_id_template. Values, facets,
# point types, baja types, nav paths, categories, Niagara users, and Niagara
# roles are deliberately excluded — they are evidence, never resource
# identity, and Niagara users/roles are never BASIS identity.
VALID_NIAGARA_TEMPLATE_FIELDS = frozenset(
    {
        "operation",
        "station",
        "ord",
        "component",
        "slot",
        "point",
        "schedule",
        "alarm",
        "history",
    }
)

# Target field required per operation. Every operation also requires a
# station (resource IDs are station-rooted). Operations absent from this map
# have no single mandatory target beyond the station.
_OPERATION_TARGET_FIELD: dict[str, str] = {
    "READ_COMPONENT": "component",
    "READ_POINT": "point",
    "READ_SLOT": "slot",
    "READ_HISTORY": "history",
    "READ_ALARM": "alarm",
    "READ_SCHEDULE": "schedule",
    "WRITE_POINT": "point",
    "WRITE_SLOT": "slot",
    "UPDATE_SCHEDULE": "schedule",
    "ACK_ALARM": "alarm",
    "COMMAND_POINT": "point",
    "OVERRIDE_POINT": "point",
    "RELEASE_OVERRIDE": "point",
    "SUBSCRIBE_POINT": "point",
    "SUBSCRIBE_ALARM": "alarm",
    "SUBSCRIBE_HISTORY": "history",
    "RESOLVE_ORD": "ord",
}

# Operations that require at least one of several target fields.
_OPERATION_ANY_TARGET_FIELDS: dict[str, tuple[str, ...]] = {
    "INVOKE_ACTION": ("component", "point", "ord"),
}

# Regex that extracts {param_name} tokens from a template string.
_CAPTURE_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Regex that finds malformed brace tokens (unmatched or non-identifier content).
_MALFORMED_BRACE_RE = re.compile(r"\{[^}]*$|\{[^}\w][^}]*\}")


def required_target_field(operation: str) -> str | None:
    """
    Return the single target field required for a Niagara operation, or None
    if the operation has no single mandatory target (BROWSE, LIST_CHILDREN)
    or requires one-of-several targets (INVOKE_ACTION).
    """
    return _OPERATION_TARGET_FIELD.get(operation)


def required_any_of_target_fields(operation: str) -> tuple[str, ...] | None:
    """
    Return the one-of-several target fields required for a Niagara operation
    (at least one must be present), or None if the operation has no such
    requirement.
    """
    return _OPERATION_ANY_TARGET_FIELDS.get(operation)


def _extract_template_fields(template: str) -> set[str]:
    """Return the set of field names referenced in a {param} template string."""
    return set(_CAPTURE_TOKEN_RE.findall(template))


def _validate_resource_id_template(template: str, route_label: str) -> None:
    """
    Validate that a resource_id_template is structurally sound and only
    references fields from VALID_NIAGARA_TEMPLATE_FIELDS.

    Raises:
        InvalidMappingError: If the template is empty, malformed, or
            references unknown fields (including the evidence-only fields
            value, facet, point_type, baja_type, nav_path, category,
            niagara_user, and niagara_role).
    """
    if not template or not template.strip():
        raise InvalidMappingError(f"Route '{route_label}': resource_id_template must not be empty")
    if _MALFORMED_BRACE_RE.search(template):
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template contains malformed token in '{template}'"
        )
    refs = _extract_template_fields(template)
    unknown = refs - VALID_NIAGARA_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_NIAGARA_TEMPLATE_FIELDS)}. "
            "Values, facets, point types, baja types, nav paths, categories, "
            "Niagara users, and Niagara roles are evidence only and may never "
            "appear in resource IDs."
        )


@dataclass(frozen=True)
class NiagaraOperation:
    """
    A raw Niagara platform operation, as received before normalization.

    This models the intent of a Niagara platform operation without
    representing wire traffic or a live station connection. No Fox/Foxs
    client. No Baja runtime. No Haystack client. No REST connector. No
    station, supervisor, or JACE connectivity. No packet parsing. This is
    deliberately a small model — it does not attempt to model the full
    Niagara platform.

    Attributes:
        operation:    Niagara operation name, e.g. "READ_POINT",
                      "OVERRIDE_POINT", "BROWSE". See
                      VALID_NIAGARA_OPERATIONS.
        station:      Station name. Required — resource IDs are
                      station-rooted.
        host:         Optional host name or address of the platform host.
                      Evidence only.
        ord:          Optional Niagara ORD string. Preserved exactly as
                      supplied — never parsed, resolved, or followed. May be
                      used in deterministic resource IDs.
        component:    Optional component name. Supports deterministic
                      resource IDs.
        slot:         Optional slot/property name. Supports deterministic
                      resource IDs.
        point:        Optional point name. Supports deterministic resource
                      IDs.
        point_type:   Optional point type descriptor (e.g.
                      "NumericWritable"). Evidence only.
        value:        Optional operation value (written value, command
                      argument, override value). Evidence only — never
                      rendered into resource IDs.
        facet:        Optional facet descriptor (e.g. "units=°F"). Evidence
                      only.
        schedule:     Optional schedule name. Supports deterministic
                      resource IDs.
        alarm:        Optional alarm identifier. Supports deterministic
                      resource IDs.
        history:      Optional history identifier. Supports deterministic
                      resource IDs.
        category:     Optional Niagara category name. Evidence only — the
                      adapter does not interpret Niagara category-based
                      permissions.
        baja_type:    Optional Baja type spec (e.g.
                      "control:NumericWritable"). Evidence only.
        nav_path:     Optional nav path. Evidence only.
        niagara_user: Optional Niagara user name reported by the platform
                      layer. Evidence only — never BASIS identity, never
                      copied into subject_hint.
        niagara_role: Optional Niagara role name reported by the platform
                      layer. Evidence only — never BASIS identity, never
                      copied into subject_hint.
        metadata:     Additional platform-specific fields (e.g. override
                      duration/level, acknowledgement context).
    """

    operation: str
    station: str | None = None
    host: str | None = None
    ord: str | None = None
    component: str | None = None
    slot: str | None = None
    point: str | None = None
    point_type: str | None = None
    value: Any = None
    facet: str | None = None
    schedule: str | None = None
    alarm: str | None = None
    history: str | None = None
    category: str | None = None
    baja_type: str | None = None
    nav_path: str | None = None
    niagara_user: str | None = None
    niagara_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the Niagara operation name and the path is a
        deterministic station-rooted address: "station:{station}" extended,
        in fixed order, with "/ord:{ord}", "/component:{component}",
        "/slot:{slot}", "/point:{point}", "/history:{history}",
        "/alarm:{alarm}", and "/schedule:{schedule}" for whichever targets
        are present. All Niagara fields are preserved in metadata for audit
        purposes.
        """
        path = f"station:{self.station}"
        for label, target in (
            ("ord", self.ord),
            ("component", self.component),
            ("slot", self.slot),
            ("point", self.point),
            ("history", self.history),
            ("alarm", self.alarm),
            ("schedule", self.schedule),
        ):
            if target is not None:
                path += f"/{label}:{target}"
        meta: dict[str, Any] = {
            "operation": self.operation,
            "station": self.station,
            "host": self.host,
            "ord": self.ord,
            "component": self.component,
            "slot": self.slot,
            "point": self.point,
            "point_type": self.point_type,
            "value": self.value,
            "facet": self.facet,
            "schedule": self.schedule,
            "alarm": self.alarm,
            "history": self.history,
            "category": self.category,
            "baja_type": self.baja_type,
            "nav_path": self.nav_path,
            "niagara_user": self.niagara_user,
            "niagara_role": self.niagara_role,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="niagara",
            method=self.operation,
            path=path,
            metadata=meta,
        )


@dataclass(frozen=True)
class NiagaraRouteMapping:
    """
    Maps a Niagara (operation, station) pair to normalized authorization
    semantics.

    Attributes:
        operation:            Niagara operation to match (see
            VALID_NIAGARA_OPERATIONS), or "*" for any.
        station:              Station name to match verbatim, or "*" for
            any. Exact string comparison only — no host resolution, no
            supervisor topology inference.
        action:               Normalized action verb (e.g. "read",
            "execute"). If empty string, the default operation action map is
            consulted at normalization time (READ_*→read, WRITE_*/
            UPDATE_SCHEDULE→write, ACK_ALARM/INVOKE_ACTION/COMMAND_POINT/
            OVERRIDE_POINT/RELEASE_OVERRIDE→execute, BROWSE/RESOLVE_ORD/
            LIST_CHILDREN→browse, SUBSCRIBE_*→subscribe).
        resource_type:        Normalized resource category, e.g.
            "niagara_point".
        resource_id_template: Template for the resource ID. May reference
            fields in VALID_NIAGARA_TEMPLATE_FIELDS. Values, facets, point
            types, baja types, nav paths, categories, Niagara users, and
            Niagara roles are never template fields.
        name:                 Optional human-readable name (for diagnostics
            and duplicate-name detection).
    """

    operation: str
    station: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.operation}:{self.station}"

        # operation must be a valid Niagara operation or wildcard
        if self.operation != "*" and self.operation not in VALID_NIAGARA_OPERATIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized Niagara operation '{self.operation}'. "
                f"Valid operations: {sorted(VALID_NIAGARA_OPERATIONS)} or '*'"
            )

        # station must be a non-empty string ("*" is the wildcard)
        if not self.station or not self.station.strip():
            raise InvalidMappingError(f"Route '{label}': station must be a non-empty string or '*'")

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_NIAGARA_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_NIAGARA_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)


@dataclass
class NiagaraMappingConfig:
    """
    A validated collection of NiagaraRouteMapping entries for the Niagara
    adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[NiagaraRouteMapping] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._check_duplicate_names()

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

    def match(self, operation: NiagaraOperation) -> NiagaraRouteMapping:
        """
        Find the first matching route for the given Niagara operation.

        Matching is performed on operation and station. A route field value
        of "*" matches any operation value for that field. Station names are
        compared verbatim — no host resolution, no supervisor topology
        inference.

        Returns:
            The first matching NiagaraRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            operation_match = route.operation == "*" or route.operation == operation.operation
            station_match = route.station == "*" or route.station == operation.station
            if operation_match and station_match:
                return route
        raise UnknownRouteError(
            f"No route matched: operation={operation.operation!r} station={operation.station!r}"
        )

    def resolve_action(self, route: NiagaraRouteMapping, operation: NiagaraOperation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the
        default operation action map is consulted.

        Raises:
            InvalidMappingError: If neither the route nor the default map has
                an entry for the operation.
        """
        if route.action:
            return route.action
        if operation.operation in _DEFAULT_OPERATION_ACTION_MAP:
            return _DEFAULT_OPERATION_ACTION_MAP[operation.operation]
        raise InvalidMappingError(
            f"No default action mapping for Niagara operation '{operation.operation}' "
            f"and route '{route.name or route.operation}' has no explicit action."
        )

    def resolve_resource_id(self, route: NiagaraRouteMapping, operation: NiagaraOperation) -> str:
        """
        Render the resource_id_template using fields from the Niagara
        operation.

        Available substitution fields:
          {operation}  - Niagara operation name
          {station}    - Station name
          {ord}        - ORD, verbatim (if present)
          {component}  - Component name (if present)
          {slot}       - Slot/property name (if present)
          {point}      - Point name (if present)
          {schedule}   - Schedule name (if present)
          {alarm}      - Alarm identifier (if present)
          {history}    - History identifier (if present)

        Optional fields are only available when present on the operation. A
        template that references an absent optional field fails closed.

        Values, facets, point types, baja types, nav paths, categories,
        Niagara users, and Niagara roles are never available as template
        fields — they remain protocol evidence only.

        Raises:
            InvalidMappingError: If a template placeholder has no
                corresponding field available on the operation.
        """
        captures: dict[str, str] = {"operation": operation.operation}
        for label in (
            "station",
            "ord",
            "component",
            "slot",
            "point",
            "schedule",
            "alarm",
            "history",
        ):
            target = getattr(operation, label)
            if target is not None:
                captures[label] = target
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"field {exc} which is not available on the operation "
                f"(route '{route.name or route.operation}')"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NiagaraMappingConfig:
        """
        Parse a Niagara mapping config from a plain dictionary (e.g. loaded
        from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[NiagaraRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    NiagaraRouteMapping(
                        operation=raw.get("operation", ""),
                        station=raw.get("station", "*"),
                        action=raw.get("action", ""),
                        resource_type=raw.get("resource_type", ""),
                        resource_id_template=raw.get("resource_id_template", ""),
                        name=raw.get("name", ""),
                    )
                )
            except InvalidMappingError:
                raise
            except Exception as exc:
                raise InvalidMappingError(f"Route at index {i} is invalid: {exc}") from exc

        return cls(routes=routes)
