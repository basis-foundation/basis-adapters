# Release Readiness — v0.2.0 Checklist

This document defines what must be true before a `v0.2.0` release of
`basis-adapters` is tagged. It is a gate, not a promise of a date. It
supplements, and does not replace, the historical
[`docs/release-readiness.md`](release-readiness.md) `v0.1.0` record.

**Current status: v0.2.0 release candidate.** The initial nine-adapter
normalization surface (REST, BACnet, Modbus, OPC UA, MQTT, DNP3, IEC 61850,
KNX, Niagara) remains complete and unchanged from `v0.1.0`. This release adds
deterministic adapter-evidence material construction
(`basis_adapters.evidence`), RFC 8785 canonicalization, and SHA-256 digest
generation, under the architecture formally accepted in `basis-architecture`
[ADR-0007](https://github.com/basis-foundation/basis-architecture/blob/main/docs/adr/0007-adapter-evidence-construction.md)
(Stage 1). The version in `pyproject.toml` is `0.2.0`. This is a **minor
feature release**, not a patch: it is justified by additive public API and
the library's first declared runtime dependency.

> **Release readiness does not mean production OT readiness.** A `v0.2.0`
> release means the library's contracts, documentation, and quality gates
> are coherent and stable enough for early adopters to build against. It
> does not mean the library has been audited, hardened, or validated for
> deployment in live operational technology environments, and it does not
> mean the operation-aware handoff is complete. No production-readiness
> claims are made anywhere in this repository, and this release must not
> introduce any.

---

## Release Scope

### Accepted architecture dependency

`basis-architecture`'s ADR-0007 ("Adapter Evidence Construction") has been
formally **accepted**. `basis_adapters.evidence` implements only the
`basis-adapters`-owned portion of that accepted architecture (Stage 1):
constructing governed evidence material, canonicalizing it, and digesting it.
It does not implement Stage 2 (the operation-producer runtime) or any later
stage.

### Additive public API (`basis_adapters` package root)

New in `v0.2.0`, all additive — nothing existing was removed or renamed:

- Constants: `EVIDENCE_PROFILE`, `CANONICALIZATION_PROFILE`,
  `DIGEST_ALGORITHM_SHA256`
- Models: `AdapterEvidenceMaterial`, `EvidenceDigest`,
  `ConstructedAdapterEvidence`
- Function: `construct_adapter_evidence()`
- Exceptions: `EvidenceConstructionError` and its five subclasses
  (`UnsupportedEvidenceProtocolError`, `UnexpectedEvidenceFieldError`,
  `ProhibitedEvidenceValueError`, `EvidenceCanonicalizationError`,
  `UnsupportedDigestAlgorithmError`)
- Governed per-protocol metadata projections for all nine adapters, with a
  deliberate empty REST metadata projection in the `basis-adapter-evidence-v1`
  profile (documented limitation, not a defect — REST's own normalized
  output and `protocol_evidence` are unaffected)

See [`docs/public-api.md`](public-api.md#adapter-evidence-construction-basis_adaptersevidence)
for the full inventory, verified against `src/basis_adapters/__init__.py`,
`src/basis_adapters/evidence.py`, and `src/basis_adapters/errors.py` during
this release-preparation pass — documented and actual exports match exactly.
`_PROHIBITED_METADATA_KEYS` (internal, `src/basis_adapters/evidence.py`)
remains private and is not exported.

### Package version and runtime dependency

- `pyproject.toml` `version`: `0.1.0` → `0.2.0`.
- First runtime dependency ever declared by this package:
  `rfc8785==0.1.4` (pure-Python RFC 8785 / JSON Canonicalization Scheme
  implementation), used exclusively by `src/basis_adapters/evidence.py`.
  Through `v0.1.0` this package declared `dependencies = []`.

### Unchanged

Existing adapter normalization behavior and the serialized
`NormalizedAuthorizationRequest.to_dict()` / `ProtocolOperation.to_dict()`
output are byte-for-byte unchanged. No adapter, model, exception, mapping
schema, or action/resource semantic was altered.

---

## Compatibility Assessment

Classified **additive** relative to `v0.1.0`:

- No existing adapter removed.
- No existing public normalization model removed.
- No existing serialized normalized-request field changed.
- No action or resource semantics changed.
- No mapping schema changed.
- No protocol support removed.
- No existing normalization exception behavior changed.
- Callers that do not import `basis_adapters.evidence` observe zero
  behavior change.
- Installation now includes the new `rfc8785==0.1.4` runtime dependency —
  this is an **additive packaging change**, stated directly here rather than
  described as invisible: any environment that installs `basis-adapters`
  `v0.2.0` pulls in `rfc8785` even if the caller never imports
  `basis_adapters.evidence`.

See [`docs/compatibility.md`](compatibility.md) for the full, previously
established compatibility contract (unchanged by this release-preparation
pass).

---

## Explicit Non-Goals / Known Limitations

`v0.2.0` does **not** provide:

- an operation-producer runtime;
- producer authentication;
- `reference_id` minting;
- `adapter_source` selection;
- `redaction_classification` assignment;
- final `AdapterEvidenceReference` assembly;
- gateway submission;
- evidence persistence;
- later evidence retrieval or verification;
- protocol network communication;
- device command execution;
- execution-result evidence;
- proof of truthfulness, authenticity, authorization, or execution.

A digest proves correspondence with canonical bytes only — see
[Security and Trust Boundaries](#security-and-trust-boundaries) below.

---

## Quality Gates

- [x] All tests pass: `python -m pytest` — **1530 passed**
- [x] Lint passes: `ruff check .` — all checks passed
- [x] Format check passes: `ruff format --check .` — 99 files already
      formatted
- [x] Type check passes: `mypy src` (strict mode) — no issues found in 31
      source files
- [x] `git diff --check` — clean, no whitespace errors

## Build Gates

- [x] `python -m build` succeeds, producing:
  - `basis_adapters-0.2.0-py3-none-any.whl`
  - `basis_adapters-0.2.0.tar.gz`
- [x] Wheel contents verified: `basis_adapters/evidence.py`,
      `basis_adapters/errors.py`, and all nine adapter subpackages present;
      `basis_adapters-0.2.0.dist-info/METADATA` declares `Version: 0.2.0` and
      `Requires-Dist: rfc8785==0.1.4`; no test cache, `.venv`, `.git`
      metadata, build cache, or unintended artifact packaged.
- [x] Sdist contents verified: source tree, `pyproject.toml`, `README.md`,
      `LICENSE`, `docs/`, `examples/`, `schemas/`, `src/`, `tests/`; no
      generated artifacts.
- [x] Clean wheel install into a fresh virtual environment (outside this
      repository checkout) succeeds; `import basis_adapters` resolves to the
      installed site-packages path, not the source checkout.
- [x] Clean sdist install into a separate fresh virtual environment succeeds;
      `import basis_adapters` resolves to that environment's site-packages
      path.
- [x] Clean-install smoke test: `rfc8785` installed as a dependency; REST
      adapter normalization succeeds; `construct_adapter_evidence()` succeeds
      on the result; digest algorithm is `sha-256`; digest is 64 lowercase
      hexadecimal characters.

Exact wheel/sdist filenames, sizes, and SHA-256 checksums, and the final
package/working-tree state, are recorded in this release-preparation PR's
completion report rather than hard-coded here, consistent with the
established BASIS sibling-repository convention (see e.g. `basis-gateway`'s
`docs/releases/v0.2.0.md`).

> **Readiness-build hashes are not final release checksums.** Any wheel/sdist
> SHA-256 values recorded in this repository's release-preparation completion
> reports (this document included) were produced from a **pre-tag readiness
> build** — a candidate build used only to prove the build, packaging, and
> clean-install gates pass. They must **not** be copied into the final
> `v0.2.0` GitHub Release. Before publishing:
>
> - the wheel and source distribution must be **rebuilt from the exact
>   commit checked out at the pushed `v0.2.0` tag**, not from any
>   pre-tag working tree;
> - `SHA256SUMS.txt` must be generated fresh from those tagged-build
>   artifacts;
> - the wheel and source distribution uploaded to the GitHub Release must be
>   verified against that freshly generated `SHA256SUMS.txt`, not against any
>   readiness-build hash recorded earlier;
> - readiness-build hashes remain useful as evidence that the build gate was
>   exercised and passed during release preparation, but they carry no
>   authority over what is actually published.

---

## Documentation

- [x] README status section identifies `v0.2.0` as a release candidate (not
      as released) and accurately scopes what this release does and does not
      add.
- [x] `docs/public-api.md` matches the exported API surface exactly
      (verified against `__all__` in `src/basis_adapters/__init__.py`).
- [x] `docs/compatibility.md` already documented the evidence-construction
      addition and the new runtime dependency as additive; no further change
      needed.
- [x] Architecture and contract docs describe the code as it exists.
- [x] This document exists as the version-specific `v0.2.0` readiness record;
      the `v0.1.0` record (`docs/release-readiness.md`) is preserved
      unmodified as a historical record; README navigation links both.

## Examples and Schemas

- [x] All examples under `examples/` remain valid against their JSON Schemas
      (enforced by `tests/test_schema_examples.py`).
- [x] No JSON Schema was changed in this release.

## Repository Hygiene

- [x] No `__pycache__/`, `.venv/`, cache directories, `dist/`, or
      `*.egg-info` paths are committed or remain in the working tree.
- [x] No stray working files, editor droppings, or local tooling output in
      the tree.

## Claims Discipline

- [x] No claims of live protocol or network communication anywhere in docs
      or code comments — adapters remain pure normalization.
- [x] No production-readiness claims.
- [x] No claim that the operation-aware handoff is complete.
- [x] Version in `pyproject.toml` (`0.2.0`) matches the tag to be prepared.

## Architectural Integrity

- [x] The adapter contract (`docs/contracts/adapter-contract.md`) remains
      intact: fail-closed semantics, evidence preservation, no authorization
      logic.
- [x] All nine adapters still emit the canonical normalized request shape
      (enforced by `tests/test_normalization_contract.py`, unchanged).
- [x] No coupling to `basis-core` or `basis-gateway` has been introduced.
- [x] `basis_adapters.evidence` remains a pure, side-effect-free helper: no
      network, storage, or clock access.

---

## Security and Trust Boundaries

This release-preparation pass confirmed the documentation and release
artifacts do not imply:

- that a digest is a signature;
- that evidence is tamper-proof without authenticated storage or transport;
- that a producer is authenticated by constructing evidence;
- that authorization proves execution;
- that canonicalization validates truthfulness;
- that `subject_hint` is verified identity.

A digest proves only byte-correspondence with the declared canonical input
under the profile the material itself declares.

---

## Release Automation Assessment

No BASIS Python sibling repository (`basis-core`, `basis-gateway`,
`basis-identity`, `basis-schemas`) has a GitHub Actions release-publishing
workflow today. Release creation and artifact upload (wheel, sdist,
`SHA256SUMS.txt`, GitHub Release) is, across the ecosystem, a manual,
repository-approved step performed by the repository owner after a tag is
pushed and CI is confirmed green — see e.g. `basis-gateway`'s
`docs/release-checklist.md`. `basis-adapters`' existing
`.github/workflows/ci.yml` (pytest, `ruff check`, `ruff format --check`,
`mypy src`, single Python 3.10 job) already matches this standardized
pattern and was left unchanged by this release-preparation pass — see this
PR's completion report for the full assessment.

## v0.2.0 Release Candidate Checklist

The remaining steps between this release candidate and a published release
are entirely the **repository owner's**, performed manually after this PR
merges — none of them have occurred yet, and nothing in this repository
automates them (see Release Automation Assessment above):

1. [ ] Final pass of the quality and build gates on `main` at the merge
       commit.
2. [ ] Confirm `git ls-files` / `git status --short` shows no generated
       artifacts or stray files.
3. [ ] Confirm the version in `pyproject.toml` (`0.2.0`) matches the tag to
       be created.
4. [ ] Create and push the annotated tag: `git tag -a v0.2.0 -m "basis-adapters
       v0.2.0"` then `git push origin v0.2.0`.
5. [ ] Check out the exact tagged commit in a clean environment.
6. [ ] Build the wheel and source distribution from that tagged checkout
       (`python -m build`) — not from any pre-tag working tree.
7. [ ] Generate `SHA256SUMS.txt` covering the two tagged-build artifacts.
8. [ ] Create the GitHub Release from the tag with release notes.
9. [ ] Upload the wheel, source distribution, and `SHA256SUMS.txt` as release
       assets.
10. [ ] Download or otherwise inspect the uploaded release assets.
11. [ ] Verify the uploaded wheel and source distribution against
        `SHA256SUMS.txt` — a checksum mismatch means the uploaded asset was
        not built from the tagged commit and must not be published.

## Out of Scope for v0.2.0

Tagging `v0.2.0` explicitly does not require (and must not include): an
operation-producer runtime, producer authentication, final
`AdapterEvidenceReference` assembly, live protocol communication, a gateway
client, a proxy server, Docker/Kubernetes artifacts, PyPI publishing
automation, or a GitHub Actions release-publishing workflow (consistent with
the current BASIS ecosystem-wide convention — see Release Automation
Assessment above). Those remain separate decisions for later phases.
