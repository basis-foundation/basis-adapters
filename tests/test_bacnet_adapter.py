"""
Tests for BacnetAdapter normalization behavior.

Covers the four BACnet service primitives, wildcard matching, exact matching,
property matching, template substitution, protocol evidence preservation, and
failure result shapes.
"""

from __future__ import annotations

from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import BacnetMappingConfig, BacnetOperation, BacnetRouteMapping
from basis_adapters.models import AdapterContext, AdapterResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_op(**kwargs: object) -> BacnetOperation:
    defaults: dict[str, object] = {
        "service": "ReadProperty",
        "object_type": "analogInput",
        "object_instance": 1,
        "property_identifier": "presentValue",
    }
    defaults.update(kwargs)
    return BacnetOperation(**defaults)  # type: ignore[arg-type]


def make_route(**kwargs: object) -> BacnetRouteMapping:
    defaults: dict[str, object] = {
        "service": "ReadProperty",
        "object_type": "analogInput",
        "property_identifier": "presentValue",
        "action": "read",
        "resource_type": "point",
        "resource_id_template": "{object_type}:{object_instance}",
    }
    defaults.update(kwargs)
    return BacnetRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: BacnetRouteMapping, adapter_id: str = "test") -> BacnetAdapter:
    config = BacnetMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return BacnetAdapter(mapping=config, context=ctx)


# ---------------------------------------------------------------------------
# Service primitive normalization
# ---------------------------------------------------------------------------


class TestServicePrimitives:
    def test_read_property_normalizes_to_read(self) -> None:
        route = make_route(service="ReadProperty", action="read")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(service="ReadProperty"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_write_property_normalizes_to_write(self) -> None:
        route = make_route(service="WriteProperty", action="write", object_type="*")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(service="WriteProperty"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "write"

    def test_subscribe_cov_normalizes_to_subscribe(self) -> None:
        route = make_route(
            service="SubscribeCOV",
            object_type="*",
            property_identifier="*",
            action="subscribe",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(service="SubscribeCOV", object_type="analogInput", property_identifier="*")
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "subscribe"

    def test_command_value_normalizes_to_control(self) -> None:
        route = make_route(
            service="CommandValue",
            object_type="*",
            property_identifier="*",
            action="control",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(
                service="CommandValue",
                object_type="binaryOutput",
                property_identifier="presentValue",
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "control"

    def test_default_action_from_service_map(self) -> None:
        # Route with empty action uses default service action map
        route = make_route(action="")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(service="ReadProperty"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_command_value_default_action_is_execute(self) -> None:
        # CommandValue's implicit (no explicit route action) default is
        # "execute", conforming to the canonical action vocabulary used by
        # DNP3/IEC 61850/Niagara command primitives. Explicit
        # `action="control"` remains a supported compatibility alias — see
        # test_command_value_normalizes_to_control above.
        route = make_route(
            service="CommandValue",
            object_type="*",
            property_identifier="*",
            action="",
        )
        adapter = make_adapter(route)
        result = adapter.normalize(
            make_op(
                service="CommandValue",
                object_type="binaryOutput",
                property_identifier="presentValue",
            )
        )
        assert result.success
        assert result.request is not None
        assert result.request.action == "execute"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_protocol_is_bacnet(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol == "bacnet"


# ---------------------------------------------------------------------------
# Resource type and ID
# ---------------------------------------------------------------------------


class TestResourceTypeAndId:
    def test_resource_type_from_route(self) -> None:
        route = make_route(resource_type="sensor")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.resource_type == "sensor"

    def test_resource_id_template_substitution(self) -> None:
        route = make_route(
            resource_id_template="{object_type}:{object_instance}:{property_identifier}"
        )
        adapter = make_adapter(route)
        op = make_op(
            object_type="analogInput", object_instance=7, property_identifier="presentValue"
        )
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "analogInput:7:presentValue"

    def test_resource_id_with_device_id(self) -> None:
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        adapter = make_adapter(route)
        op = make_op(device_id="device-42", object_instance=3)
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.resource_id == "device-42:3"

    def test_resource_id_device_id_none_fails(self) -> None:
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        adapter = make_adapter(route)
        op = make_op(device_id=None)
        result = adapter.normalize(op)
        assert not result.success
        assert result.request is None
        assert result.error is not None
        assert "device_id" in result.error


# ---------------------------------------------------------------------------
# Matching behavior
# ---------------------------------------------------------------------------


class TestMatchingBehavior:
    def test_wildcard_service_matches_any(self) -> None:
        route = make_route(service="*", object_type="*", property_identifier="*")
        adapter = make_adapter(route)
        for svc in ("ReadProperty", "WriteProperty", "SubscribeCOV", "CommandValue"):
            result = adapter.normalize(make_op(service=svc))
            assert result.success, f"Expected success for service={svc}"

    def test_exact_match_wins_over_wildcard(self) -> None:
        r_exact = make_route(name="exact", service="ReadProperty", action="read")
        r_wild = make_route(
            name="wild", service="*", object_type="*", property_identifier="*", action="control"
        )
        adapter = make_adapter(r_exact, r_wild)
        result = adapter.normalize(make_op(service="ReadProperty"))
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_first_match_wins(self) -> None:
        r1 = make_route(name="first", action="read")
        r2 = make_route(name="second", action="control")
        adapter = make_adapter(r1, r2)
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.action == "read"

    def test_unsupported_service_returns_failure(self) -> None:
        # No route matches a WriteProperty operation when only ReadProperty is configured
        route = make_route(service="ReadProperty")
        adapter = make_adapter(route)
        result = adapter.normalize(make_op(service="WriteProperty", object_type="binaryOutput"))
        assert not result.success
        assert result.request is None
        assert result.error is not None

    def test_no_routes_returns_failure(self) -> None:
        config = BacnetMappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="test")
        adapter = BacnetAdapter(mapping=config, context=ctx)
        result = adapter.normalize(make_op())
        assert not result.success
        assert result.error is not None


# ---------------------------------------------------------------------------
# Protocol evidence
# ---------------------------------------------------------------------------


class TestProtocolEvidence:
    def test_protocol_evidence_is_protocol_operation(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        evidence = result.request.protocol_evidence
        assert evidence.protocol == "bacnet"

    def test_protocol_evidence_method_is_service(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op(service="ReadProperty"))
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "ReadProperty"

    def test_protocol_evidence_path_encodes_object_identity(self) -> None:
        adapter = make_adapter(make_route())
        op = make_op(
            object_type="analogInput", object_instance=5, property_identifier="presentValue"
        )
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.path == "analogInput:5:presentValue"

    def test_device_id_in_evidence_metadata(self) -> None:
        route = make_route(resource_id_template="{object_type}:{object_instance}")
        adapter = make_adapter(route)
        op = make_op(device_id="dev-77")
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["device_id"] == "dev-77"

    def test_priority_in_evidence_metadata(self) -> None:
        adapter = make_adapter(make_route())
        op = make_op(priority=8)
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["priority"] == 8

    def test_value_present_in_evidence_metadata(self) -> None:
        adapter = make_adapter(make_route())
        op = make_op(value_present=True)
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["value_present"] is True

    def test_evidence_preserved_when_device_id_none(self) -> None:
        # A route that doesn't reference device_id — evidence still preserved
        route = make_route(resource_id_template="{object_type}:{object_instance}")
        adapter = make_adapter(route)
        op = make_op(device_id=None)
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["device_id"] is None


# ---------------------------------------------------------------------------
# Failure result shape
# ---------------------------------------------------------------------------


class TestFailureResultShape:
    def test_failure_has_no_request(self) -> None:
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert result.success is False
        assert result.request is None

    def test_failure_has_error_string(self) -> None:
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert isinstance(result.error, str)
        assert len(result.error) > 0

    def test_normalize_never_raises(self) -> None:
        # Even with an empty config, normalize() must not raise
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert isinstance(result, AdapterResult)


# ---------------------------------------------------------------------------
# Subject hint
# ---------------------------------------------------------------------------


class TestSubjectHint:
    def test_subject_hint_from_metadata(self) -> None:
        adapter = make_adapter(make_route())
        op = make_op(metadata={"subject_hint": "user:alice"})
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint == "user:alice"

    def test_no_subject_hint_is_none(self) -> None:
        adapter = make_adapter(make_route())
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.subject_hint is None


# ---------------------------------------------------------------------------
# Adapter identity
# ---------------------------------------------------------------------------


class TestAdapterIdentity:
    def test_adapter_id(self) -> None:
        config = BacnetMappingConfig(routes=[])
        ctx = AdapterContext(adapter_id="bacnet-primary")
        adapter = BacnetAdapter(mapping=config, context=ctx)
        assert adapter.adapter_id == "bacnet-primary"
