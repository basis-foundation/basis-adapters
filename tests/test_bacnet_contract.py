"""
BACnet adapter contract preservation tests.

These tests verify that the BACnet adapter satisfies the adapter contract
defined in docs/contracts/adapter-contract.md:

1. AdapterResult shape is always correct (success/request/error invariants).
2. The adapter does not import basis_core.
3. The adapter does not import basis_gateway.
4. Protocol evidence is always preserved in successful results.
5. Failure means deny-by-default (no forward semantics).
6. normalize() never raises.
7. The adapter is isolated — no network, no gateway, no policy evaluation.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from basis_adapters.bacnet.adapter import BacnetAdapter
from basis_adapters.bacnet.mapping import BacnetMappingConfig, BacnetOperation, BacnetRouteMapping
from basis_adapters.models import (
    AdapterContext,
    AdapterResult,
    NormalizedAuthorizationRequest,
    ProtocolOperation,
)

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
        "service": "*",
        "object_type": "*",
        "property_identifier": "*",
        "action": "read",
        "resource_type": "point",
        "resource_id_template": "{object_type}:{object_instance}",
    }
    defaults.update(kwargs)
    return BacnetRouteMapping(**defaults)  # type: ignore[arg-type]


def make_adapter(*routes: BacnetRouteMapping) -> BacnetAdapter:
    config = BacnetMappingConfig(routes=list(routes))
    ctx = AdapterContext(adapter_id="contract-test")
    return BacnetAdapter(mapping=config, context=ctx)


def make_full_adapter() -> BacnetAdapter:
    return make_adapter(make_route())


# ---------------------------------------------------------------------------
# Contract 1: AdapterResult shape invariants
# ---------------------------------------------------------------------------


class TestAdapterResultShape:
    def test_success_result_has_request_and_no_error(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert result.success is True
        assert result.request is not None
        assert result.error is None

    def test_failure_result_has_error_and_no_request(self) -> None:
        # Empty config — no routes — forces failure
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert result.success is False
        assert result.error is not None
        assert result.request is None

    def test_result_is_adapter_result_instance(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert isinstance(result, AdapterResult)

    def test_success_request_is_normalized_authorization_request(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert result.success
        assert isinstance(result.request, NormalizedAuthorizationRequest)

    def test_result_is_frozen(self) -> None:
        import dataclasses

        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Contract 2 & 3: Adapter isolation — no basis_core, no basis_gateway
# ---------------------------------------------------------------------------


class TestAdapterIsolation:
    def test_bacnet_adapter_does_not_import_basis_core(self) -> None:
        import basis_adapters.bacnet.adapter as adapter_mod

        # Reload to get fresh module-level imports
        importlib.reload(adapter_mod)
        for name in sys.modules:
            assert not name.startswith("basis_core"), (
                f"basis_adapters.bacnet.adapter imported basis_core module: {name}"
            )

    def test_bacnet_mapping_does_not_import_basis_core(self) -> None:
        import basis_adapters.bacnet.mapping as mapping_mod

        importlib.reload(mapping_mod)
        for name in sys.modules:
            assert not name.startswith("basis_core"), (
                f"basis_adapters.bacnet.mapping imported basis_core module: {name}"
            )

    def test_bacnet_adapter_does_not_import_basis_gateway(self) -> None:
        import basis_adapters.bacnet.adapter as adapter_mod

        importlib.reload(adapter_mod)
        for name in sys.modules:
            assert not name.startswith("basis_gateway"), (
                f"basis_adapters.bacnet.adapter imported basis_gateway module: {name}"
            )

    def test_bacnet_mapping_does_not_import_basis_gateway(self) -> None:
        import basis_adapters.bacnet.mapping as mapping_mod

        importlib.reload(mapping_mod)
        for name in sys.modules:
            assert not name.startswith("basis_gateway"), (
                f"basis_adapters.bacnet.mapping imported basis_gateway module: {name}"
            )

    def test_no_network_imports(self) -> None:
        """
        The bacnet package must not import network libraries.
        socket, urllib, requests, httpx, aiohttp are all prohibited.
        """
        import basis_adapters.bacnet.adapter as adapter_mod
        import basis_adapters.bacnet.mapping as mapping_mod

        importlib.reload(adapter_mod)
        importlib.reload(mapping_mod)

        forbidden = ("socket", "urllib", "requests", "httpx", "aiohttp")
        for name in sys.modules:
            for prefix in forbidden:
                if name == prefix or name.startswith(prefix + "."):
                    # Only fail if the import came from our modules
                    # (socket is used by stdlib — we can't fail on its mere presence)
                    pass

        # The real check: verify neither module file imports forbidden names
        import ast
        import inspect

        for mod in (adapter_mod, mapping_mod):
            source = inspect.getsource(mod)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    else:
                        names = [node.module or ""]
                    for name in names:
                        for prefix in forbidden:
                            assert not (name == prefix or name.startswith(prefix + ".")), (
                                f"{mod.__name__} imports network library '{name}'"
                            )


# ---------------------------------------------------------------------------
# Contract 4: Protocol evidence always preserved
# ---------------------------------------------------------------------------


class TestProtocolEvidenceContract:
    def test_protocol_evidence_is_always_present_on_success(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence is not None

    def test_protocol_evidence_is_protocol_operation(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert result.success
        assert isinstance(result.request.protocol_evidence, ProtocolOperation)  # type: ignore[union-attr]

    def test_protocol_evidence_protocol_is_bacnet(self) -> None:
        adapter = make_full_adapter()
        result = adapter.normalize(make_op())
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.protocol == "bacnet"

    def test_protocol_evidence_preserves_original_service(self) -> None:
        op = make_op(service="WriteProperty")
        # Need a route that matches WriteProperty
        route = make_route(service="WriteProperty", action="write")
        config = BacnetMappingConfig(routes=[route])
        ctx = AdapterContext(adapter_id="test")
        adapter2 = BacnetAdapter(mapping=config, context=ctx)
        result = adapter2.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.method == "WriteProperty"

    def test_protocol_evidence_preserves_device_id(self) -> None:
        adapter = make_full_adapter()
        op = make_op(device_id="dev-99")
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        assert result.request.protocol_evidence.metadata["device_id"] == "dev-99"

    def test_protocol_evidence_is_not_modified(self) -> None:
        adapter = make_full_adapter()
        op = make_op(
            object_type="analogInput",
            object_instance=42,
            property_identifier="presentValue",
        )
        result = adapter.normalize(op)
        assert result.success
        assert result.request is not None
        evidence = result.request.protocol_evidence
        # Evidence path should encode original fields exactly
        assert evidence.path == "analogInput:42:presentValue"


# ---------------------------------------------------------------------------
# Contract 5: Failure means deny-by-default
# ---------------------------------------------------------------------------


class TestFailClosedContract:
    def test_no_route_match_produces_failure(self) -> None:
        # A route for ReadProperty won't match WriteProperty
        route = make_route(service="ReadProperty")
        config = BacnetMappingConfig(routes=[route])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op(service="WriteProperty", object_type="binaryOutput"))
        assert result.success is False

    def test_failure_result_has_error_message(self) -> None:
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert result.success is False
        assert isinstance(result.error, str)
        assert len(result.error) > 0

    def test_device_id_none_failure_is_deny(self) -> None:
        # Template requires device_id but it's None
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op(device_id=None))
        assert result.success is False
        # Caller must treat this as deny
        assert result.request is None


# ---------------------------------------------------------------------------
# Contract 6: normalize() never raises
# ---------------------------------------------------------------------------


class TestNormalizeNeverRaises:
    def test_empty_config_does_not_raise(self) -> None:
        config = BacnetMappingConfig(routes=[])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op())
        assert isinstance(result, AdapterResult)

    def test_unmatched_service_does_not_raise(self) -> None:
        route = make_route(service="ReadProperty")
        config = BacnetMappingConfig(routes=[route])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op(service="WriteProperty", object_type="binaryOutput"))
        assert isinstance(result, AdapterResult)
        assert result.success is False

    def test_device_id_none_does_not_raise(self) -> None:
        route = make_route(resource_id_template="{device_id}:{object_instance}")
        config = BacnetMappingConfig(routes=[route])
        adapter = BacnetAdapter(mapping=config, context=AdapterContext(adapter_id="test"))
        result = adapter.normalize(make_op(device_id=None))
        assert isinstance(result, AdapterResult)
        assert result.success is False
