# Compatibility

Current compatibility expectations for `basis-adapters`. The library is pre-v1:
breaking changes are possible, but they must be deliberate, documented, and visible
in schemas, examples, and contract tests. This document defines what counts as
breaking.

## The Normalized Request Shape Is a Compatibility-Sensitive Contract

The serialized output of `NormalizedAuthorizationRequest.to_dict()` — defined by
`schemas/normalized-authorization-request.schema.json` and
`docs/contracts/normalization-contract.md` — is the handoff boundary between
adapters and the enforcement layer. Downstream consumers (basis-gateway, audit
pipelines) parse this shape. Treat any change to it as a contract change, not a
refactor.

## What Counts as Breaking

- **Removing a field** from the normalized request, protocol evidence, or any
  mapping config schema.
- **Renaming a field** (equivalent to remove + add).
- **Changing action or resource semantics** — e.g. changing what `action` values
  mean, altering how `resource_type`/`resource_id` are derived for an existing
  mapping, or changing the `action` enum in a non-additive way.
- **Weakening evidence preservation** — dropping, truncating, or mutating
  `protocol_evidence`. Evidence must remain a verbatim record of the original
  operation; audit depends on it.
- **Changing fail-closed semantics** — any change that lets a failed normalization
  produce a forwardable request.
- **Tightening mapping validation** such that previously valid configs are rejected
  (acceptable when fixing a correctness bug, but it is still breaking and must be
  called out).

## What Should Be Additive

- **Schema changes should be additive where possible**: new optional fields, new
  enum values where downstream tolerance is verified, new mapping capabilities that
  leave existing configs valid.
- New adapters, new examples, new docs.

## Rules for Protocol Adapters

- Protocol adapters must **not introduce protocol-specific top-level output
  fields**. Protocol detail belongs inside `protocol_evidence` (and
  `protocol_evidence.metadata`), never as siblings of `action`/`resource_type`/
  `resource_id`.
- **New protocols must conform to the canonical handoff shape.** A new adapter that
  needs a different output shape is a signal to evolve the shared contract
  deliberately, not to fork it per-protocol.
- All adapters participate in the cross-protocol contract tests
  (`tests/test_normalization_contract.py`); a new adapter is not complete until it
  does.

## Process

When a change touches the normalized request shape or a mapping schema:

1. Update the JSON Schema(s) under `schemas/`.
2. Update the examples under `examples/` (schema/example validation tests will
   catch drift).
3. Update `docs/contracts/normalization-contract.md` and, if API names change,
   `docs/public-api.md`.
4. Note the change explicitly in the PR description, flagged as additive or
   breaking.
