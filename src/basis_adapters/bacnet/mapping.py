"""
BACnet adapter mapping configuration.

A BACnet mapping config is a list of BacnetRouteMapping entries. Each entry
describes how a specific BACnet service + object type + property identifier
combination should be normalized into a BASIS authorization request.

BACnet operations are matched by three fields:
  - service          e.g. "ReadProperty", "WriteProperty", "*"
  - object_type      e.g. "analogInput", "binaryOutput", "*"
  - property_identifier  e.g. "presentValue", "description", "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {service}             - BACnet service name
  {object_type}         - BACnet object type
  {object_instance}     - BACnet object instance number (as string)
  {property_identifier} - BACnet property identifier
  {device_id}           - BACnet device identifier (fails if None)

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_BACNET_TEMPLATE_FIELDS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared constant.
from basis_adapters.rest.mapping import VALID_ACTIONS

# Recognized BACnet service primitives supported by this adapter.
VALID_BACNET_SERVICES = frozenset({"ReadProperty", "WriteProperty", "SubscribeCOV", "CommandValue"})

# Fields that may be referenced in resource_id_template.
VALID_BACNET_TEMPLATE_FIELDS = frozenset(
    {"service", "object_type", "object_instance", "property_identifier", "device_id"}
)

# Default action mapping from BACnet service to normalized action verb.
_DEFAULT_SERVICE_ACTION_MAP: dict[str, str] = {
    "ReadProperty": "read",
    "WriteProperty": "write",
    "SubscribeCOV": "subscribe",
    "CommandValue": "control",
}

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
    references fields from VALID_BACNET_TEMPLATE_FIELDS.

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
    unknown = refs - VALID_BACNET_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_BACNET_TEMPLATE_FIELDS)}"
        )


@dataclass(frozen=True)
class BacnetOperation:
    """
    A raw BACnet protocol operation, as received before normalization.

    Attributes:
        service:             BACnet service primitive, e.g. "ReadProperty".
        object_type:         BACnet object type, e.g. "analogInput".
        object_instance:     BACnet object instance number, e.g. 1.
        property_identifier: BACnet property, e.g. "presentValue".
        device_id:           Optional BACnet device identifier string.
        priority:            Optional write/command priority (1–16).
        value_present:       True if the operation carries a value payload.
        metadata:            Additional protocol-specific fields.
    """

    service: str
    object_type: str
    object_instance: int
    property_identifier: str
    device_id: str | None = None
    priority: int | None = None
    value_present: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The path encodes the object identity as
        ``{object_type}:{object_instance}:{property_identifier}``.
        All BACnet fields are preserved in metadata for audit purposes.
        """
        meta: dict[str, Any] = {
            "service": self.service,
            "object_type": self.object_type,
            "object_instance": self.object_instance,
            "property_identifier": self.property_identifier,
            "device_id": self.device_id,
            "priority": self.priority,
            "value_present": self.value_present,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="bacnet",
            method=self.service,
            path=f"{self.object_type}:{self.object_instance}:{self.property_identifier}",
            metadata=meta,
        )


@dataclass(frozen=True)
class BacnetRouteMapping:
    """
    Maps a BACnet (service, object_type, property_identifier) combination to
    normalized authorization semantics.

    Attributes:
        service:             BACnet service to match, or "*" for any.
        object_type:         BACnet object type to match, or "*" for any.
        property_identifier: BACnet property identifier to match, or "*" for any.
        action:              Normalized action verb (e.g. "read", "write").
            If empty string, the default service action map is consulted at
            normalization time.
        resource_type:       Normalized resource category, e.g. "point".
        resource_id_template: Template for the resource ID. May reference
            {service}, {object_type}, {object_instance}, {property_identifier},
            {device_id}. All referenced fields must be in
            VALID_BACNET_TEMPLATE_FIELDS.
        name:                Optional human-readable name (for diagnostics and
            duplicate-name detection).
    """

    service: str
    object_type: str
    property_identifier: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.service}:{self.object_type}:{self.property_identifier}"

        # service must be a valid BACnet service or wildcard
        if self.service != "*" and self.service not in VALID_BACNET_SERVICES:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized BACnet service '{self.service}'. "
                f"Valid services: {sorted(VALID_BACNET_SERVICES)} or '*'"
            )

        # object_type and property_identifier can be any non-empty string or "*"
        if not self.object_type:
            raise InvalidMappingError(f"Route '{label}': object_type must not be empty")
        if not self.property_identifier:
            raise InvalidMappingError(f"Route '{label}': property_identifier must not be empty")

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)


@dataclass
class BacnetMappingConfig:
    """
    A validated collection of BacnetRouteMapping entries for the BACnet adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[BacnetRouteMapping] = field(default_factory=list)

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

    def match(self, operation: BacnetOperation) -> BacnetRouteMapping:
        """
        Find the first matching route for the given BACnet operation.

        Matching is performed on service, object_type, and property_identifier.
        A route field value of "*" matches any operation value for that field.

        Returns:
            The first matching BacnetRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            if (
                (route.service == "*" or route.service == operation.service)
                and (route.object_type == "*" or route.object_type == operation.object_type)
                and (
                    route.property_identifier == "*"
                    or route.property_identifier == operation.property_identifier
                )
            ):
                return route
        raise UnknownRouteError(
            f"No route matched: service={operation.service!r} "
            f"object_type={operation.object_type!r} "
            f"property_identifier={operation.property_identifier!r}"
        )

    def resolve_action(self, route: BacnetRouteMapping, operation: BacnetOperation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the default
        service action map is consulted.

        Raises:
            InvalidMappingError: If neither the route nor the default map has an
                entry for the operation's service.
        """
        if route.action:
            return route.action
        if operation.service in _DEFAULT_SERVICE_ACTION_MAP:
            return _DEFAULT_SERVICE_ACTION_MAP[operation.service]
        raise InvalidMappingError(
            f"No default action mapping for BACnet service '{operation.service}' "
            f"and route '{route.name or route.service}' has no explicit action."
        )

    def resolve_resource_id(self, route: BacnetRouteMapping, operation: BacnetOperation) -> str:
        """
        Render the resource_id_template using fields from the BACnet operation.

        If the template references {device_id} and operation.device_id is None,
        raises InvalidMappingError with a descriptive message rather than silently
        substituting an empty string.

        Raises:
            InvalidMappingError: If device_id is None but referenced, or if any
                template placeholder has no corresponding field.
        """
        if "{device_id}" in route.resource_id_template and operation.device_id is None:
            raise InvalidMappingError(
                f"Route '{route.name or route.service}': resource_id_template references "
                f"{{device_id}} but operation.device_id is None"
            )
        captures: dict[str, str] = {
            "service": operation.service,
            "object_type": operation.object_type,
            "object_instance": str(operation.object_instance),
            "property_identifier": operation.property_identifier,
            "device_id": operation.device_id or "",
        }
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"undefined field {exc} for route '{route.name or route.service}'"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BacnetMappingConfig:
        """
        Parse a BACnet mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[BacnetRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    BacnetRouteMapping(
                        service=raw.get("service", ""),
                        object_type=raw.get("object_type", ""),
                        property_identifier=raw.get("property_identifier", ""),
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
