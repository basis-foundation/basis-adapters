"""
REST adapter: normalizes HTTP-like operations into BASIS authorization requests.

The adapter accepts a ProtocolOperation representing an HTTP request, applies
the configured RestMappingConfig, and produces a NormalizedAuthorizationRequest
suitable for submission to basis-gateway.

Design invariants:
- No network calls. No gateway calls. No basis-core calls.
- Fail closed: unknown routes and invalid mappings raise rather than guess.
- Protocol evidence is always attached to the normalized request.
- The adapter does not evaluate whether the request should be allowed.
"""

from __future__ import annotations

from basis_adapters.errors import AdapterError
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)
from basis_adapters.rest.mapping import RestMappingConfig

PROTOCOL = "rest"


class RestAdapter:
    """
    Normalizes REST (HTTP) operations into BASIS authorization requests.

    Usage::

        config = RestMappingConfig.from_dict(mapping_dict)
        ctx = AdapterContext(adapter_id="rest-primary")
        adapter = RestAdapter(mapping=config, context=ctx)

        operation = ProtocolOperation(
            protocol="rest",
            method="GET",
            path="/devices/ahu-1/points/supply-temp",
        )
        result = adapter.normalize(operation)
        if result.success:
            # submit result.request to basis-gateway
            ...

    The adapter does not raise on normalization failure; it returns
    AdapterResult.fail(...) so callers can decide how to handle the outcome.
    """

    def __init__(self, mapping: RestMappingConfig, context: AdapterContext) -> None:
        self._mapping = mapping
        self._context = context

    @property
    def adapter_id(self) -> str:
        return self._context.adapter_id

    def normalize(self, operation: ProtocolOperation) -> AdapterResult:
        """
        Normalize a ProtocolOperation into an AdapterResult.

        On success: returns AdapterResult.ok(NormalizedAuthorizationRequest).
        On failure: returns AdapterResult.fail(error_message).

        This method never raises — errors are captured into AdapterResult.
        """
        try:
            return self._normalize(operation)
        except AdapterError as exc:
            return AdapterResult.fail(str(exc))

    def _normalize(self, operation: ProtocolOperation) -> AdapterResult:
        route, captures = self._mapping.match(operation.method, operation.path)

        action = self._mapping.resolve_action(route, operation.method)
        resource_id = self._mapping.resolve_resource_id(route, captures)

        request = NormalizedAuthorizationRequest(
            action=action,
            resource_type=route.resource_type,
            resource_id=resource_id,
            protocol=PROTOCOL,
            protocol_evidence=operation,
            subject_hint=operation.metadata.get("subject_hint"),
        )
        return AdapterResult.ok(request)
