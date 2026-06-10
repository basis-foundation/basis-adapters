"""
OPC UA adapter mapping configuration.

An OPC UA mapping config is a list of OpcuaRouteMapping entries. Each entry
describes how a specific OPC UA service (and optional attribute) should be
normalized into a BASIS authorization request.

OPC UA operations are matched by two fields:
  - service       e.g. "Read", "Write", "Call", "Subscribe", "Browse", "*"
  - attribute_id  e.g. "Value", "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {service}          - OPC UA service name
  {node_id}          - Target node identifier, e.g. "ns=2;s=Building.AHU1.SupplyTemp"
  {attribute_id}     - Attribute identifier, e.g. "Value" (if present on the operation)
  {method_id}        - Method node identifier (if present on the operation)
  {namespace_index}  - Namespace index as string (if present on the operation)
  {browse_name}      - Browse name (if present on the operation)
  {parent_node_id}   - Parent node identifier (if present on the operation)

Fields marked "if present" are optional on the operation. A template that
references an optional field which is absent at normalization time fails
closed at render time.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_OPCUA_TEMPLATE_FIELDS.
- Call routes must reference {method_id} in their resource_id_template so a
  method invocation is never normalized without identifying the method.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# OPC UA services supported by this adapter.
VALID_OPCUA_SERVICES = frozenset({"Read", "Write", "Call", "Subscribe", "Browse"})

# Normalized action verbs accepted for OPC UA routes. OPC UA extends the shared
# action vocabulary with "execute" (method invocation) and "browse" (address
# space traversal). Both verbs are part of the canonical normalized request
# schema (schemas/normalized-authorization-request.schema.json).
VALID_OPCUA_ACTIONS = VALID_ACTIONS | frozenset({"execute", "browse"})

# Default action mapping from OPC UA service to normalized action verb.
_DEFAULT_SERVICE_ACTION_MAP: dict[str, str] = {
    "Read": "read",
    "Write": "write",
    "Call": "execute",
    "Subscribe": "subscribe",
    "Browse": "browse",
}

# OPC UA node identifier types (NodeId IdentifierType).
VALID_OPCUA_IDENTIFIER_TYPES = frozenset({"numeric", "string", "guid", "opaque"})

# Fields that may be referenced in resource_id_template.
VALID_OPCUA_TEMPLATE_FIELDS = frozenset(
    {
        "service",
        "node_id",
        "attribute_id",
        "method_id",
        "namespace_index",
        "browse_name",
        "parent_node_id",
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
    references fields from VALID_OPCUA_TEMPLATE_FIELDS.

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
    unknown = refs - VALID_OPCUA_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_OPCUA_TEMPLATE_FIELDS)}"
        )


@dataclass(frozen=True)
class OpcuaOperation:
    """
    A raw OPC UA operation, as received before normalization.

    This models the intent of an OPC UA service request without representing
    actual wire messages or a live session. No asyncua. No TCP. No secure
    channel. No session management.

    Attributes:
        service:            OPC UA service name, e.g. "Read", "Write", "Call",
                            "Subscribe", "Browse".
        node_id:            Target node identifier in OPC UA string notation,
                            e.g. "ns=2;s=Building.AHU1.SupplyTemp".
        attribute_id:       Optional attribute identifier, e.g. "Value".
        method_id:          Optional method node identifier; required for Call.
        namespace_index:    Optional namespace index of the target node.
        identifier:         Optional bare identifier portion of the node ID.
        identifier_type:    Optional identifier type: "numeric", "string",
                            "guid", or "opaque".
        browse_name:        Optional browse name of the target node.
        parent_node_id:     Optional parent/owning node identifier.
        subscription_id:    Optional subscription identifier (Subscribe).
        monitored_item_id:  Optional monitored item identifier (Subscribe).
        value_present:      True if the operation carries a write payload.
        endpoint_url:       Optional endpoint URL the request was addressed to.
        session_id:         Optional OPC UA session identifier string.
        metadata:           Additional protocol-specific fields.
    """

    service: str
    node_id: str
    attribute_id: str | None = None
    method_id: str | None = None
    namespace_index: int | None = None
    identifier: str | None = None
    identifier_type: str | None = None
    browse_name: str | None = None
    parent_node_id: str | None = None
    subscription_id: int | None = None
    monitored_item_id: int | None = None
    value_present: bool = False
    endpoint_url: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the OPC UA service name and the path is the target node
        identifier. All OPC UA fields are preserved in metadata for audit
        purposes.
        """
        meta: dict[str, Any] = {
            "service": self.service,
            "node_id": self.node_id,
            "attribute_id": self.attribute_id,
            "method_id": self.method_id,
            "namespace_index": self.namespace_index,
            "identifier": self.identifier,
            "identifier_type": self.identifier_type,
            "browse_name": self.browse_name,
            "parent_node_id": self.parent_node_id,
            "subscription_id": self.subscription_id,
            "monitored_item_id": self.monitored_item_id,
            "value_present": self.value_present,
            "endpoint_url": self.endpoint_url,
            "session_id": self.session_id,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="opcua",
            method=self.service,
            path=self.node_id,
            metadata=meta,
        )


@dataclass(frozen=True)
class OpcuaRouteMapping:
    """
    Maps an OPC UA (service, attribute_id) pair to normalized authorization semantics.

    Attributes:
        service:              OPC UA service to match, or "*" for any.
        attribute_id:         Attribute identifier to match, or "*" for any.
        action:               Normalized action verb (e.g. "read", "execute").
            If empty string, the default service action map is consulted at
            normalization time.
        resource_type:        Normalized resource category, e.g. "opcua_node".
        resource_id_template: Template for the resource ID. May reference
            {service}, {node_id}, {attribute_id}, {method_id},
            {namespace_index}, {browse_name}, {parent_node_id}.
        name:                 Optional human-readable name (for diagnostics and
            duplicate-name detection).
    """

    service: str
    attribute_id: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.service}:{self.attribute_id}"

        # service must be a valid OPC UA service or wildcard
        if self.service != "*" and self.service not in VALID_OPCUA_SERVICES:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized OPC UA service '{self.service}'. "
                f"Valid services: {sorted(VALID_OPCUA_SERVICES)} or '*'"
            )

        # attribute_id: any non-empty string or wildcard
        if not self.attribute_id:
            raise InvalidMappingError(f"Route '{label}': attribute_id must not be empty")

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_OPCUA_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_OPCUA_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)

        # Call routes must identify the method being invoked.
        if self.service == "Call" and "method_id" not in _extract_template_fields(
            self.resource_id_template
        ):
            raise InvalidMappingError(
                f"Route '{label}': Call routes must reference {{method_id}} in "
                "resource_id_template so the invoked method is identified"
            )


@dataclass
class OpcuaMappingConfig:
    """
    A validated collection of OpcuaRouteMapping entries for the OPC UA adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[OpcuaRouteMapping] = field(default_factory=list)

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

    def match(self, operation: OpcuaOperation) -> OpcuaRouteMapping:
        """
        Find the first matching route for the given OPC UA operation.

        Matching is performed on service and attribute_id. A route field value
        of "*" matches any operation value for that field, including an absent
        attribute_id. An exact attribute_id route only matches operations that
        carry that attribute.

        Returns:
            The first matching OpcuaRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            service_match = route.service == "*" or route.service == operation.service
            attribute_match = (
                route.attribute_id == "*" or route.attribute_id == operation.attribute_id
            )
            if service_match and attribute_match:
                return route
        raise UnknownRouteError(
            f"No route matched: service={operation.service!r} "
            f"attribute_id={operation.attribute_id!r}"
        )

    def resolve_action(self, route: OpcuaRouteMapping, operation: OpcuaOperation) -> str:
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
            f"No default action mapping for OPC UA service '{operation.service}' "
            f"and route '{route.name or route.service}' has no explicit action."
        )

    def resolve_resource_id(self, route: OpcuaRouteMapping, operation: OpcuaOperation) -> str:
        """
        Render the resource_id_template using fields from the OPC UA operation.

        Available substitution fields:
          {service}          - OPC UA service name
          {node_id}          - Target node identifier
          {attribute_id}     - Attribute identifier (if present)
          {method_id}        - Method node identifier (if present)
          {namespace_index}  - Namespace index as string (if present)
          {browse_name}      - Browse name (if present)
          {parent_node_id}   - Parent node identifier (if present)

        Optional fields are only available when present on the operation. A
        template that references an absent optional field fails closed.

        Raises:
            InvalidMappingError: If a template placeholder has no corresponding
                field available on the operation.
        """
        captures: dict[str, str] = {
            "service": operation.service,
            "node_id": operation.node_id,
        }
        if operation.attribute_id is not None:
            captures["attribute_id"] = operation.attribute_id
        if operation.method_id is not None:
            captures["method_id"] = operation.method_id
        if operation.namespace_index is not None:
            captures["namespace_index"] = str(operation.namespace_index)
        if operation.browse_name is not None:
            captures["browse_name"] = operation.browse_name
        if operation.parent_node_id is not None:
            captures["parent_node_id"] = operation.parent_node_id
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"field {exc} which is not available on the operation "
                f"(route '{route.name or route.service}')"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpcuaMappingConfig:
        """
        Parse an OPC UA mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[OpcuaRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    OpcuaRouteMapping(
                        service=raw.get("service", ""),
                        attribute_id=raw.get("attribute_id", "*"),
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
