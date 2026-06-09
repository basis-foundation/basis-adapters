"""
Tests for core basis-adapters models.

Verifies that the domain models are immutable, correctly structured, and
that AdapterResult factory methods produce the expected shapes.
"""

import dataclasses

import pytest

from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)

# ---------------------------------------------------------------------------
# ProtocolOperation
# ---------------------------------------------------------------------------


class TestProtocolOperation:
    def test_basic_construction(self) -> None:
        op = ProtocolOperation(protocol="rest", method="GET", path="/devices/ahu-1")
        assert op.protocol == "rest"
        assert op.method == "GET"
        assert op.path == "/devices/ahu-1"
        assert op.metadata == {}

    def test_with_metadata(self) -> None:
        op = ProtocolOperation(
            protocol="rest",
            method="POST",
            path="/points",
            metadata={"subject_hint": "user@example.com"},
        )
        assert op.metadata["subject_hint"] == "user@example.com"

    def test_is_frozen(self) -> None:
        op = ProtocolOperation(protocol="rest", method="GET", path="/")
        with pytest.raises(dataclasses.FrozenInstanceError):
            op.method = "POST"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NormalizedAuthorizationRequest
# ---------------------------------------------------------------------------


class TestNormalizedAuthorizationRequest:
    def _make_op(self) -> ProtocolOperation:
        return ProtocolOperation(
            protocol="rest", method="GET", path="/devices/ahu-1/points/supply-temp"
        )

    def test_basic_construction(self) -> None:
        op = self._make_op()
        req = NormalizedAuthorizationRequest(
            action="read",
            resource_type="point",
            resource_id="ahu-1:supply-temp",
            protocol="rest",
            protocol_evidence=op,
        )
        assert req.action == "read"
        assert req.resource_type == "point"
        assert req.resource_id == "ahu-1:supply-temp"
        assert req.protocol == "rest"
        assert req.protocol_evidence is op
        assert req.subject_hint is None

    def test_with_subject_hint(self) -> None:
        op = self._make_op()
        req = NormalizedAuthorizationRequest(
            action="read",
            resource_type="point",
            resource_id="ahu-1:supply-temp",
            protocol="rest",
            protocol_evidence=op,
            subject_hint="user@example.com",
        )
        assert req.subject_hint == "user@example.com"

    def test_is_frozen(self) -> None:
        op = self._make_op()
        req = NormalizedAuthorizationRequest(
            action="read",
            resource_type="point",
            resource_id="ahu-1:supply-temp",
            protocol="rest",
            protocol_evidence=op,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            req.action = "write"  # type: ignore[misc]

    def test_protocol_evidence_is_preserved(self) -> None:
        """The original operation is always attached so the request is auditable."""
        op = self._make_op()
        req = NormalizedAuthorizationRequest(
            action="read",
            resource_type="point",
            resource_id="ahu-1:supply-temp",
            protocol="rest",
            protocol_evidence=op,
        )
        assert req.protocol_evidence.method == "GET"
        assert req.protocol_evidence.path == "/devices/ahu-1/points/supply-temp"


# ---------------------------------------------------------------------------
# AdapterContext
# ---------------------------------------------------------------------------


class TestAdapterContext:
    def test_basic_construction(self) -> None:
        ctx = AdapterContext(adapter_id="rest-primary")
        assert ctx.adapter_id == "rest-primary"
        assert ctx.config == {}

    def test_with_config(self) -> None:
        ctx = AdapterContext(adapter_id="rest-primary", config={"timeout": 5})
        assert ctx.config["timeout"] == 5

    def test_is_frozen(self) -> None:
        ctx = AdapterContext(adapter_id="rest-primary")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.adapter_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# AdapterResult
# ---------------------------------------------------------------------------


class TestAdapterResult:
    def _make_request(self) -> NormalizedAuthorizationRequest:
        op = ProtocolOperation(protocol="rest", method="GET", path="/devices/ahu-1")
        return NormalizedAuthorizationRequest(
            action="read",
            resource_type="device",
            resource_id="ahu-1",
            protocol="rest",
            protocol_evidence=op,
        )

    def test_ok_result(self) -> None:
        req = self._make_request()
        result = AdapterResult.ok(req)
        assert result.success is True
        assert result.request is req
        assert result.error is None

    def test_fail_result(self) -> None:
        result = AdapterResult.fail("No route matched: GET /unknown")
        assert result.success is False
        assert result.request is None
        assert result.error == "No route matched: GET /unknown"

    def test_ok_and_fail_are_mutually_exclusive(self) -> None:
        req = self._make_request()
        ok = AdapterResult.ok(req)
        fail = AdapterResult.fail("err")
        assert ok.success != fail.success
        assert ok.error is None
        assert fail.request is None
