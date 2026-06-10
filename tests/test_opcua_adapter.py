"""
OPC UA adapter behavior tests — Phase 7.

Covers all five supported services, normalization output, protocol evidence
preservation, subject_hint forwarding, operation validation failures, and
fail-closed behavior.
"""

from __future__ import annotations

from typing import Any

from basis_adapters.models import AdapterContext, AdapterResult
from basis_adapters.opcua.adapter import OpcuaAdapter
from basis_adapters.opcua.mapping import (
    OpcuaMappingConfig,
    OpcuaOperation,
    OpcuaRouteMapping,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_route(**kwargs: object) -> OpcuaRouteMapping:
    defaults: dict[str, object] = {
        "service": "Read",
        "attribute_id": "Value",
        "action": "read",
        "resource_type": "opcua_node",
        "resource_id_template": "{node_id}:{attribute_id}",
        "name": "",
    }
    defaults.update(kwargs)
    return OpcuaRouteMapping(**defaults)  # type: ignore[arg-type]


def make_op(**kwargs: object) -> OpcuaOperation:
    defaults: dict[str, object] = {
        "service": "Read",
        "node_id": "ns=2;s=Building.AHU1.SupplyTemp",
        "attribute_id": "Value",
    }
    defaults.update(kwargs)
    return OpcuaOperation(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: OpcuaRouteMapping, adapter_id: str = "opcua-test") -> OpcuaAdapter:
    config = OpcuaMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id=adapter_id)
    return OpcuaAdapter(mapping=config, context=ctx)


def full_adapter() -> OpcuaAdapter:
    """Adapter with routes for all five services, mirroring the example mapping."""
    return make_adapter(
        make_route(name="read-node-value", service="Read", attribute_id="Value", action="read"),
        make_route(name="write-node-value", service="Write", attribute_id="Value", action="write"),
        make_route(
            name="call-method",
            service="Call",
            attribute_id="*",
            action="execute",
            resource_type="opcua_method",
            resource_id_template="{node_id}:method:{method_id}",
        ),
        make_route(
            name="subscribe-node-value",
            service="Subscribe",
            attribute_id="Value",
            action="subscribe",
        ),
        make_route(
            name="browse-node",
            service="Browse",
            attribute_id="*",
            action="browse",
            resource_id_template="{node_id}",
        ),
    )


# ---------------------------------------------------------------------------
# Service normalization — the spec examples
# ---------------------------------------------------------------------------


class TestServiceNormalization:
    def test_read_normalizes_to_read(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Read", node_id="ns=2;s=Building.AHU1.SupplyTemp")
        )
        assert result.success and result.request is not None
        req = result.request
        assert req.protocol == "opcua"
        assert req.action == "read"
        assert req.resource_type == "opcua_node"
        assert req.resource_id == "ns=2;s=Building.AHU1.SupplyTemp:Value"

    def test_write_normalizes_to_write(self) -> None:
        result = full_adapter().normalize(
            make_op(
                service="Write",
                node_id="ns=2;s=Building.AHU1.Setpoint",
                value_present=True,
            )
        )
        assert result.success and result.request is not None
        req = result.request
        assert req.protocol == "opcua"
        assert req.action == "write"
        assert req.resource_type == "opcua_node"
        assert req.resource_id == "ns=2;s=Building.AHU1.Setpoint:Value"

    def test_call_normalizes_to_execute(self) -> None:
        result = full_adapter().normalize(
            make_op(
                service="Call",
                node_id="ns=2;s=Building.AHU1",
                attribute_id=None,
                method_id="ns=2;s=Building.AHU1.Reset",
            )
        )
        assert result.success and result.request is not None
        req = result.request
        assert req.protocol == "opcua"
        assert req.action == "execute"
        assert req.resource_type == "opcua_method"
        assert req.resource_id == "ns=2;s=Building.AHU1:method:ns=2;s=Building.AHU1.Reset"

    def test_subscribe_normalizes_to_subscribe(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Subscribe", node_id="ns=2;s=Building.AHU1.SupplyTemp")
        )
        assert result.success and result.request is not None
        req = result.request
        assert req.action == "subscribe"
        assert req.resource_id == "ns=2;s=Building.AHU1.SupplyTemp:Value"

    def test_browse_normalizes_to_browse(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Browse", node_id="ns=2;s=Building.AHU1", attribute_id=None)
        )
        assert result.success and result.request is not None
        req = result.request
        assert req.action == "browse"
        assert req.resource_id == "ns=2;s=Building.AHU1"

    def test_default_actions_via_empty_route_action(self) -> None:
        adapter = make_adapter(
            make_route(service="*", attribute_id="*", action="", resource_id_template="{node_id}")
        )
        expectations = {
            "Read": "read",
            "Write": "write",
            "Subscribe": "subscribe",
            "Browse": "browse",
        }
        for service, expected in expectations.items():
            result = adapter.normalize(make_op(service=service))
            assert result.success and result.request is not None
            assert result.request.action == expected, service
        call_result = adapter.normalize(make_op(service="Call", method_id="ns=2;s=M"))
        assert call_result.success and call_result.request is not None
        assert call_result.request.action == "execute"


# ---------------------------------------------------------------------------
# Protocol evidence
# ---------------------------------------------------------------------------


class TestProtocolEvidence:
    def test_node_id_in_evidence(self) -> None:
        result = full_adapter().normalize(make_op())
        assert result.success and result.request is not None
        ev = result.request.protocol_evidence
        assert ev.protocol == "opcua"
        assert ev.method == "Read"
        assert ev.path == "ns=2;s=Building.AHU1.SupplyTemp"
        assert ev.metadata["node_id"] == "ns=2;s=Building.AHU1.SupplyTemp"

    def test_namespace_index_in_evidence_when_present(self) -> None:
        result = full_adapter().normalize(make_op(namespace_index=2))
        assert result.success and result.request is not None
        assert result.request.protocol_evidence.metadata["namespace_index"] == 2

    def test_namespace_index_none_in_evidence_when_absent(self) -> None:
        result = full_adapter().normalize(make_op())
        assert result.success and result.request is not None
        assert result.request.protocol_evidence.metadata["namespace_index"] is None

    def test_endpoint_url_in_evidence_when_present(self) -> None:
        result = full_adapter().normalize(
            make_op(endpoint_url="opc.tcp://building-server:4840/basis")
        )
        assert result.success and result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["endpoint_url"] == "opc.tcp://building-server:4840/basis"

    def test_session_id_in_evidence_when_present(self) -> None:
        result = full_adapter().normalize(make_op(session_id="session-7f3a"))
        assert result.success and result.request is not None
        assert result.request.protocol_evidence.metadata["session_id"] == "session-7f3a"

    def test_subscription_fields_in_evidence_when_present(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Subscribe", subscription_id=11, monitored_item_id=42)
        )
        assert result.success and result.request is not None
        meta = result.request.protocol_evidence.metadata
        assert meta["subscription_id"] == 11
        assert meta["monitored_item_id"] == 42

    def test_method_id_in_evidence_for_call(self) -> None:
        result = full_adapter().normalize(
            make_op(
                service="Call",
                node_id="ns=2;s=Building.AHU1",
                attribute_id=None,
                method_id="ns=2;s=Building.AHU1.Reset",
            )
        )
        assert result.success and result.request is not None
        assert (
            result.request.protocol_evidence.metadata["method_id"] == "ns=2;s=Building.AHU1.Reset"
        )

    def test_value_present_in_evidence(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Write", node_id="ns=2;s=N", value_present=True)
        )
        assert result.success and result.request is not None
        assert result.request.protocol_evidence.metadata["value_present"] is True

    def test_extra_metadata_preserved_in_evidence(self) -> None:
        result = full_adapter().normalize(make_op(metadata={"trace_id": "t-1"}))
        assert result.success and result.request is not None
        assert result.request.protocol_evidence.metadata["trace_id"] == "t-1"


# ---------------------------------------------------------------------------
# Subject hint
# ---------------------------------------------------------------------------


class TestSubjectHint:
    def test_subject_hint_none_when_absent(self) -> None:
        result = full_adapter().normalize(make_op())
        assert result.success and result.request is not None
        assert result.request.subject_hint is None

    def test_subject_hint_forwarded_when_present(self) -> None:
        result = full_adapter().normalize(
            make_op(metadata={"subject_hint": "operator@example.internal"})
        )
        assert result.success and result.request is not None
        assert result.request.subject_hint == "operator@example.internal"


# ---------------------------------------------------------------------------
# Failures — fail closed, never raise
# ---------------------------------------------------------------------------


class TestFailures:
    def test_unsupported_service_fails(self) -> None:
        result = full_adapter().normalize(make_op(service="HistoryRead"))
        assert result.success is False
        assert result.request is None
        assert result.error is not None and "Unsupported OPC UA service" in result.error

    def test_empty_service_fails(self) -> None:
        result = full_adapter().normalize(make_op(service=""))
        assert result.success is False

    def test_missing_node_id_fails(self) -> None:
        result = full_adapter().normalize(make_op(node_id=""))
        assert result.success is False
        assert result.error is not None and "node_id" in result.error

    def test_whitespace_node_id_fails(self) -> None:
        result = full_adapter().normalize(make_op(node_id="   "))
        assert result.success is False

    def test_non_string_node_id_fails(self) -> None:
        result = full_adapter().normalize(make_op(node_id=42))
        assert result.success is False
        assert result.error is not None and "node_id" in result.error

    def test_non_integer_namespace_index_fails(self) -> None:
        result = full_adapter().normalize(make_op(namespace_index="2"))
        assert result.success is False
        assert result.error is not None and "namespace_index" in result.error

    def test_boolean_namespace_index_fails(self) -> None:
        result = full_adapter().normalize(make_op(namespace_index=True))
        assert result.success is False

    def test_invalid_identifier_type_fails(self) -> None:
        result = full_adapter().normalize(make_op(identifier_type="symbolic"))
        assert result.success is False
        assert result.error is not None and "identifier_type" in result.error

    def test_call_missing_method_id_fails(self) -> None:
        result = full_adapter().normalize(
            make_op(service="Call", attribute_id=None, method_id=None)
        )
        assert result.success is False
        assert result.error is not None and "method_id" in result.error

    def test_call_empty_method_id_fails(self) -> None:
        result = full_adapter().normalize(make_op(service="Call", attribute_id=None, method_id=""))
        assert result.success is False

    def test_unmatched_operation_fails(self) -> None:
        adapter = make_adapter(make_route(service="Write"))
        result = adapter.normalize(make_op(service="Read"))
        assert result.success is False
        assert result.error is not None and "No route matched" in result.error

    def test_no_routes_fails(self) -> None:
        adapter = make_adapter()
        result = adapter.normalize(make_op())
        assert result.success is False

    def test_template_referencing_absent_field_fails_closed(self) -> None:
        adapter = make_adapter(
            make_route(attribute_id="*", resource_id_template="{node_id}:{method_id}")
        )
        result = adapter.normalize(make_op(method_id=None))
        assert result.success is False
        assert result.error is not None

    def test_normalize_never_raises(self) -> None:
        adapter = make_adapter()
        for op in (
            make_op(service="Bogus"),
            make_op(node_id=""),
            make_op(service="Call", method_id=None),
            make_op(),
        ):
            result = adapter.normalize(op)
            assert isinstance(result, AdapterResult)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_success_result_invariants(self) -> None:
        result = full_adapter().normalize(make_op())
        assert result.success is True
        assert result.request is not None
        assert result.error is None

    def test_failure_result_invariants(self) -> None:
        result = make_adapter().normalize(make_op())
        assert result.success is False
        assert result.request is None
        assert result.error is not None

    def test_adapter_id_exposed(self) -> None:
        adapter = make_adapter(make_route(), adapter_id="opcua-primary")
        assert adapter.adapter_id == "opcua-primary"

    def test_serialized_output_shape(self) -> None:
        result = full_adapter().normalize(make_op(namespace_index=2))
        assert result.success and result.request is not None
        d: dict[str, Any] = result.request.to_dict()
        assert d["protocol"] == "opcua"
        assert d["action"] == "read"
        assert d["resource_type"] == "opcua_node"
        assert d["resource_id"] == "ns=2;s=Building.AHU1.SupplyTemp:Value"
        assert d["protocol_evidence"]["method"] == "Read"
        assert d["subject_hint"] is None
