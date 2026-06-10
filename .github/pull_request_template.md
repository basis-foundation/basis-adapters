# Pull Request

## Summary

<!-- What does this PR change, and why? One concern per PR. -->

## Type of Change

<!-- e.g. feature, fix, docs, contract change (additive/breaking), test-only -->

## Quality Gates

- [ ] `python -m pytest` passes
- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `mypy src` passes

## Architectural Integrity

- [ ] Adapter contract preserved (fail-closed, evidence preserved verbatim, no
      authorization/enforcement logic; see `docs/contracts/adapter-contract.md`)
- [ ] No coupling to `basis-gateway` or `basis-core` added
- [ ] No live protocol/network communication added
- [ ] No protocol-specific top-level fields added to the normalized request shape

## Documentation and Contracts

- [ ] Docs updated if behavior, API, or contracts changed (or N/A)
- [ ] Examples and JSON Schemas updated if the surfaces they describe changed (or N/A)
- [ ] If the normalized request shape or a mapping schema changed, the change is
      flagged in this description as **additive** or **breaking** (or N/A)

## Notes for Reviewer

<!-- Anything that needs extra attention, trade-offs made, follow-ups deferred. -->
