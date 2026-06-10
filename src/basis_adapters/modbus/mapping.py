"""
Modbus adapter mapping configuration.

A Modbus mapping config is a list of ModbusRouteMapping entries. Each entry
describes how a specific Modbus function (and optional register type) should
be normalized into a BASIS authorization request.

Modbus operations are matched by two fields:
  - function       e.g. "ReadHoldingRegisters", "WriteSingleRegister", "*"
  - register_type  e.g. "holding_register", "coil", "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {function}        - Modbus function code name
  {unit_id}         - Modbus unit/device identifier (integer, as string)
  {address}         - Starting register address (integer, as string)
  {quantity}        - Number of registers/coils (integer, as string; "1" if absent)
  {register_type}   - Register type inferred from function or operation

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against VALID_MODBUS_TEMPLATE_FIELDS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# All Modbus function codes supported by this adapter.
VALID_MODBUS_FUNCTIONS = frozenset(
    {
        "ReadCoils",
        "ReadDiscreteInputs",
        "ReadHoldingRegisters",
        "ReadInputRegisters",
        "WriteSingleCoil",
        "WriteSingleRegister",
        "WriteMultipleCoils",
        "WriteMultipleRegisters",
    }
)

# Register types inferred from function codes when not explicitly provided.
_FUNCTION_REGISTER_TYPE: dict[str, str] = {
    "ReadCoils": "coil",
    "ReadDiscreteInputs": "discrete_input",
    "ReadHoldingRegisters": "holding_register",
    "ReadInputRegisters": "input_register",
    "WriteSingleCoil": "coil",
    "WriteSingleRegister": "holding_register",
    "WriteMultipleCoils": "coil",
    "WriteMultipleRegisters": "holding_register",
}

# Default action mapping from Modbus function to normalized action verb.
_DEFAULT_FUNCTION_ACTION_MAP: dict[str, str] = {
    "ReadCoils": "read",
    "ReadDiscreteInputs": "read",
    "ReadHoldingRegisters": "read",
    "ReadInputRegisters": "read",
    "WriteSingleCoil": "write",
    "WriteSingleRegister": "write",
    "WriteMultipleCoils": "write",
    "WriteMultipleRegisters": "write",
}

# Fields that may be referenced in resource_id_template.
VALID_MODBUS_TEMPLATE_FIELDS = frozenset(
    {"function", "unit_id", "address", "quantity", "register_type"}
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
    references fields from VALID_MODBUS_TEMPLATE_FIELDS.

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
    unknown = refs - VALID_MODBUS_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_MODBUS_TEMPLATE_FIELDS)}"
        )


@dataclass(frozen=True)
class ModbusOperation:
    """
    A raw Modbus operation, as received before normalization.

    This models the intent of a Modbus request without representing actual
    wire bytes or a live connection. No pymodbus. No TCP sockets.

    Attributes:
        function:        Modbus function code name, e.g. "ReadHoldingRegisters".
        unit_id:         Modbus unit identifier (device address), 1–247.
        address:         Starting register or coil address (0-based or 1-based
                         depending on convention; preserved as-is for evidence).
        quantity:        Number of registers or coils requested. Defaults to 1.
        value_present:   True if the operation carries a write payload.
        register_type:   Optional explicit register type override. If absent,
                         inferred from the function code at normalization time.
        source_address:  Optional source IP or network address string.
        transaction_id:  Optional Modbus TCP transaction identifier.
        metadata:        Additional protocol-specific fields.
    """

    function: str
    unit_id: int
    address: int
    quantity: int = 1
    value_present: bool = False
    register_type: str | None = None
    source_address: str | None = None
    transaction_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def effective_register_type(self) -> str:
        """
        Return the effective register type for this operation.

        If the operation carries an explicit register_type, it is returned.
        Otherwise, the type is inferred from the function code.
        Returns "unknown" for unrecognized functions (caller should handle
        this via fail-closed before reaching this point).
        """
        if self.register_type is not None:
            return self.register_type
        return _FUNCTION_REGISTER_TYPE.get(self.function, "unknown")

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The path encodes the unit and address as
        ``unit:{unit_id}:addr:{address}``. All Modbus fields are preserved
        in metadata for audit purposes.
        """
        meta: dict[str, Any] = {
            "function": self.function,
            "unit_id": self.unit_id,
            "address": self.address,
            "quantity": self.quantity,
            "value_present": self.value_present,
            "register_type": self.register_type,
            "source_address": self.source_address,
            "transaction_id": self.transaction_id,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="modbus",
            method=self.function,
            path=f"unit:{self.unit_id}:addr:{self.address}",
            metadata=meta,
        )


@dataclass(frozen=True)
class ModbusRouteMapping:
    """
    Maps a Modbus (function, register_type) pair to normalized authorization semantics.

    Attributes:
        function:             Modbus function to match, or "*" for any.
        register_type:        Register type to match, or "*" for any.
        action:               Normalized action verb (e.g. "read", "write").
            If empty string, the default function action map is consulted at
            normalization time.
        resource_type:        Normalized resource category, e.g. "modbus_register".
        resource_id_template: Template for the resource ID. May reference
            {function}, {unit_id}, {address}, {quantity}, {register_type}.
            All referenced fields must be in VALID_MODBUS_TEMPLATE_FIELDS.
        name:                 Optional human-readable name (for diagnostics and
            duplicate-name detection).
    """

    function: str
    register_type: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.function}:{self.register_type}"

        # function must be a valid Modbus function or wildcard
        if self.function != "*" and self.function not in VALID_MODBUS_FUNCTIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized Modbus function '{self.function}'. "
                f"Valid functions: {sorted(VALID_MODBUS_FUNCTIONS)} or '*'"
            )

        # register_type: any non-empty string or wildcard
        if not self.register_type:
            raise InvalidMappingError(f"Route '{label}': register_type must not be empty")

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
class ModbusMappingConfig:
    """
    A validated collection of ModbusRouteMapping entries for the Modbus adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[ModbusRouteMapping] = field(default_factory=list)

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

    def match(self, operation: ModbusOperation) -> ModbusRouteMapping:
        """
        Find the first matching route for the given Modbus operation.

        Matching is performed on function and register_type. A route field
        value of "*" matches any operation value for that field. For
        register_type, the effective register type (inferred from the function
        if not explicitly set on the operation) is used for matching.

        Returns:
            The first matching ModbusRouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        effective_rt = operation.effective_register_type()
        for route in self.routes:
            function_match = route.function == "*" or route.function == operation.function
            register_match = route.register_type == "*" or route.register_type == effective_rt
            if function_match and register_match:
                return route
        raise UnknownRouteError(
            f"No route matched: function={operation.function!r} register_type={effective_rt!r}"
        )

    def resolve_action(self, route: ModbusRouteMapping, operation: ModbusOperation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the default
        function action map is consulted.

        Raises:
            InvalidMappingError: If neither the route nor the default map has an
                entry for the operation's function.
        """
        if route.action:
            return route.action
        if operation.function in _DEFAULT_FUNCTION_ACTION_MAP:
            return _DEFAULT_FUNCTION_ACTION_MAP[operation.function]
        raise InvalidMappingError(
            f"No default action mapping for Modbus function '{operation.function}' "
            f"and route '{route.name or route.function}' has no explicit action."
        )

    def resolve_resource_id(self, route: ModbusRouteMapping, operation: ModbusOperation) -> str:
        """
        Render the resource_id_template using fields from the Modbus operation.

        Available substitution fields:
          {function}       - Modbus function name
          {unit_id}        - Unit ID as string
          {address}        - Register address as string
          {quantity}       - Quantity as string
          {register_type}  - Effective register type

        Raises:
            InvalidMappingError: If a template placeholder has no corresponding field.
        """
        captures: dict[str, str] = {
            "function": operation.function,
            "unit_id": str(operation.unit_id),
            "address": str(operation.address),
            "quantity": str(operation.quantity),
            "register_type": operation.effective_register_type(),
        }
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"undefined field {exc} for route '{route.name or route.function}'"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModbusMappingConfig:
        """
        Parse a Modbus mapping config from a plain dictionary (e.g. loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[ModbusRouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    ModbusRouteMapping(
                        function=raw.get("function", ""),
                        register_type=raw.get("register_type", ""),
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
