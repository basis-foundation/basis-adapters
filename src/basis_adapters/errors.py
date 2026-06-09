"""
Exception hierarchy for basis-adapters.

Adapters fail closed: any mapping ambiguity or configuration error must raise
rather than silently producing an incorrect normalized request.
"""


class AdapterError(Exception):
    """
    Base exception for all adapter errors.

    Callers should catch this when they want to handle any adapter failure
    without distinguishing between subtypes.
    """


class InvalidMappingError(AdapterError):
    """
    Raised when a mapping configuration is structurally invalid.

    Examples:
    - A route entry is missing required fields.
    - An action value is not a recognized normalized verb.
    - A resource_type value is empty or malformed.

    Adapters must raise this during configuration validation, not at
    normalization time, so misconfigured adapters fail fast on startup.
    """


class UnknownRouteError(AdapterError):
    """
    Raised when an incoming operation does not match any configured route.

    Adapters fail closed: an operation with no matching route must not
    produce a normalized request. The caller is responsible for deciding
    how to handle the refusal (e.g. return 403, log, alert).
    """
