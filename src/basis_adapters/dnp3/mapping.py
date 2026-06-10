"""
DNP3 adapter mapping configuration.

A DNP3 mapping config is a list of Dnp3RouteMapping entries. Each entry
describes how a specific DNP3 operation (and optional point type) should be
normalized into a BASIS authorization request.

DNP3 operations are matched by two fields:
  - operation   e.g. "READ", "SELECT", "OPERATE", "DIRECT_OPERATE", "*"
  - point_type  e.g. "binary_output", "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {operation}            - DNP3 operation name
  {outstation_id}        - Logical outstation identifier (if present)
  {master_id}            - Logical master identifier (if present)
  {source_address}       - DNP3 source (link-layer) address (if present)
  {destination_address}  - DNP3 destination (link-layer) address (if present)
  {object_group}         - DNP3 object group number (if present)
  {variation}            - DNP3 object variation number (if present)
  {point_index}          - Point index within the object group (if present)
  {point_type}           - Point type, e.g. "analog_input" (if present)
  {event_class}          - DNP3 event class 0-3 (if present)

Fields marked "if present" are optional on the operation. A template that
references an optional field which is absent at normalization time fails
closed at render time.

Command values are deliberately NOT a template field: values (CROB codes,
analog output commands) are protocol evidence, never resource identity.
Resource IDs must stay deterministic and free of sensitive command payloads.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_DNP3_TEMPLATE_FIELDS.
- Control routes (SELECT, OPERATE, DIRECT_OPERATE, CONTROL) must reference
  {point_index} in their resource_id_template so a control command is never
  normalized without identifying the controlled point.
- DNP3 reuses the existing canonical action vocabulary (READ→read, control
  operations→execute, ENABLE_UNSOLICITED→subscribe). No new action verbs
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

# DNP3 operations supported by this adapter (protocol-native function names).
VALID_DNP3_OPERATIONS = frozenset(
    {"READ", "SELECT", "OPERATE", "DIRECT_OPERATE", "CONTROL", "ENABLE_UNSOLICITED"}
)

# DNP3 operations that represent control commands targeting a specific point.
DNP3_CONTROL_OPERATIONS = frozenset({"SELECT", "OPERATE", "DIRECT_OPERATE", "CONTROL"})

# DNP3 point types recognized by this adapter.
VALID_DNP3_POINT_TYPES = frozenset(
    {
        "binary_input",
        "binary_output",
        "analog_input",
        "analog_output",
        "counter",
        "frozen_counter",
    }
)

# DNP3 control models. select_before_operate covers the SELECT/OPERATE
# two-step pattern; direct_operate covers single-step DIRECT_OPERATE commands.
VALID_DNP3_CONTROL_MODELS = frozenset({"select_before_operate", "direct_operate"})

# Normalized action verbs accepted for DNP3 routes. DNP3 reuses the shared
# action vocabulary plus "execute" (introduced additively in Phase 7 for
# OPC UA method invocation) for control commands. No new verbs were added.
VALID_DNP3_ACTIONS = VALID_ACTIONS | frozenset({"execute"})

# Default action mapping from DNP3 operation to normalized action verb.
# Control semantics prefer "execute" over "write": a CROB or analog output
# command is a command to equipment, not a simple data write.
_DEFAULT_OPERATION_ACTION_MAP: dict[str, str] = {
    "READ": "read",
    "SELECT": "execute",
    "OPERATE": "execute",
    "DIRECT_OPERATE": "execute",
    "CONTROL": "execute",
    "ENABLE_UNSOLICITED": "subscribe",
}

# Fields that may be referenced in resource_id_template.
VALID_DNP3_TEMPLATE_FIELDS = frozenset(
    {
        "operation",
        "outstation_id",
        "master_id",
        "source_address",
        "destination_address",
        "object_group",
        "variation",
        "point_index",
        "point_type",
        "event_class",
    }
)

# Regex that extracts {param_name} tokens from a template string.
_CAPTURE_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Regex that finds malformed brace tokens (unmatched or non-identifier content).
_MALFORMED_BRACE_RE = re.compile(r"\{[^}]*$|\{[^}\w][^}]*\}")


def _extract_template_fields(template: str) -> set[str]:
    """Return the set of field names referenced in a {param} template string."""
    return set(_CAPTURE_TOKEN_RE.findall(template))


def _validate_resource_id_template(template: str, route_label: str) -> None:
    """
    Validate that a resource_id_template is structurally sound and only
    references fields from VALID_DNP3_TEMPLATE_FIELDS.

    Raises:
        InvalidMappingError: If the template is empty, malformed, or references
            unknown fields.
    """
    if not template or not template.strip():
        raise InvalidMappingError(f"Route '{route_label}': resource_id_template must not be empty")
    if _MALFORMED_BRACE_RE.search(template):
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template contains malformed token in '{template}'"
        )
    refs = _extract_template_fields(template)
    unknown = refs - VALID_DNP3_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_DNP3_TEMPLATE_FIELDS)}"
        )


@dataclass(frozen=True)
class Dnp3Operation:
    """
    A raw DNP3 operation, as received before normalization.

    This models the intent of a DNP3 application-layer request without
    representing actual wire frames or a live master/outstation session.
    No DNP3 stack. No TCP/serial transport. No packet parsing.

    Attributes:
        operation:           DNP3 operation name: "READ", "SELECT", "OPERATE",
                             "DIRECT_OPERATE", "CONTROL", or
                             "ENABLE_UNSOLICITED" (protocol-native function
                             names, uppercase).
        source_address:      Optional DNP3 source (link-layer) address of the
                             requesting master. Evidence only.
        destination_address: Optional DNP3 destination (link-layer) address of
                             the target outstation. Provides target identity
                             when no outstation_id is supplied.
        outstation_id:       Optional logical outstation identifier. Either
                             outstation_id or destination_address is required —
                             a DNP3 operation without target identity fails
                             closed.
        master_id:           Optional logical master identifier. Evidence only —
                             never treated as verified identity.
        object_group:        Optional DNP3 object group number (0-255), e.g.
                             group 30 for analog inputs, group 12 for CROBs.
        variation:           Optional object variation number (0-255). Requires
                             object_group to be present.
        point_index:         Optional point index within the object group.
                             Required for control operations; optional for
                             class-level reads.
        point_type:          Optional point type: "binary_input",
                             "binary_output", "analog_input", "analog_output",
                             "counter", or "frozen_counter".
        function_code:       Optional DNP3 application-layer function code
                             (0-255). Preserved as evidence.
        qualifier:           Optional DNP3 qualifier code (0-255). Preserved
                             as evidence.
        control_code:        Optional control code (e.g. CROB control code,
                             0-255). Preserved as evidence.
        control_model:       Optional control model: "select_before_operate"
                             or "direct_operate". Must be consistent with the
                             operation (DIRECT_OPERATE may not claim
                             select_before_operate and vice versa).
        event_class:         Optional DNP3 event class (0-3). Relevant for
                             class reads and unsolicited reporting.
        value:               Optional command/write value. Evidence only —
                             never rendered into resource IDs.
        metadata:            Additional protocol-specific fields.
    """

    operation: str
    source_address: int | None = None
    destination_address: int | None = None
    outstation_id: str | None = None
    master_id: str | None = None
    object_group: int | None = None
    variation: int | None = None
    point_index: int | None = None
    point_type: str | None = None
    function_code: int | None = None
    qualifier: int | None = None
    control_code: int | None = None
    control_model: str | None = None
    event_class: int | None = None
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the DNP3 operation name and the path is a deterministic
        outstation-rooted address: "outstation:{target}" extended with
        "/{point_type}/{point_index}" for point-addressed operations or
        "/group/{object_group}[/variation/{variation}]" for object-group
        operations. All DNP3 fields are preserved in metadata for audit
        purposes.
        """
        target = self.outstation_id if self.outstation_id is not None else self.destination_address
        path = f"outstation:{target}"
        if self.point_type is not None and self.point_index is not None:
            path += f"/{self.point_type}/{self.point_index}"
        elif self.object_group is not None:
            path += f"/group/{self.object_group}"
            if self.variation is not None:
                path += f"/variation/{self.variation}"
        meta: dict[str, Any] = {
            "operation": self.operation,
            "source_address": self.source_address,
            "destination_address": self.destination_address,
            "outstation_id": self.outstation_id,
            "master_id": self.master_id,
            "object_group": self.object_group,
            "variation": self.variation,
            "point_index": self.point_index,
            "point_type": self.point_type,
            "function_code": self.function_code,
            "qualifier": self.qualifier,
            "control_code": self.control_code,
            "control_model": self.control_model,
            "event_class": self.event_class,
            "value": self.value,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="dnp3",
            method=self.operation,
            path=path,
            metadata=meta,
        )


@dataclass(frozen=True)
class Dnp3RouteMapping:
    """
    Maps a DNP3 (operation, point_type) pair to normalized authorization semantics.

    Attributes:
        operation:            DNP3 operation to match ("READ", "SELECT",
            "OPERATE", "DIRECT_OPERATE", "CONTROL", "ENABLE_UNSOLICITED"),
            or "*" for any.
        point_type:           Point type to match, or "*" for any (including
            an absent point_type). An exact point_type route only matches
            operations that carry that point type.
        action:               Normalized action verb (e.g. "read", "execute").
            If empty string, the default operation action map is consulted at
            normalization time (READ→read, SELECT/OPERATE/DIRECT_OPERATE/
            CONTROL→execute, ENABLE_UNSOLICITED→subscribe).
        resource_type:        Normalized resource category, e.g. "dnp3_point".
        resource_id_template: Template for the resource ID. May reference
            fields in VALID_DNP3_TEMPLATE_FIELDS. Control routes must
            reference {point_index}.
        name:                 Optional human-readable name (for diagnostics and
            duplicate-name detection).
    """

    operation: str
    point_type: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.operation}:{self.point_type}"

        # operation must be a valid DNP3 operation or wildcard
        if self.operation != "*" and self.operation not in VALID_DNP3_OPERATIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized DNP3 operation '{self.operation}'. "
                f"Valid operations: {sorted(VALID_DNP3_OPERATIONS)} or '*'"
            )

        # point_type must be a valid DNP3 point type or wildcard
        if self.point_type != "*" and self.point_type not in VALID_DNP3_POINT_TYPES:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized DNP3 point type '{self.point_type}'. "
                f"Valid point types: {sorted(VALID_DNP3_POINT_TYPES)} or '*'"
            )

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_DNP3_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_DNP3_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)

        # Control routes must identify the point being commanded.
        if self.operation in DNP3_CONTROL_OPERATIONS and "point_index" not in (
            _extract_template_fields(self.resource_id_template)
        ):
            raise InvalidMappingError(
                f"Route '{label}': control routes ({sorted(DNP3_CONTROL_OPERATIONS)}) must "
                "reference {point_index} in resource_id_template so the controlled point "
                "is identified"
            )


@dataclass
class Dnp3MappingConfig:
    """
    A validated collection of Dnp3RouteMapping entries for the DNP3 adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[Dnp3RouteMapping] = field(default_factory=list)

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

    def match(self, operation: Dnp3Operation) -> Dnp3RouteMapping:
        """
        Find the first matching route for the given DNP3 operation.

        Matching is performed on operation and point_type. A route field value
        of "*" matches any operation value for that field, including an absent
        point_type. An exact point_type route only matches operations that
        carry that point type.

        Returns:
            The first matching Dnp3RouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            operation_match = route.operation == "*" or route.operation == operation.operation
            point_type_match = route.point_type == "*" or route.point_type == operation.point_type
            if operation_match and point_type_match:
                return route
        raise UnknownRouteError(
            f"No route matched: operation={operation.operation!r} "
            f"point_type={operation.point_type!r}"
        )

    def resolve_action(self, route: Dnp3RouteMapping, operation: Dnp3Operation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the default
        operation action map is consulted (READ→read, SELECT/OPERATE/
        DIRECT_OPERATE/CONTROL→execute, ENABLE_UNSOLICITED→subscribe).

        Raises:
            InvalidMappingError: If neither the route nor the default map has an
                entry for the operation.
        """
        if route.action:
            return route.action
        if operation.operation in _DEFAULT_OPERATION_ACTION_MAP:
            return _DEFAULT_OPERATION_ACTION_MAP[operation.operation]
        raise InvalidMappingError(
            f"No default action mapping for DNP3 operation '{operation.operation}' "
            f"and route '{route.name or route.operation}' has no explicit action."
        )

    def resolve_resource_id(self, route: Dnp3RouteMapping, operation: Dnp3Operation) -> str:
        """
        Render the resource_id_template using fields from the DNP3 operation.

        Available substitution fields:
          {operation}            - DNP3 operation name
          {outstation_id}        - Outstation identifier (if present)
          {master_id}            - Master identifier (if present)
          {source_address}       - Source address as string (if present)
          {destination_address}  - Destination address as string (if present)
          {object_group}         - Object group as string (if present)
          {variation}            - Variation as string (if present)
          {point_index}          - Point index as string (if present)
          {point_type}           - Point type (if present)
          {event_class}          - Event class as string (if present)

        Optional fields are only available when present on the operation. A
        template that references an absent optional field fails closed.

        Command values are never available as template fields — they remain
        protocol evidence only.

        Raises:
            InvalidMappingError: If a template placeholder has no corresponding
                field available on the operation.
        """
        captures: dict[str, str] = {"operation": operation.operation}
        if operation.outstation_id is not None:
            captures["outstation_id"] = operation.outstation_id
        if operation.master_id is not None:
            captures["master_id"] = operation.master_id
        if operation.source_address is not None:
            captures["source_address"] = str(operation.source_address)
        if operation.destination_address is not None:
            captures["destination_address"] = str(operation.destination_address)
        if operation.object_group is not None:
            captures["object_group"] = str(operation.object_group)
        if operation.variation is not None:
            captures["variation"] = str(operation.variation)
        if operation.point_index is not None:
            captures["point_index"] = str(operation.point_index)
        if operation.point_type is not None:
            captures["point_type"] = operation.point_type
        if operation.event_class is not None:
            captures["event_class"] = str(operation.event_class)
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"field {exc} which is not available on the operation "
                f"(route '{route.name or route.operation}')"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Dnp3MappingConfig:
        """
        Parse a DNP3 mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[Dnp3RouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    Dnp3RouteMapping(
                        operation=raw.get("operation", ""),
                        point_type=raw.get("point_type", "*"),
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
