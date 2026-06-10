"""
MQTT adapter mapping configuration.

An MQTT mapping config is a list of MqttRouteMapping entries. Each entry
describes how a specific MQTT operation (and optional exact topic) should
be normalized into a BASIS authorization request.

MQTT operations are matched by two fields:
  - operation  e.g. "PUBLISH", "SUBSCRIBE", "*"
  - topic      an exact topic string, or "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Topic matching is deliberately literal. A route ``topic`` is compared for
exact string equality with the operation topic (or matched by the "*"
sentinel). The adapter performs **no MQTT topic-filter matching**: MQTT
wildcard characters (``+`` and ``#``) appearing in an operation topic are
preserved verbatim as opaque strings and are never expanded or matched
against other topics. Wildcard authorization policy belongs to higher-level
policy evaluation, not the adapter.

Resource ID templates may reference the following fields using {param} syntax:
  {operation}      - MQTT operation name ("PUBLISH" or "SUBSCRIBE")
  {topic}          - MQTT topic string, preserved verbatim
  {client_id}      - MQTT client identifier (fails closed if absent)
  {qos}            - Quality of Service level (0, 1, or 2; as string)
  {payload_type}   - Declared payload type (json, text, binary, unknown)

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_MQTT_TEMPLATE_FIELDS.
- MQTT reuses the existing canonical action vocabulary (PUBLISH→write,
  SUBSCRIBE→subscribe by default). No new action verbs were added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# MQTT operations supported by this adapter (protocol-native packet names).
VALID_MQTT_OPERATIONS = frozenset({"PUBLISH", "SUBSCRIBE"})

# Declared payload types accepted on an MQTT operation.
VALID_MQTT_PAYLOAD_TYPES = frozenset({"json", "text", "binary", "unknown"})

# MQTT QoS levels.
VALID_MQTT_QOS_LEVELS = frozenset({0, 1, 2})

# Default action mapping from MQTT operation to normalized action verb.
# MQTT uses the existing canonical actions; no new verbs were introduced.
_DEFAULT_OPERATION_ACTION_MAP: dict[str, str] = {
    "PUBLISH": "write",
    "SUBSCRIBE": "subscribe",
}

# Fields that may be referenced in resource_id_template.
VALID_MQTT_TEMPLATE_FIELDS = frozenset({"operation", "topic", "client_id", "qos", "payload_type"})

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
    references fields from VALID_MQTT_TEMPLATE_FIELDS.

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
    unknown = refs - VALID_MQTT_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_MQTT_TEMPLATE_FIELDS)}"
        )


@dataclass(frozen=True)
class MqttOperation:
    """
    A raw MQTT operation, as received before normalization.

    This models the intent of an MQTT PUBLISH or SUBSCRIBE without
    representing actual wire packets or a live broker connection.
    No paho-mqtt. No TCP sockets. No broker.

    Attributes:
        operation:        MQTT operation name: "PUBLISH" or "SUBSCRIBE"
                          (protocol-native packet names).
        topic:            MQTT topic (PUBLISH) or topic filter (SUBSCRIBE).
                          Required. Preserved verbatim — MQTT wildcards
                          (``+``, ``#``) are never expanded by the adapter.
        client_id:        Optional MQTT client identifier. Evidence only —
                          never treated as verified identity.
        qos:              Quality of Service level: 0, 1, or 2. Defaults to 0.
        retain:           Retain flag. Relevant for PUBLISH; must be False
                          for SUBSCRIBE operations.
        payload_type:     Declared payload type: "json", "text", "binary",
                          or "unknown". Defaults to "unknown". The adapter
                          never inspects payload bytes.
        protocol_version: Optional MQTT protocol version string,
                          e.g. "3.1.1" or "5.0".
        metadata:         Additional protocol-specific fields.
    """

    operation: str
    topic: str
    client_id: str | None = None
    qos: int = 0
    retain: bool = False
    payload_type: str = "unknown"
    protocol_version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the MQTT operation name and the path is the topic,
        preserved verbatim (including any ``+``/``#`` wildcard characters).
        All MQTT fields are preserved in metadata for audit purposes.
        """
        meta: dict[str, Any] = {
            "operation": self.operation,
            "topic": self.topic,
            "client_id": self.client_id,
            "qos": self.qos,
            "retain": self.retain,
            "payload_type": self.payload_type,
            "protocol_version": self.protocol_version,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="mqtt",
            method=self.operation,
            path=self.topic,
            metadata=meta,
        )


@dataclass(frozen=True)
class MqttRouteMapping:
    """
    Maps an MQTT (operation, topic) pair to normalized authorization semantics.

    Attributes:
        operation:            MQTT operation to match ("PUBLISH" or
            "SUBSCRIBE"), or "*" for any.
        topic:                Exact topic string to match, or "*" for any.
            Matching is literal string equality — the route never performs
            MQTT topic-filter matching, and ``+``/``#`` in a route topic
            match only a literally identical operation topic.
        action:               Normalized action verb (e.g. "write",
            "subscribe"). If empty string, the default operation action map
            is consulted at normalization time (PUBLISH→write,
            SUBSCRIBE→subscribe).
        resource_type:        Normalized resource category, e.g. "mqtt_topic".
        resource_id_template: Template for the resource ID. May reference
            {operation}, {topic}, {client_id}, {qos}, {payload_type}.
            All referenced fields must be in VALID_MQTT_TEMPLATE_FIELDS.
        name:                 Optional human-readable name (for diagnostics and
            duplicate-name detection).
    """

    operation: str
    topic: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.operation}:{self.topic}"

        # operation must be a valid MQTT operation or wildcard
        if self.operation != "*" and self.operation not in VALID_MQTT_OPERATIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized MQTT operation '{self.operation}'. "
                f"Valid operations: {sorted(VALID_MQTT_OPERATIONS)} or '*'"
            )

        # topic: any non-empty string or wildcard sentinel
        if not self.topic or not self.topic.strip():
            raise InvalidMappingError(f"Route '{label}': topic must not be empty")

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
class MqttMappingConfig:
    """
    A validated collection of MqttRouteMapping entries for the MQTT adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[MqttRouteMapping] = field(default_factory=list)

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

    def match(self, operation: MqttOperation) -> MqttRouteMapping:
        """
        Find the first matching route for the given MQTT operation.

        Matching is performed on operation and topic. A route field value of
        "*" matches any operation value for that field. Topic comparison is
        literal string equality — no MQTT topic-filter matching is performed,
        and wildcard characters in the operation topic are treated as opaque.

        Returns:
            The first matching MqttRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            operation_match = route.operation == "*" or route.operation == operation.operation
            topic_match = route.topic == "*" or route.topic == operation.topic
            if operation_match and topic_match:
                return route
        raise UnknownRouteError(
            f"No route matched: operation={operation.operation!r} topic={operation.topic!r}"
        )

    def resolve_action(self, route: MqttRouteMapping, operation: MqttOperation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the default
        operation action map is consulted (PUBLISH→write, SUBSCRIBE→subscribe).

        Raises:
            InvalidMappingError: If neither the route nor the default map has an
                entry for the operation.
        """
        if route.action:
            return route.action
        if operation.operation in _DEFAULT_OPERATION_ACTION_MAP:
            return _DEFAULT_OPERATION_ACTION_MAP[operation.operation]
        raise InvalidMappingError(
            f"No default action mapping for MQTT operation '{operation.operation}' "
            f"and route '{route.name or route.operation}' has no explicit action."
        )

    def resolve_resource_id(self, route: MqttRouteMapping, operation: MqttOperation) -> str:
        """
        Render the resource_id_template using fields from the MQTT operation.

        Available substitution fields:
          {operation}     - MQTT operation name
          {topic}         - MQTT topic, preserved verbatim
          {client_id}     - Client identifier (fails closed if absent)
          {qos}           - QoS level as string
          {payload_type}  - Declared payload type

        Raises:
            InvalidMappingError: If a template placeholder has no corresponding
                field (e.g. {client_id} referenced but the operation carries no
                client_id).
        """
        captures: dict[str, str] = {
            "operation": operation.operation,
            "topic": operation.topic,
            "qos": str(operation.qos),
            "payload_type": operation.payload_type,
        }
        if operation.client_id is not None:
            captures["client_id"] = operation.client_id
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"undefined field {exc} for route '{route.name or route.operation}'"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MqttMappingConfig:
        """
        Parse an MQTT mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[MqttRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    MqttRouteMapping(
                        operation=raw.get("operation", ""),
                        topic=raw.get("topic", ""),
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
