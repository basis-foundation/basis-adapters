"""
IEC 61850 adapter mapping configuration.

An IEC 61850 mapping config is a list of Iec61850RouteMapping entries. Each
entry describes how a specific IEC 61850 operation (and optional logical node)
should be normalized into a BASIS authorization request.

IEC 61850 operations are matched by two fields:
  - operation     e.g. "READ", "WRITE", "SELECT", "DIRECT_OPERATE", "*"
  - logical_node  e.g. "CSWI1", "LLN0", "*"

The wildcard sentinel "*" matches any value for that field. Routes are
evaluated in order; the first match wins.

Resource ID templates may reference the following fields using {param} syntax:
  {operation}                     - IEC 61850 operation name
  {ied_name}                      - IED name (always present)
  {logical_device}                - Logical device name (if present)
  {logical_node}                  - Logical node name (if present)
  {data_object}                   - Data object name (if present)
  {data_attribute}                - Data attribute name (if present)
  {functional_constraint}         - Functional constraint, e.g. "ST" (if present)
  {dataset}                       - Dataset name (if present)
  {report_control_block}          - Report control block name (if present)
  {goose_control_block}           - GOOSE control block name (if present)
  {sampled_values_control_block}  - Sampled Values control block name (if present)

Fields marked "if present" are optional on the operation. A template that
references an optional field which is absent at normalization time fails
closed at render time.

Values, quality, timestamps, origin, cause of transmission, and control model
are deliberately NOT template fields: they are protocol evidence, never
resource identity. Resource IDs must stay deterministic and free of dynamic
protocol state.

Design invariants:
- Mapping validation is eager: InvalidMappingError is raised at parse time,
  not at normalization time.
- Unknown operations raise UnknownRouteError — adapters fail closed.
- Adapters do not evaluate policy; they only map operations to semantics.
- Duplicate named routes are rejected at config construction time.
- Template field references are validated against
  VALID_IEC61850_TEMPLATE_FIELDS.
- Control routes (SELECT, SELECT_WITH_VALUE, OPERATE, DIRECT_OPERATE, CANCEL)
  must reference {data_object} in their resource_id_template so a control
  command is never normalized without identifying the controlled data object.
- Control-block routes (ENABLE_REPORTING, ENABLE_GOOSE,
  ENABLE_SAMPLED_VALUES) must reference their control block template field so
  a subscription is never normalized without identifying the control block.
- IEC 61850 reuses the existing canonical action vocabulary (READ→read,
  WRITE→write, control operations→execute, enable-reporting/GOOSE/Sampled
  Values→subscribe). No new action verbs were added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from basis_adapters.errors import InvalidMappingError, UnknownRouteError
from basis_adapters.models import ProtocolOperation

# Recognized normalized action verbs — shared from REST mapping.
from basis_adapters.rest.mapping import VALID_ACTIONS

# IEC 61850 operations supported by this adapter (protocol-intent names).
VALID_IEC61850_OPERATIONS = frozenset(
    {
        "READ",
        "WRITE",
        "SELECT",
        "SELECT_WITH_VALUE",
        "OPERATE",
        "DIRECT_OPERATE",
        "CANCEL",
        "ENABLE_REPORTING",
        "ENABLE_GOOSE",
        "ENABLE_SAMPLED_VALUES",
    }
)

# IEC 61850 operations that represent control commands targeting a data object.
IEC61850_CONTROL_OPERATIONS = frozenset(
    {"SELECT", "SELECT_WITH_VALUE", "OPERATE", "DIRECT_OPERATE", "CANCEL"}
)

# IEC 61850 operations that represent subscription-style intents bound to a
# control block (report, GOOSE, or Sampled Values).
IEC61850_SUBSCRIPTION_OPERATIONS = frozenset(
    {"ENABLE_REPORTING", "ENABLE_GOOSE", "ENABLE_SAMPLED_VALUES"}
)

# IEC 61850 control models (ctlModel). The sbo_* models cover the two-step
# select-before-operate pattern; the direct_* models cover single-step direct
# control. status_only marks a point that cannot be controlled at all.
VALID_IEC61850_CONTROL_MODELS = frozenset(
    {
        "status_only",
        "direct_with_normal_security",
        "sbo_with_normal_security",
        "direct_with_enhanced_security",
        "sbo_with_enhanced_security",
    }
)

# Control model partitions used for operation/control-model consistency checks.
IEC61850_SBO_CONTROL_MODELS = frozenset({"sbo_with_normal_security", "sbo_with_enhanced_security"})
IEC61850_DIRECT_CONTROL_MODELS = frozenset(
    {"direct_with_normal_security", "direct_with_enhanced_security"}
)

# IEC 61850 functional constraints recognized by this adapter.
VALID_IEC61850_FUNCTIONAL_CONSTRAINTS = frozenset(
    {
        "ST",  # status information
        "MX",  # measurands (analogue values)
        "SP",  # setpoint
        "SV",  # substitution
        "CF",  # configuration
        "DC",  # description
        "SG",  # setting group
        "SE",  # setting group editable
        "SR",  # service response
        "OR",  # operate received
        "BL",  # blocking
        "EX",  # extended definition
        "CO",  # control
        "US",  # unbuffered reporting
        "MS",  # multicast sampled values control
        "RP",  # unbuffered report control
        "BR",  # buffered report control
        "LG",  # logging
        "GO",  # GOOSE control
        "GS",  # GSSE control
    }
)

# Normalized action verbs accepted for IEC 61850 routes. IEC 61850 reuses the
# shared action vocabulary plus "execute" (introduced additively in Phase 7
# for OPC UA method invocation) for control commands. No new verbs were added.
VALID_IEC61850_ACTIONS = VALID_ACTIONS | frozenset({"execute"})

# Default action mapping from IEC 61850 operation to normalized action verb.
# Control semantics prefer "execute" over "write": a SELECT/OPERATE on a
# breaker is a command to equipment, not a simple data write.
_DEFAULT_OPERATION_ACTION_MAP: dict[str, str] = {
    "READ": "read",
    "WRITE": "write",
    "SELECT": "execute",
    "SELECT_WITH_VALUE": "execute",
    "OPERATE": "execute",
    "DIRECT_OPERATE": "execute",
    "CANCEL": "execute",
    "ENABLE_REPORTING": "subscribe",
    "ENABLE_GOOSE": "subscribe",
    "ENABLE_SAMPLED_VALUES": "subscribe",
}

# Fields that may be referenced in resource_id_template. Values, quality,
# timestamps, origin, cause, and control model are deliberately excluded —
# they are evidence, never resource identity.
VALID_IEC61850_TEMPLATE_FIELDS = frozenset(
    {
        "operation",
        "ied_name",
        "logical_device",
        "logical_node",
        "data_object",
        "data_attribute",
        "functional_constraint",
        "dataset",
        "report_control_block",
        "goose_control_block",
        "sampled_values_control_block",
    }
)

# Subscription operations and the control block template field each must
# reference, so a subscription is never normalized without identifying its
# control block.
_CONTROL_BLOCK_TEMPLATE_FIELD: dict[str, str] = {
    "ENABLE_REPORTING": "report_control_block",
    "ENABLE_GOOSE": "goose_control_block",
    "ENABLE_SAMPLED_VALUES": "sampled_values_control_block",
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
    references fields from VALID_IEC61850_TEMPLATE_FIELDS.

    Raises:
        InvalidMappingError: If the template is empty, malformed, or references
            unknown fields (including the evidence-only fields value, quality,
            timestamp, origin, cause, and control_model).
    """
    if not template or not template.strip():
        raise InvalidMappingError(f"Route '{route_label}': resource_id_template must not be empty")
    if _MALFORMED_BRACE_RE.search(template):
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template contains malformed token in '{template}'"
        )
    refs = _extract_template_fields(template)
    unknown = refs - VALID_IEC61850_TEMPLATE_FIELDS
    if unknown:
        raise InvalidMappingError(
            f"Route '{route_label}': resource_id_template references unknown field(s) "
            f"{sorted(unknown)}. Valid fields: {sorted(VALID_IEC61850_TEMPLATE_FIELDS)}. "
            "Values, quality, timestamps, origin, cause, and control model are evidence "
            "only and may never appear in resource IDs."
        )


@dataclass(frozen=True)
class Iec61850Operation:
    """
    A raw IEC 61850 operation, as received before normalization.

    This models the intent of an IEC 61850 service request without
    representing actual wire traffic or a live client/server association.
    No MMS stack. No GOOSE subscriber. No Sampled Values processor. No
    packet parsing. This is deliberately a small model — it does not attempt
    to represent the full IEC 61850 standard.

    Attributes:
        operation:        IEC 61850 operation name: "READ", "WRITE", "SELECT",
                          "SELECT_WITH_VALUE", "OPERATE", "DIRECT_OPERATE",
                          "CANCEL", "ENABLE_REPORTING", "ENABLE_GOOSE", or
                          "ENABLE_SAMPLED_VALUES".
        ied_name:         Name of the target IED (intelligent electronic
                          device). Required — an IEC 61850 operation without
                          target identity fails closed.
        logical_device:   Optional logical device name, e.g. "PROT".
                          Required by hierarchy when logical_node is present.
        logical_node:     Optional logical node name, e.g. "CSWI1", "LLN0".
                          Required for read/write, control, and subscription
                          operations.
        data_object:      Optional data object name, e.g. "Pos". Requires
                          logical_node. Required for control operations.
        data_attribute:   Optional data attribute name, e.g. "stVal".
                          Requires data_object.
        functional_constraint: Optional functional constraint, e.g. "ST",
                          "MX", "CO". Preserved as evidence.
        dataset:          Optional dataset name. Preserved as evidence.
        report_control_block: Optional report control block name. Required
                          for ENABLE_REPORTING.
        goose_control_block: Optional GOOSE control block name. Required for
                          ENABLE_GOOSE.
        sampled_values_control_block: Optional Sampled Values control block
                          name. Required for ENABLE_SAMPLED_VALUES.
        control_model:    Optional control model (ctlModel):
                          "status_only", "direct_with_normal_security",
                          "sbo_with_normal_security",
                          "direct_with_enhanced_security", or
                          "sbo_with_enhanced_security". Must be consistent
                          with the operation (DIRECT_OPERATE may not claim an
                          sbo_* model; SELECT/OPERATE/CANCEL may not claim a
                          direct_* model; status_only points cannot be
                          controlled at all).
        origin:           Optional origin context (e.g. orCat/orIdent).
                          Evidence only — never treated as verified identity.
        cause:            Optional cause of transmission. Evidence only.
        quality:          Optional quality descriptor. Evidence only.
        timestamp:        Optional protocol timestamp. Evidence only.
        value:            Optional write/control value. Evidence only — never
                          rendered into resource IDs.
        metadata:         Additional protocol-specific fields.
    """

    operation: str
    ied_name: str | None = None
    logical_device: str | None = None
    logical_node: str | None = None
    data_object: str | None = None
    data_attribute: str | None = None
    functional_constraint: str | None = None
    dataset: str | None = None
    report_control_block: str | None = None
    goose_control_block: str | None = None
    sampled_values_control_block: str | None = None
    control_model: str | None = None
    origin: dict[str, Any] | None = None
    cause: str | None = None
    quality: str | None = None
    timestamp: str | None = None
    value: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_protocol_operation(self) -> ProtocolOperation:
        """
        Convert to a ProtocolOperation for use as protocol_evidence.

        The method is the IEC 61850 operation name and the path is a
        deterministic IED-rooted address: "ied:{ied_name}" extended with
        "/ld:{logical_device}", "/ln:{logical_node}", "/do:{data_object}",
        "/da:{data_attribute}", and the relevant control block segment
        ("/rcb:", "/gcb:", or "/svcb:") when those fields are present. All
        IEC 61850 fields are preserved in metadata for audit purposes.
        """
        path = f"ied:{self.ied_name}"
        if self.logical_device is not None:
            path += f"/ld:{self.logical_device}"
        if self.logical_node is not None:
            path += f"/ln:{self.logical_node}"
        if self.data_object is not None:
            path += f"/do:{self.data_object}"
        if self.data_attribute is not None:
            path += f"/da:{self.data_attribute}"
        if self.report_control_block is not None:
            path += f"/rcb:{self.report_control_block}"
        if self.goose_control_block is not None:
            path += f"/gcb:{self.goose_control_block}"
        if self.sampled_values_control_block is not None:
            path += f"/svcb:{self.sampled_values_control_block}"
        meta: dict[str, Any] = {
            "operation": self.operation,
            "ied_name": self.ied_name,
            "logical_device": self.logical_device,
            "logical_node": self.logical_node,
            "data_object": self.data_object,
            "data_attribute": self.data_attribute,
            "functional_constraint": self.functional_constraint,
            "dataset": self.dataset,
            "report_control_block": self.report_control_block,
            "goose_control_block": self.goose_control_block,
            "sampled_values_control_block": self.sampled_values_control_block,
            "control_model": self.control_model,
            "origin": self.origin,
            "cause": self.cause,
            "quality": self.quality,
            "timestamp": self.timestamp,
            "value": self.value,
        }
        meta.update(self.metadata)
        return ProtocolOperation(
            protocol="iec61850",
            method=self.operation,
            path=path,
            metadata=meta,
        )


@dataclass(frozen=True)
class Iec61850RouteMapping:
    """
    Maps an IEC 61850 (operation, logical_node) pair to normalized
    authorization semantics.

    Attributes:
        operation:            IEC 61850 operation to match ("READ", "WRITE",
            "SELECT", "SELECT_WITH_VALUE", "OPERATE", "DIRECT_OPERATE",
            "CANCEL", "ENABLE_REPORTING", "ENABLE_GOOSE",
            "ENABLE_SAMPLED_VALUES"), or "*" for any.
        logical_node:         Logical node name to match, or "*" for any
            (including an absent logical node). An exact logical_node route
            only matches operations that carry that logical node.
        action:               Normalized action verb (e.g. "read", "execute").
            If empty string, the default operation action map is consulted at
            normalization time (READ→read, WRITE→write, SELECT/
            SELECT_WITH_VALUE/OPERATE/DIRECT_OPERATE/CANCEL→execute,
            ENABLE_REPORTING/ENABLE_GOOSE/ENABLE_SAMPLED_VALUES→subscribe).
        resource_type:        Normalized resource category, e.g.
            "iec61850_data_object".
        resource_id_template: Template for the resource ID. May reference
            fields in VALID_IEC61850_TEMPLATE_FIELDS. Control routes must
            reference {data_object}; control-block routes must reference
            their control block field.
        name:                 Optional human-readable name (for diagnostics
            and duplicate-name detection).
    """

    operation: str
    logical_node: str
    action: str
    resource_type: str
    resource_id_template: str
    name: str = ""

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        label = self.name or f"{self.operation}:{self.logical_node}"

        # operation must be a valid IEC 61850 operation or wildcard
        if self.operation != "*" and self.operation not in VALID_IEC61850_OPERATIONS:
            raise InvalidMappingError(
                f"Route '{label}': unrecognized IEC 61850 operation '{self.operation}'. "
                f"Valid operations: {sorted(VALID_IEC61850_OPERATIONS)} or '*'"
            )

        # logical_node must be a non-empty string ("*" is the wildcard)
        if not self.logical_node or not self.logical_node.strip():
            raise InvalidMappingError(
                f"Route '{label}': logical_node must be a non-empty string or '*'"
            )

        # action must be valid if explicitly specified
        if self.action and self.action not in VALID_IEC61850_ACTIONS:
            raise InvalidMappingError(
                f"Route '{label}': invalid action '{self.action}'. "
                f"Valid actions: {sorted(VALID_IEC61850_ACTIONS)}"
            )

        # resource_type
        if not self.resource_type or not self.resource_type.strip():
            raise InvalidMappingError(f"Route '{label}': resource_type must not be empty")

        # resource_id_template
        _validate_resource_id_template(self.resource_id_template, label)

        refs = _extract_template_fields(self.resource_id_template)

        # Control routes must identify the data object being commanded.
        if self.operation in IEC61850_CONTROL_OPERATIONS and "data_object" not in refs:
            raise InvalidMappingError(
                f"Route '{label}': control routes ({sorted(IEC61850_CONTROL_OPERATIONS)}) "
                "must reference {data_object} in resource_id_template so the controlled "
                "data object is identified"
            )

        # Control-block routes must identify their control block.
        required_block = _CONTROL_BLOCK_TEMPLATE_FIELD.get(self.operation)
        if required_block is not None and required_block not in refs:
            raise InvalidMappingError(
                f"Route '{label}': {self.operation} routes must reference "
                f"{{{required_block}}} in resource_id_template so the control block "
                "is identified"
            )


@dataclass
class Iec61850MappingConfig:
    """
    A validated collection of Iec61850RouteMapping entries for the IEC 61850
    adapter.

    Routes are evaluated in order; the first match wins.

    Duplicate route names (non-empty) are rejected at construction time.
    """

    routes: list[Iec61850RouteMapping] = field(default_factory=list)

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

    def match(self, operation: Iec61850Operation) -> Iec61850RouteMapping:
        """
        Find the first matching route for the given IEC 61850 operation.

        Matching is performed on operation and logical_node. A route field
        value of "*" matches any operation value for that field, including an
        absent logical_node. An exact logical_node route only matches
        operations that carry that logical node.

        Returns:
            The first matching Iec61850RouteMapping.

        Raises:
            UnknownRouteError: If no route matches.
        """
        for route in self.routes:
            operation_match = route.operation == "*" or route.operation == operation.operation
            ln_match = route.logical_node == "*" or route.logical_node == operation.logical_node
            if operation_match and ln_match:
                return route
        raise UnknownRouteError(
            f"No route matched: operation={operation.operation!r} "
            f"logical_node={operation.logical_node!r}"
        )

    def resolve_action(self, route: Iec61850RouteMapping, operation: Iec61850Operation) -> str:
        """
        Determine the normalized action for the given route and operation.

        If the route has an explicit action, it is used. Otherwise, the
        default operation action map is consulted (READ→read, WRITE→write,
        SELECT/SELECT_WITH_VALUE/OPERATE/DIRECT_OPERATE/CANCEL→execute,
        ENABLE_REPORTING/ENABLE_GOOSE/ENABLE_SAMPLED_VALUES→subscribe).

        Raises:
            InvalidMappingError: If neither the route nor the default map has
                an entry for the operation.
        """
        if route.action:
            return route.action
        if operation.operation in _DEFAULT_OPERATION_ACTION_MAP:
            return _DEFAULT_OPERATION_ACTION_MAP[operation.operation]
        raise InvalidMappingError(
            f"No default action mapping for IEC 61850 operation '{operation.operation}' "
            f"and route '{route.name or route.operation}' has no explicit action."
        )

    def resolve_resource_id(self, route: Iec61850RouteMapping, operation: Iec61850Operation) -> str:
        """
        Render the resource_id_template using fields from the IEC 61850
        operation.

        Available substitution fields:
          {operation}                     - IEC 61850 operation name
          {ied_name}                      - IED name
          {logical_device}                - Logical device (if present)
          {logical_node}                  - Logical node (if present)
          {data_object}                   - Data object (if present)
          {data_attribute}                - Data attribute (if present)
          {functional_constraint}         - Functional constraint (if present)
          {dataset}                       - Dataset (if present)
          {report_control_block}          - Report control block (if present)
          {goose_control_block}           - GOOSE control block (if present)
          {sampled_values_control_block}  - SV control block (if present)

        Optional fields are only available when present on the operation. A
        template that references an absent optional field fails closed.

        Values, quality, timestamps, origin, and cause are never available as
        template fields — they remain protocol evidence only.

        Raises:
            InvalidMappingError: If a template placeholder has no
                corresponding field available on the operation.
        """
        captures: dict[str, str] = {"operation": operation.operation}
        if operation.ied_name is not None:
            captures["ied_name"] = operation.ied_name
        if operation.logical_device is not None:
            captures["logical_device"] = operation.logical_device
        if operation.logical_node is not None:
            captures["logical_node"] = operation.logical_node
        if operation.data_object is not None:
            captures["data_object"] = operation.data_object
        if operation.data_attribute is not None:
            captures["data_attribute"] = operation.data_attribute
        if operation.functional_constraint is not None:
            captures["functional_constraint"] = operation.functional_constraint
        if operation.dataset is not None:
            captures["dataset"] = operation.dataset
        if operation.report_control_block is not None:
            captures["report_control_block"] = operation.report_control_block
        if operation.goose_control_block is not None:
            captures["goose_control_block"] = operation.goose_control_block
        if operation.sampled_values_control_block is not None:
            captures["sampled_values_control_block"] = operation.sampled_values_control_block
        try:
            return route.resource_id_template.format_map(captures)
        except KeyError as exc:
            raise InvalidMappingError(
                f"resource_id_template '{route.resource_id_template}' references "
                f"field {exc} which is not available on the operation "
                f"(route '{route.name or route.operation}')"
            ) from exc

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Iec61850MappingConfig:
        """
        Parse an IEC 61850 mapping config from a plain dictionary (e.g.
        loaded from JSON).

        Raises:
            InvalidMappingError: If any route is structurally invalid.
        """
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            raise InvalidMappingError("Mapping config 'routes' must be a list")

        routes: list[Iec61850RouteMapping] = []
        for i, raw in enumerate(raw_routes):
            if not isinstance(raw, dict):
                raise InvalidMappingError(f"Route at index {i} must be a dict")
            try:
                routes.append(
                    Iec61850RouteMapping(
                        operation=raw.get("operation", ""),
                        logical_node=raw.get("logical_node", "*"),
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
