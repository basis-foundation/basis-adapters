"""
KNX adapter mapping configuration.

A KNX mapping config is a list of KnxRouteMapping entries. Each entry
describes how a specific KNX operation (and optional group address) should be
normalized into a BASIS authorization request.

KNX operations are matched by two fields:
  - operation      e.g. "GROUP_VALUE_READ", "GROUP_VALUE_WRITE", "*"
  - group_address  e.g. "1/2/3", "*"

The wildcard sentinel "*" matches any value for that field. Group addresses
are matched verbatim — no topology expansion, no semantic inference. Routes
are evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {operation}             - KNX operation name
  {group_address}         - KNX group address (always present)
  {individual_address}    - KNX individual address (if present)
  {device_address}        - KNX device address (if present)
  {communication_object}  - Communication object number (if present)
  {area}                  - Topology area number (if present)
  {line}                  - Topology line number (if present)
  {device}                - Topology device number (if present)

Fields marked "if present" are optional on the operation. A template that
references an optional field which is absent at normalization time fails
closed at render time.

Values, payloads, payload types, priority, and datapoint types are
deliberately NOT template fields: they are protocol evidence, never resource
identity. Resource IDs must stay deterministic and free of dynamic bus state.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_KNX_TEMPLATE_FIELDS.
- KNX reuses the existing canonical action vocabulary
  (GROUP_VALUE_READ→read, GROUP_VALUE_WRITE→write, GROUP_VALUE_RESPONSE→read,
  OBSERVE→subscribe). No new action verbs were added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# KNX operations supported by this adapter (protocol-intent names).
# GROUP_VALUE_READ models an A_GroupValue_Read intent; GROUP_VALUE_WRITE
# models an A_GroupValue_Write intent; GROUP_VALUE_RESPONSE models an
# A_GroupValue_Response (an observed answer to a read — data flowing back);
# OBSERVE models an explicit intent to monitor a group address for updates.
VALID_KNX_OPERATIONS = frozenset(
    {
        "GROUP_VALUE_READ",
        "GROUP_VALUE_WRITE",
        "GROUP_VALUE_RESPONSE",
        "OBSERVE",
    }
)

# KNX transmission priorities (frame priority classes).
VALID_KNX_PRIORITIES = frozenset({"system", "urgent", "normal", "low"})

# Normalized action verbs accepted for KNX routes. KNX reuses the shared
# action vocabulary unchanged — no new verbs were added.
VALID_KNX_ACTIONS = VALID_ACTIONS

# Default action mapping from KNX operation to normalized action verb.
# GROUP_VALUE_RESPONSE normalizes to "read": a response is data flowing back
# to a reader — the authorization-relevant semantics are read semantics.
# OBSERVE normalizes to "subscribe": an explicit intent to receive ongoing
# updates for a group address, with no implication of live bus monitoring.
_DEFAULT_OPERATION_ACTION_MAP: dict[str, str] = {
    "GROUP_VALUE_READ": "read",
    "GROUP_VALUE_WRITE": "write",
    "GROUP_VALUE_RESPONSE": "read",
    "OBSERVE": "subscribe",
}

# Fields that may be referenced in resource_id_template. Values, payloads,
# payload types, priority, and datapoint types are deliberately excluded —
# they are evidence, never resource identity.
VALID_KNX_TEMPLATE_FIELDS = frozenset(
    {
        "operation",
        "group_address",
        "individual_address",
        "device_address",
        "communication_object",
        "area",
        "line",
        "device",
    }
)

# Regex that extracts {param_name} tokens from a template string.
_CAPTURE_TOKEN_RE = re.compile(r"\{(\w+)\}")

# Regex that finds malformed brace tokens (unmatched or non-identifier content).
_MALFORMED_BRACE_RE = re.compile(r"\{[^}]*$|\{[^}\w][^}]*\}")

# KNX group address formats, matched verbatim:
#   three-level  main/middle/sub  (5/3/8 bits: 0-31 / 0-7 / 0-255)
#   two-level    main/sub         (5/11 bits:  0-31 / 0-2047)
#   free         single number    (16 bits:    0-65535)
_GROUP_ADDRESS_THREE_LEVEL_RE = re.compile(r"^(\d{1,2})/(\d)/(\d{1,3})$")
_GROUP_ADDRESS_TWO_LEVEL_RE = re.compile(r"^(\d{1,2})/(\d{1,4})$")
_GROUP_ADDRESS_FREE_RE = re.compile(r"^(\d{1,5})$")

# KNX individual (physical) address format: area.line.device
# (4/4/8 bits: 0-15 . 0-15 . 0-255).
_INDIVIDUAL_ADDRESS_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{1,3})$")

# KNX datapoint type (DPT) notation, e.g. "1.001", "9.001". This is a basic
# shape check only — the adapter does not parse or validate full DPT payload
# semantics.
_DATAPOINT_TYPE_RE = re.compile(r"^\d{1,3}\.\d{1,4}$")


def is_valid_group_address(value: str) -> bool:
    """
    Return True if value is a well-formed KNX group address.

    Accepts three-level ("main/middle/sub"), two-level ("main/sub"), and
    free-style (single 16-bit number) notation, with KNX range limits.
    The address is treated as an opaque verbatim identifier beyond this
    format check — no topology expansion, no semantic inference.
    """
    m = _GROUP_ADDRESS_THREE_LEVEL_RE.match(value)
    if m:
        main, middle, sub = (int(g) for g in m.groups())
        return main <= 31 and middle <= 7 and sub <= 255
    m = _GROUP_ADDRESS_TWO_LEVEL_RE.match(value)
    if m:
        main, sub = (int(g) for g in m.groups())
        return main <= 31 and sub <= 2047
    m = _GROUP_ADDRESS_FREE_RE.match(value)
    if m:
        return int(m.group(1)) <= 65535
    return False


def is_valid_individual_address(value: str) -> bool:
    """
    Return True if value is a well-formed KNX individual (physical) address
    in "area.line.device" notation with KNX range limits.
    """
    m = _INDIVIDUAL_ADDRESS_RE.match(value)
    if m:
        area, line, device = (int(g) for g in m.groups())
        return area <= 15 and line <= 15 and device <= 255
    return False


def is_valid_datapoint_type(value: str) -> bool:
    """
    Return True if value looks like KNX datapoint type (DPT) notation,
    e.g. "1.001". Basic shape check only — DPT payload semantics are not
    parsed or validated.
    """
    return _DATAPOINT_TYPE_RE.match(value) is not None


def _extract_template_fields(template: str) -> set[str]:
    """Return the set of field names referenced in a {param} template string."""
    return set(_CAPTURE_TOKEN_RE.findall(template))


def _validate_resource_id_template(template: str, route_label: str) -> None:
    """
    Validate that a resource_id_template is structurally sound and only
    references fields from VALID_KNX_TEMPLATE_FIELDS.

    Raises:
        InvalidMappingError: If the template is empty, malformed, or
            references unknown fields (including the evidence-only fields
            value, payload_type, priority, and datapoint_type).
    """
    if not template or not template.strip():
        raise InvalidMappingError(f"Route '{route_label}': resource_id_template must not be empty")
    if _MALFORMED_BRACE_RE.search(template):
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template contains malformed token in '{template}'"
        )
    refs = _extract_template_fields(template)
    unknown = refs - VALID_KNX_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_KNX_TEMPLATE_FIELDS)}. "
            "Values, payloads, payload types, priority, and datapoint types are "
            "evidence only and may never appear in resource IDs."
        )


@dataclass(frozen=True)
class KnxOperation:
    """
    A raw KNX operation, as received before normalization.

    This models the intent of a KNX application-layer group operation without
    representing actual wire traffic or a live bus connection. No KNX/IP
    tunneling. No routing. No multicast. No bus monitoring. No packet
    parsing. This is deliberately a small model — it does not attempt to
    represent the full KNX specification.

    Attributes:
        operation:            KNX operation name: "GROUP_VALUE_READ",
                              "GROUP_VALUE_WRITE", "GROUP_VALUE_RESPONSE",
                              or "OBSERVE".
        group_address:        KNX group address, e.g. "1/2/3" (three-level),
                              "1/200" (two-level), or "2563" (free style).
                              Required — every supported operation is a
                              group-address operation. Preserved verbatim;
                              never expanded into topology or semantics.
        individual_address:   Optional KNX individual (physical) address of
                              the originating or addressed device, e.g.
                              "1.1.5". Evidence only.
        device_address:       Optional device address, e.g. "1.1.7". Evidence
                              and optional device-specific resource identity.
        communication_object: Optional communication object number on the
                              device. Evidence and optional resource identity.
        datapoint_type:       Optional KNX datapoint type (DPT), e.g.
                              "1.001". Preserved as evidence — DPT payload
                              semantics are not parsed or validated beyond a
                              basic shape check.
        payload_type:         Optional payload type descriptor. Evidence only.
        value:                Optional payload value. Evidence only — never
                              rendered into resource IDs.
        priority:             Optional KNX frame priority: "system",
                              "urgent", "normal", or "low". Evidence only.
        area:                 Optional topology area number (0-15). Evidence
                              only.
        line:                 Optional topology line number (0-15). Evidence
                              only.
        device:               Optional topology device number (0-255).
                              Evidence only.
        metadata:             Additional protocol-specific fields.
    """

    operation: str
    group_address: str | None = None
    individual_address: str | None = None
    device_address: str | None = None
    communication_object: int | None = None
    datapoint_type: str | None = None
    payload_type: str | None = None
    value: Any = None
    priority: str | None = None
    area: int | None = None
    line: int | None = None
    device: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the KNX operation name and the path is a deterministic
        group-address-rooted address: "group:{group_address}" extended with
        "/object:{communication_object}" when a communication object is
        present. All KNX fields are preserved in metadata for audit purposes.
        """
        path = f"group:{self.group_address}"
        if self.communication_object is not None:
            path += f"/object:{self.communication_object}"
        meta: dict[str, Any] = {
            "operation": self.operation,
            "group_address": self.group_address,
            "individual_address": self.individual_address,
            "device_address": self.device_address,
            "communication_object": self.communication_object,
            "datapoint_type": self.datapoint_type,
            "payload_type": self.payload_type,
            "value": self.value,
            "priority": self.priority,
            "area": self.area,
            "line": self.line,
            "device": self.device,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="knx",
            method=self.operation,
            path=path,
            metadata=meta,
        )


@dataclass(frozen=True)
class KnxRouteMapping:
    """
    Maps a KNX (operation, group_address) pair to normalized authorization
    semantics.

    Attributes:
        operation:            KNX operation to match ("GROUP_VALUE_READ",
            "GROUP_VALUE_WRITE", "GROUP_VALUE_RESPONSE", "OBSERVE"), or "*"
            for any.
        group_address:        Group address to match verbatim, or "*" for
            any. Exact string comparison only — no topology expansion, no
            range matching, no semantic inference.
        action:               Normalized action verb (e.g. "read", "write").
            If empty string, the default operation action map is consulted
            at normalization time (GROUP_VALUE_READ→read,
            GROUP_VALUE_WRITE→write, GROUP_VALUE_RESPONSE→read,
            OBSERVE→subscribe).
        resource_type:        Normalized resource category, e.g.
            "knx_group_address".
        resource_id_template: Template for the resource ID. May reference
            fields in VALID_KNX_TEMPLATE_FIELDS. Values, payloads, payload
            types, priority, and datapoint types are never template fields.
        name:                 Optional human-readable name (for diagnostics
            and duplicate-name detection).
    """

    operation: str
    group_address: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.operation}:{self.group_address}"

        # operation must be a valid KNX operation or wildcard
        if self.operation != "*" and self.operation not in VALID_KNX_OPERATIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized KNX operation '{self.operation}'. "
                f"Valid operations: {sorted(VALID_KNX_OPERATIONS)} or '*'"
            )

        # group_address must be a non-empty string ("*" is the wildcard)
        if not self.group_address or not self.group_address.strip():
            raise InvalidMappingError(
                f"Route '{label}': group_address must be a non-empty string or '*'"
            )

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_KNX_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_KNX_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)


@dataclass
class KnxMappingConfig:
    """
    A validated collection of KnxRouteMapping entries for the KNX adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[KnxRouteMapping] = field(default_factory=list)

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

    def match(self, operation: KnxOperation) -> KnxRouteMapping:
        """
        Find the first matching route for the given KNX operation.

        Matching is performed on operation and group_address. A route field
        value of "*" matches any operation value for that field. Group
        addresses are compared verbatim — no topology expansion, no range
        matching, no semantic inference.

        Returns:
            The first matching KnxRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            operation_match = route.operation == "*" or route.operation == operation.operation
            ga_match = route.group_address == "*" or route.group_address == operation.group_address
            if operation_match and ga_match:
                return route
        raise UnknownRouteError(
            f"No route matched: operation={operation.operation!r} "
            f"group_address={operation.group_address!r}"
        )

    def resolve_action(self, route: KnxRouteMapping, operation: KnxOperation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the
        default operation action map is consulted (GROUP_VALUE_READ→read,
        GROUP_VALUE_WRITE→write, GROUP_VALUE_RESPONSE→read,
        OBSERVE→subscribe).

        Raises:
            InvalidMappingError: If neither the route nor the default map has
                an entry for the operation.
        """
        if route.action:
            return route.action
        if operation.operation in _DEFAULT_OPERATION_ACTION_MAP:
            return _DEFAULT_OPERATION_ACTION_MAP[operation.operation]
        raise InvalidMappingError(
            f"No default action mapping for KNX operation '{operation.operation}' "
            f"and route '{route.name or route.operation}' has no explicit action."
        )

    def resolve_resource_id(self, route: KnxRouteMapping, operation: KnxOperation) -> str:
        """
        Render the resource_id_template using fields from the KNX operation.

        Available substitution fields:
          {operation}             - KNX operation name
          {group_address}         - KNX group address
          {individual_address}    - Individual address (if present)
          {device_address}        - Device address (if present)
          {communication_object}  - Communication object number (if present)
          {area}                  - Topology area number (if present)
          {line}                  - Topology line number (if present)
          {device}                - Topology device number (if present)

        Optional fields are only available when present on the operation. A
        template that references an absent optional field fails closed.

        Values, payloads, payload types, priority, and datapoint types are
        never available as template fields — they remain protocol evidence
        only.

        Raises:
            InvalidMappingError: If a template placeholder has no
                corresponding field available on the operation.
        """
        captures: dict[str, str] = {"operation": operation.operation}
        if operation.group_address is not None:
            captures["group_address"] = operation.group_address
        if operation.individual_address is not None:
            captures["individual_address"] = operation.individual_address
        if operation.device_address is not None:
            captures["device_address"] = operation.device_address
        if operation.communication_object is not None:
            captures["communication_object"] = str(operation.communication_object)
        if operation.area is not None:
            captures["area"] = str(operation.area)
        if operation.line is not None:
            captures["line"] = str(operation.line)
        if operation.device is not None:
            captures["device"] = str(operation.device)
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"field {exc} which is not available on the operation "
                f"(route '{route.name or route.operation}')"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnxMappingConfig:
        """
        Parse a KNX mapping config from a plain dictionary (e.g. loaded from
        JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[KnxRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    KnxRouteMapping(
                        operation=raw.get("operation", ""),
                        group_address=raw.get("group_address", "*"),
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
