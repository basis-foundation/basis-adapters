# Operation-Aware Handoff Alignment Plan

## Status

Planning. This document is discovery and assessment only. It does not change
any Python model, any JSON Schema, or any runtime behavior in this
repository. It assesses whether `basis-adapters`' current, released `v0.1.0`
public surface can support a future, not-yet-implemented operation-producer
runtime in constructing a valid `adapter-evidence-reference` and a complete
operation-aware handoff, per
[`basis-architecture`'s `docs/architecture/operation-producer-and-execution-boundary.md`](https://github.com/basis-foundation/basis-architecture/blob/main/docs/architecture/operation-producer-and-execution-boundary.md)
(§13, Stage 2), which names this exact document as the next decision gate in
the ecosystem's implementation sequence.

## Governing Question

> Can the current `basis-adapters` public surface produce the normalized
> operation facts and safe adapter-evidence reference needed by a future
> operation-producer runtime without breaking the released `v0.1.0`
> contract?

## Summary Answer

Mixed, by field. The bulk of the operation-aware handoff — action, resource
type, local resource identifier, protocol label, and protocol evidence — is
already sufficient today, unchanged, because `basis-adapters`' existing
normalized-request shape was designed for exactly this handoff. The four
fields required by the published `adapter-evidence-reference` contract
(`reference_id`, `evidence_digest`, `adapter_source`,
`redaction_classification`) are **not** currently produced by
`basis-adapters` at all, and — per field, assessed in §5 — three of the four
are not something this repository should manufacture without further
architecture direction; the fourth (`adapter_source`) is already
constructible by a producer runtime from fields `basis-adapters` already
exposes, with no library change required. No blocking defect exists in the
released `v0.1.0` contract. A small number of additive, optional fields are
plausible future work, gated on decisions this document does not have the
authority to make (see §12), but none of them are required to unblock the
next architecture stage.

## Relationship to Other Documents

This plan directly answers the decision gate named in
`basis-architecture`'s `docs/architecture/operation-producer-and-execution-boundary.md`
§13, Stage 2 ("`basis-adapters` operation-aware handoff alignment plan...
Decision gate: does `basis-adapters` need any additive surface at all, or is
its current public API already sufficient for a producer runtime to consume?").
It also relies on, without restating, `docs/contracts/normalization-contract.md`,
`docs/contracts/adapter-contract.md`, `docs/public-api.md`, and
`docs/compatibility.md` in this repository, and on the published
`adapter-evidence-reference`, `operation-aware-decision-request`,
`redaction-classification`, and `contract-metadata` contracts in
`basis-schemas`.

---

## 1. Purpose and Current State

`basis-adapters` `v0.1.0` is a pure, protocol-normalization library. It:

- supports nine protocol/platform normalizers (REST, BACnet, Modbus, OPC UA,
  MQTT, DNP3, IEC 61850, KNX, and Niagara), each normalization-complete;
- converts protocol-native operations into a single shared normalized
  request shape, `NormalizedAuthorizationRequest`, carrying `protocol`,
  `action`, `resource_type`, `resource_id`, `protocol_evidence`, and an
  optional `subject_hint`;
- fails closed on invalid or unmappable input — a normalization failure
  (`AdapterResult.success is False`) must not be forwarded as though it were
  an authorization decision;
- does not authenticate callers — it has no identity-provider integration,
  no token verification, and no credential handling of any kind;
- does not establish producer trust — it has no concept of a "trusted
  operation producer," no gateway client, and no authentication mechanism
  toward one;
- does not invoke `basis-gateway` — normalization is an in-process, pure
  transformation with no network I/O;
- does not invoke `basis-core` — it has zero runtime dependencies
  (`pyproject.toml` declares `dependencies = []`) and no import of any
  `basis_core` module;
- does not authorize — it produces the input to an authorization decision,
  never the decision itself;
- does not execute OT operations — "no sockets, no packet parsing, no
  protocol stacks, no live protocol communication... adapters are libraries,
  not daemons" (README.md);
- does not produce execution-result evidence — no component in this
  repository observes or records whether a downstream device accepted,
  rejected, or ever received an operation.

This plan assesses the handoff between this normalization library and the
future, not-yet-implemented, authenticated operation-producer runtime that
`basis-architecture`'s operation-producer-and-execution-boundary document
names but does not implement, select a repository for, or authorize any
component to build. Per that document (§10, §11), `basis-adapters` does not
automatically expand into that runtime, a daemon, or a device controller
merely because the ecosystem has now named the role; this plan does not
propose that it should.

---

## 2. Existing Public Surface Inventory

Inventory of the public models and serialized fields in
`src/basis_adapters/models.py`, `src/basis_adapters/errors.py`, and each
protocol package, relevant to a future handoff. "Public/stable" reflects
`docs/public-api.md` and `docs/compatibility.md` as they exist today.

| Existing field or model | Current owner | Current meaning | Public/stable? | Relevant future use |
| - | - | - | - | - |
| `ProtocolOperation` (`protocol`, `method`, `path`, `metadata`) | `basis-adapters` | Raw, un-normalized wire-level operation, preserved verbatim | Public, stable | Evidence material a future `evidence_digest` might be computed over |
| `AdapterContext` (`adapter_id`, `config`) | `basis-adapters`, deployment-configured | Execution context supplied to an adapter at normalization time; `adapter_id` is a freeform, deployment-chosen label (e.g. `"rest-primary"`) | Public, stable | Candidate contributor to a future `adapter_source` value, alongside `protocol` |
| `NormalizedAuthorizationRequest.action` | `basis-adapters` | Normalized, bare action verb | Public, stable | Feeds `operation-aware-decision-request.action` after gateway composition (unchanged by this plan) |
| `NormalizedAuthorizationRequest.resource_type` | `basis-adapters` | Local resource category | Public, stable | Feeds `operation-aware-decision-request.resource_type` |
| `NormalizedAuthorizationRequest.resource_id` | `basis-adapters` | Local, untyped resource identifier | Public, stable | Feeds `operation-aware-decision-request.resource` after gateway composition into `{resource_type}:{resource_id}` |
| `NormalizedAuthorizationRequest.protocol` | `basis-adapters` | Originating protocol identifier, open lowercase label | Public, stable | Maps directly onto `adapter-evidence-reference.protocol` and `operation-aware-decision-request.protocol_context.protocol` — same open-label shape |
| `NormalizedAuthorizationRequest.protocol_evidence` | `basis-adapters` | Verbatim `ProtocolOperation`, mandatory, never stripped | Public, stable | Candidate evidence material for a future `evidence_digest`; candidate source for `operation-aware-decision-request.protocol_context.operation` |
| `NormalizedAuthorizationRequest.subject_hint` | `basis-adapters` | Unverified identity hint forwarded from the protocol layer | Public, stable | See §6 — must never become verified identity |
| `AdapterResult` (`request`, `error`, `success`) | `basis-adapters` | Outcome of a normalization attempt | Public, stable | Fail-closed gate a producer runtime must respect before constructing any evidence reference |
| `AdapterError` / `InvalidMappingError` / `UnknownRouteError` | `basis-adapters` | Exception hierarchy | Public, stable | Not part of the handoff payload; internal to normalization failure handling |
| Mapping-config classes (`RestMappingConfig`, `BacnetMappingConfig`, ...) | `basis-adapters` | Per-protocol route/template configuration | Public, stable | No `mapping_version`-shaped field exists today (see §5) |
| Package version (`pyproject.toml` `version = "0.1.0"`) | `basis-adapters` | Whole-library release version | Public (release metadata) | Not the same concept as `adapter-evidence-reference.normalization_version` (see §5) |

**Fields the published `adapter-evidence-reference` and
`operation-aware-decision-request` contracts name that do not exist
anywhere in `basis-adapters` today:** `reference_id`, `evidence_digest`,
`adapter_source`, `redaction_classification`, `normalization_version`,
`mapping_version`, `request_id`, `correlation_id`. None of these are
adapter-owned fields, adapter-internal fields, or fields planned in any
existing `basis-adapters` roadmap, implementation-phase, or design document.
This is stated here as an observed fact about the current source tree
(confirmed by searching `src/`, `docs/`, and `schemas/` for each name), not
as a conclusion that any of them belong in `basis-adapters` (see §5, §10).

There is no shared abstract base adapter class (no `base.py`); each of the
nine adapters (`RestAdapter`, `BacnetAdapter`, `ModbusAdapter`,
`OpcuaAdapter`, `MqttAdapter`, `Dnp3Adapter`, `Iec61850Adapter`,
`KnxAdapter`, `NiagaraAdapter`) is an independent class conforming to the
same behavioral contract (`docs/contracts/adapter-contract.md`) by
convention and cross-protocol contract tests, not by shared inheritance.
Any future additive surface touching "every adapter" therefore touches nine
independent classes, not one shared base.

---

## 3. Operation-Aware Field Mapping

Mapping from current adapter output to the published
`operation-aware-decision-request` categories (`operation-aware-decision-request.yaml`,
published in `basis-schemas` v0.2.0 — contract schema version 0.1.0). Per
that contract, request assembly is explicitly `basis-gateway`'s job, not `basis-adapters`'; this
table records what `basis-adapters` can *supply toward* each category, not a
claim that `basis-adapters` assembles the request itself.

| Operation-aware category | Current adapter source | Sufficient today? | Correct owner | Gap or concern |
| - | - | - | - | - |
| `action` | `NormalizedAuthorizationRequest.action` (bare verb) | Sufficient as an input to gateway composition; unchanged by this plan | `basis-adapters` produces; `basis-gateway` composes into canonical `{verb}:{domain}` form | None — existing, stable, exercised contract (`ecosystem-contract-inventory.md` §3.3) |
| Resource type | `NormalizedAuthorizationRequest.resource_type` | Sufficient | `basis-adapters` produces; `basis-gateway` composes | None |
| Local resource identifier | `NormalizedAuthorizationRequest.resource_id` | Sufficient | `basis-adapters` produces; `basis-gateway` composes into canonical `resource` | None |
| Canonical resource identifier | Not produced by `basis-adapters` | Not applicable — by design | `basis-gateway` | `basis-adapters` intentionally does not perform kernel-specific identifier composition (`basis-adapters.md`, "Relationship to `basis-gateway`") |
| Protocol | `NormalizedAuthorizationRequest.protocol` | Sufficient — open lowercase label, same shape `adapter-evidence-reference.protocol` and `protocol_context.protocol` expect | `basis-adapters` | None |
| Protocol operation | `protocol_evidence.method` / `protocol_evidence.path` / `protocol_evidence.metadata` | Sufficient as evidence; not itself the `protocol_context.operation` field, but a producer runtime can derive that field's value from `protocol_evidence.method` | Producer runtime asserts `protocol_context`, sourced from adapter evidence (per `operation-producer-and-execution-boundary.md` §4's field-ownership table) | None blocking; the mapping from `protocol_evidence.method` to `protocol_context.operation` is a producer-runtime responsibility this plan does not need to formalize in `basis-adapters` |
| Operation intent | Not observed — `basis-adapters` has no concept of `read_only` / `state_changing` / `control_affecting` classification | Not available from `basis-adapters` | Producer runtime asserts, if it has a governed basis for the classification | `operation_intent` is a producer-only field per the gateway's trust model (§3 of the boundary document); it is correctly absent from adapter output, not a gap |
| Device context | Not observed in the canonical shape; some protocols carry device-identifying fields only inside `protocol_evidence.metadata` (e.g. BACnet's `device_id`, DNP3's `outstation_id`, KNX's `device`) | Not applicable at the canonical-field level; available only as protocol evidence | Producer runtime asserts `device`, if known from deployment configuration or protocol evidence | Not a defect: `device_shape` is a producer-only field; `basis-adapters` correctly leaves it to protocol evidence rather than promoting protocol-specific fields into the canonical shape |
| Location context | Not observed anywhere in `basis-adapters` | Not available | Producer runtime asserts, from deployment configuration | Not a gap in `basis-adapters` — location is deployment topology, not protocol evidence |
| Safety context | Not observed anywhere in `basis-adapters` | Not available | Producer runtime asserts, only if a governed upstream safety source exists | Not a gap — `basis-adapters` has, correctly, no safety-system integration |
| Environment context | Not observed anywhere in `basis-adapters` | Not available | Producer runtime asserts | Not a gap |
| Risk context | Not observed anywhere in `basis-adapters` | Not available | Producer runtime asserts, if a deployment defines a risk source | Not a gap |
| Adapter evidence reference | Not produced — no `reference_id`, `evidence_digest`, `adapter_source`, or `redaction_classification` exists in `basis-adapters` | Not sufficient today (assessed field-by-field in §5) | Producer runtime constructs, from adapter output, per the boundary document's field-ownership table | See §5 |
| Request ID | Not produced — `basis-adapters` has no `request_id`-shaped field anywhere | Not applicable to `basis-adapters` | Operation-producer runtime (or, absent one, the caller); `basis-gateway` falls back to its own `correlation_id` when absent | See §7 |
| Correlation ID | Not produced — `basis-adapters` has no `correlation_id`-shaped field anywhere | Not applicable to `basis-adapters` | `basis-gateway` generates unconditionally per request; ignores caller-supplied values | See §7 |

Four distinct states recur throughout this table and are kept deliberately
distinct, per this plan's instructions: **not observed** (the field's
concept does not appear anywhere in the current source, e.g. operation
intent), **not available** (the adapter has no way to obtain the value even
in principle, e.g. safety context), **not applicable** (the field belongs
structurally to a different component by design, e.g. canonical resource
composition), and **unknown** (a value that a producer or consumer could
determine but that this plan cannot determine on `basis-adapters`' behalf,
e.g. whether a given deployment's mapping configuration should carry a
version). No cell above substitutes an invented default, an empty object, or
a placeholder value for any of these four states.

---

## 4. Ownership Matrix

Per fact, using `operation-producer-and-execution-boundary.md` (§2, §7, §10)
as authority. `basis-adapters` is assigned only the facts its own,
currently-released contract already assigns it.

| Fact | Adapter library | Producer runtime | Gateway | Executor |
| - | - | - | - | - |
| Protocol parsing | **Owns** | — | — | — |
| Normalized verb | **Owns** | — | — | — |
| Resource type | **Owns** | — | — | — |
| Local resource ID | **Owns** | — | — | — |
| Canonical action composition | — | — | **Owns** | — |
| Canonical resource composition | — | — | **Owns** | — |
| Protocol evidence | **Owns** (produces and preserves verbatim) | Carries forward, does not reinterpret | — | — |
| Adapter evidence reference | Supplies raw material only (`protocol_evidence`, `protocol`, `adapter_id`) | **Constructs** (per boundary doc §4) | Accepts, from a classified trusted producer only | — |
| Producer workload identity | — | Holds the credential | **Authenticates** | — |
| Producer trust classification | — | — | **Owns** (`OPERATION_PRODUCER_SUBJECT_IDS`) | — |
| Initiating subject identity | Contributes only an unverified `subject_hint` | May carry forward | Resolves/verifies via `basis-identity`, when applicable | — |
| Gateway request ID/correlation | — | May supply `request_id` | **Owns** (`correlation_id`, unconditionally generated) | — |
| Authorization decision | — | — | Invokes; enforces the result | — (`basis-core` decides, not listed as a column here per the boundary document's own role list) |
| Dispatch attempt | — | — | — | **Owns** (not yet implemented anywhere) |
| Execution result | — | — | — | Execution-evidence producer (not yet implemented; not this repository) |

`basis-adapters` is not assigned producer authentication, trust
classification, gateway request admission, authorization, or execution
anywhere in this matrix, consistent with §10 and §11 of the boundary
document ("`basis-adapters` does not automatically expand into a daemon,
gateway, or device controller merely because the ecosystem now names an
operation-producer runtime").

---

## 5. Adapter Evidence Reference Assessment

Each field of the published `adapter-evidence-reference` contract
(published in `basis-schemas` v0.2.0 — contract schema version 0.1.0),
assessed against what `basis-adapters` exposes today. None of the four
required fields (`reference_id`, `evidence_digest`,
`adapter_source`, `redaction_classification`) currently exist in
`basis-adapters`' source tree.

### `reference_id` (required)

No existing adapter-owned identifier can serve this role today. `basis-adapters`
mints no identifier of any kind during normalization — not a UUID, not a
counter, not a hash-derived value. Two consequences follow directly from the
existing contract:

- `NormalizedAuthorizationRequest.to_dict()` is documented as deterministic
  — "same input always produces identical output." Minting a random or
  time-derived `reference_id` inside `normalize()` would introduce
  nondeterminism into a call currently defined as a pure, side-effect-free
  transformation (`docs/contracts/adapter-contract.md`: "Normalization is a
  pure, in-process transformation. No network calls" — and by extension, no
  hidden randomness or clock reads that would need to be described
  alongside that determinism claim). Whether that determinism claim is
  about `to_dict()` serialization specifically, or about `normalize()`
  behavior more broadly, is not resolved anywhere in the current
  documentation.
- `operation-producer-and-execution-boundary.md` §4 itself leaves this
  open: the producer runtime "constructs an `AdapterEvidenceReference` (or
  accepts one the adapter library helps construct)" — phrasing that
  explicitly does not decide whether minting happens in `basis-adapters` or
  downstream.

**Conclusion:** whether `reference_id` should be created by `basis-adapters`
or by the producer runtime is left unresolved by the current architecture.
This plan does not resolve it and does not choose a UUID format or
generation algorithm. Absent a decision, a producer runtime can mint
`reference_id` itself today without requiring any `basis-adapters` change —
this is available now, without an additive PR, and is the lower-risk default
until an architecture decision states otherwise.

### `evidence_digest` (required)

`protocol_evidence` (a serialized `ProtocolOperation`: `protocol`, `method`,
`path`, `metadata`) is the only plausible evidence material `basis-adapters`
currently produces. `ProtocolOperation.to_dict()` is deterministic in the
sense that the same `ProtocolOperation` object always serializes to the same
dict structure. However:

- Canonicalization is not defined. `metadata` is an open `dict[str, Any]`
  populated differently by each of the nine adapters and, within a given
  adapter, by whatever caller constructed the originating `ProtocolOperation`.
  Nothing in `basis-adapters` guarantees key ordering, whitespace, numeric
  formatting, or encoding stability sufficient to make repeated JSON
  serialization of an equivalent `ProtocolOperation` byte-for-byte
  reproducible — the property a hash digest requires.
- No hashing behavior exists anywhere in `basis-adapters` today (confirmed:
  no `hashlib` usage, no digest computation, no canonicalization helper in
  `src/`).
- `adapter-evidence-reference.yaml` is explicit that it "does not implement,
  canonicalize, or verify hashing; evidence producers (`basis-adapters`) own
  deterministic digest generation" — naming `basis-adapters` as the intended
  owner in prose, while defining no canonicalization rule itself.

**Conclusion:** `basis-adapters` produces material that *could* become
evidence (`protocol_evidence`), but canonicalization is undefined anywhere
in the ecosystem today, and this plan does not invent one. Building a digest
builder now would mean inventing canonicalization rules without authority —
explicitly out of scope. This is an **architecture decision needed** before
any digest-builder implementation, in either `basis-adapters` or a producer
runtime.

### `adapter_source` (required)

`basis-adapters` exposes two candidate contributors: `NormalizedAuthorizationRequest.protocol`
(e.g. `"modbus"`) and `AdapterContext.adapter_id` (a deployment-chosen
freeform label, e.g. `"rest-primary"`). The schema's own examples use the
form `basis-adapters:modbus`, but `adapter-evidence-reference.yaml` does not
mandate that shape — it requires only a non-empty, opaque string, "protocol-neutral
at the field level."

**Conclusion:** a producer runtime can construct a valid `adapter_source`
value today, from fields `basis-adapters` already exposes (`protocol`, and
optionally `AdapterContext.adapter_id`), with **no `basis-adapters` change
required**. The only gap is that `basis-adapters` itself does not document
or govern the `basis-adapters:{protocol}` naming convention used in the
`basis-schemas` examples — this repository has not adopted that convention
anywhere in its own docs. That is a documentation-only observation, not a
surface gap.

### `protocol`

Already sufficient. `NormalizedAuthorizationRequest.protocol` is a stable,
public field using the same open, lowercase-label shape (`^[a-z][a-z0-9_-]*$`)
that `adapter-evidence-reference.protocol` and
`operation-aware-decision-request.protocol_context.protocol` both expect.
All nine current protocol values (`rest`, `bacnet`, `modbus`, `opcua`,
`mqtt`, `dnp3`, `iec61850`, `knx`, `niagara`) already conform to this
pattern. No change needed.

### `normalization_version`

`basis-adapters` does not expose a normalization-contract version distinct
from the whole-library package version (`pyproject.toml` `version = "0.1.0"`).
`docs/contracts/normalization-contract.md` carries a `## Status` marker
("Stable — Phase 14") that names an implementation phase, not a version
identifier, and is not exposed anywhere as a runtime-readable value. The
normalized-request JSON Schema itself
(`schemas/normalized-authorization-request.schema.json`) has no `version`
property. **Conclusion:** no such value exists today; this is a genuine gap,
not an oversight in this assessment. Whether the whole-library package
version is an acceptable stand-in, or whether a distinct normalization-contract
version constant is warranted, is left open (see §12).

### `mapping_version`

Searched every `*-mapping.schema.json` and every `src/basis_adapters/*/mapping.py`
for a version-shaped field: none exists. (MQTT's `protocol_version` is the
MQTT wire-protocol version, e.g. `"5.0"` — a semantically different concept
from a mapping-configuration version, and specific to one protocol.) No
mapping configuration in any of the nine adapters carries a stable
identifier or version today. **Conclusion:** a genuine gap. A producer
runtime cannot construct a meaningful `mapping_version` value from current
`basis-adapters` output because the underlying concept does not exist yet.

### `redaction_classification` (required)

`basis-adapters` has no sensitivity classification of any kind — no
concept of "safe to expose," "reference only," or similar anywhere in its
source or docs. This is consistent with the architecture's own ownership
model: `redaction-classification` is a `basis-architecture`-governed
vocabulary, and nothing in `basis-adapters`' current contract assigns it the
job of classifying its own evidence's sensitivity. **Conclusion:** this
belongs to the producer runtime or a future evidence component, not
`basis-adapters`, and this plan does not introduce redaction logic here, per
its explicit non-goals.

### `request_id` and `correlation_id`

Neither exists anywhere in `basis-adapters` today. Today:

- `request_id` is optional in `operation-aware-decision-request` and, per
  the boundary document's correlation model (§6), is generated by "the
  operation-producer runtime (or, absent one, the caller)" — never by
  `basis-adapters`.
- `correlation_id` is generated unconditionally by `basis-gateway`'s
  `CorrelationMiddleware`; caller-supplied values are explicitly ignored by
  documented gateway policy.
- `basis-adapters`' `normalize()` call signature has no parameter through
  which a producer runtime could inject either identifier today, and
  `AdapterContext` (`adapter_id`, `config`) does not currently carry either.

**Conclusion:** genuinely ambiguous, and this plan documents rather than
resolves it, per its instructions. A producer runtime can construct both
identifiers entirely outside `basis-adapters` (it already receives the
`AdapterResult` before submitting to the gateway, so it can generate or
carry a `request_id`/`correlation_id` at that point without needing
`basis-adapters` to plumb either through `normalize()`). Whether a future
`basis-adapters` release should accept an optional pass-through identifier
at normalization time — so that an identifier minted before normalization
(for example, one already present in `ProtocolOperation.metadata` for some
protocols) can survive into the evidence reference without the producer
runtime re-deriving it — is left open.

### Field-by-field conclusion summary

| Field | Conclusion |
| - | - |
| `reference_id` | Architecture decision needed (minting owner unresolved); constructible by producer runtime today without a `basis-adapters` change |
| `evidence_digest` | Architecture decision needed (canonicalization undefined); not implementable responsibly in this PR |
| `adapter_source` | Current public surface is sufficient — no `basis-adapters` change required |
| `protocol` | Current public surface is sufficient |
| `normalization_version` | Small additive public extension is needed, if this value is wanted at all — currently absent |
| `mapping_version` | Small additive public extension is needed, if this value is wanted at all — currently absent |
| `redaction_classification` | Correct owner is outside `basis-adapters` (producer runtime / evidence component) |
| `request_id` / `correlation_id` | Architecture decision needed (pass-through mechanism, if any); constructible entirely outside `basis-adapters` today |

A mixed conclusion by field, as anticipated by this plan's own instructions.

---

## 6. Subject Hint and Identity Boundary

`NormalizedAuthorizationRequest.subject_hint` (optional, `string | null`) is
the only identity-adjacent field `basis-adapters` produces. Its documented
meaning today, unchanged by this plan:

- it is an **unverified hint** forwarded from protocol metadata (for
  example, an HTTP header value, an MQTT `client_id`, or a Niagara
  `niagara_user`/`niagara_role` value carried in evidence);
- it **must not** establish producer trust — nothing in `basis-adapters`
  claims otherwise today, and this plan does not propose that it should;
- it **must not** silently become the authenticated subject — the
  normalization contract states plainly that "the enforcement boundary is
  responsible for resolving and verifying identity before submitting a
  decision request to `basis-core`";
- the producer runtime and `basis-gateway` own the authenticated handoff —
  `subject_hint` plays no role in producer-trust classification
  (`OPERATION_PRODUCER_SUBJECT_IDS` is keyed on the gateway's own
  authenticated caller, never on adapter-supplied hints);
- **initiating-subject identity and producer workload identity are
  distinct**, per `operation-producer-and-execution-boundary.md` §3's
  six-fact trust table: `subject_hint` is, at best, a weak signal toward
  "human or initiating subject identity" — it is never evidence of
  "authenticated workload identity," which belongs entirely to whatever
  authenticates the producer runtime toward the gateway (not yet selected;
  see `operation-producer-and-execution-boundary.md` §3, §13 Stage 4).

Individual adapters go further than the shared contract in places: the
normalization-contract documents, per protocol, several fields that are
"evidence only — never treated as verified identity" (BACnet has none
explicitly called out; OPC UA's `session_id`, MQTT's `client_id`, DNP3's
`master_id`, IEC 61850's `origin`, KNX's `individual_address`, and
Niagara's `niagara_user`/`niagara_role`, the last of which is explicitly
documented as "never copied into `subject_hint`, and never role-mapped").
This existing, per-protocol discipline already enforces the boundary this
plan is asked to confirm.

**Recommendation:** none. The current field, its documentation, and its
non-authoritative status are already consistent with the architecture's
trust rules. No deprecation, retention, or relabeling is warranted by
anything found in this assessment.

---

## 7. Correlation and Identifier Flow

| Identifier | Generator | Owner | Mutability | Exists today? | May be propagated? | May another component overwrite it? |
| - | - | - | - | - | - | - |
| Protocol-native operation identifier (where one exists, e.g. DNP3/IEC 61850 control-block or transaction identifiers) | Field device / protocol source | Carried as evidence inside `protocol_evidence.metadata`, protocol-specific | Immutable once captured | Yes, for protocols that expose one (e.g. Modbus `transaction_id`) — absent for protocols that have none | Yes, verbatim, inside `protocol_evidence` | No — `basis-adapters` never strips or replaces `protocol_evidence` |
| Adapter normalization identifier | Not generated by `basis-adapters` today | N/A | N/A | No | N/A | N/A |
| Producer-runtime request identifier | Operation-producer runtime (not yet implemented) | Producer runtime | Set once at construction | No — the runtime does not exist yet | Intended to become `operation-aware-decision-request.request_id` | `basis-gateway` never overwrites a caller-supplied `request_id`; falls back to its own `correlation_id` only when absent |
| Gateway request identifier | `basis-gateway` (`OperationAwareEvaluateRequest.request_id`, caller-suppliable) | Gateway accepts caller value or defaults it | Set once per request | Yes, in `basis-gateway` (out of scope for this repository) | N/A | N/A |
| Gateway correlation identifier | `basis-gateway`'s `CorrelationMiddleware`, unconditionally | `basis-gateway` | Generated fresh per request | Yes, in `basis-gateway` | N/A | Caller-supplied `X-Correlation-ID` headers are explicitly ignored by documented gateway policy — "would allow external parties to influence the audit trail" |
| Kernel trace identifier | `basis-core` | `basis-core` | Generated per evaluation call | Yes, in `basis-core`/`basis-gateway` | Passed through unmodified into `GatewayAuditEvent` | Not applicable to `basis-adapters` |
| Adapter evidence reference identifier (`reference_id`) | Unresolved (see §5) | Unresolved | Unresolved | No | Intended | Unresolved |
| Future execution evidence identifier | Execution-evidence producer (not yet implemented) | Execution-evidence producer | Unresolved | No | Intended | Unresolved |

`basis-adapters` today generates **no identifier of any kind**. This is not
a defect: nothing in its released contract requires one, and the components
that do generate correlation-relevant identifiers (`basis-gateway`'s
`request_id`/`correlation_id`, `basis-core`'s `trace_id`) are explicitly
gateway- and kernel-owned. Per
`operation-producer-and-execution-boundary.md` §6: "correlation creates
deterministic linkage; it does not by itself prove authenticity or
causation" — a future `basis-adapters` change that adds an identifier must
not be mistaken for a step toward proving either.

---

## 8. Representative Handoff Scenarios

### Scenario A — BACnet state-changing operation (`WriteProperty` against a setpoint)

```text
BACnet WriteProperty (object AV-4, property presentValue, value 72)
    → BacnetAdapter.normalize()
    → NormalizedAuthorizationRequest{
         protocol="bacnet", action="write", resource_type="point",
         resource_id="<rendered from template>",
         protocol_evidence={protocol, method="WriteProperty",
           path="{object_type}:{object_instance}:{property_identifier}",
           metadata={service, object_type, object_instance,
             property_identifier, device_id, priority, value_present}},
         subject_hint=None (BACnet has no documented subject_hint source)
       }
    → future producer-runtime submission
    → gateway composition and authorization
```

**Facts available at normalization time:** action, resource type, local
resource ID, protocol, full protocol evidence including `device_id` and
`priority` (both evidence-only, never verified identity per the
normalization contract).

**Facts unavailable to the adapter:** operation intent, location, device
class (BACnet's `device_id` is a raw evidence field, not the
`device_shape.device_class` category), safety/environment/risk context,
producer or subject authentication.

**Facts the producer runtime must add:** `operation_intent` (plausibly
`state_changing`, but only the producer runtime — or a governed upstream
source — can assert this), `adapter_evidence_reference` construction
(blocked on §5's open `reference_id`/`evidence_digest` questions),
`protocol_context.operation` (derivable from `protocol_evidence.method`).

**Facts the gateway must establish:** producer trust classification,
canonical action/resource composition, provenance labeling
(`trusted_producer_asserted`).

**Evidence that can be safely referenced:** the full `protocol_evidence`
object, once a digest-canonicalization rule exists (§5).

**Execution facts that do not yet exist:** whether the device accepted the
write, whether `presentValue` actually changed — no component in the
ecosystem today observes or records this.

### Scenario B — Modbus state-changing operation (semantically sparse lower bound)

```text
Modbus Function Code 06 (register 40012, value 72)
    → ModbusAdapter.normalize()
    → NormalizedAuthorizationRequest{
         protocol="modbus", action="write", resource_type="register" (example),
         resource_id="<rendered from unit:address template>",
         protocol_evidence={protocol, method="WriteSingleRegister" (example),
           path="unit:{unit_id}:addr:{address}",
           metadata={function, unit_id, address, quantity, value_present,
             register_type, source_address, transaction_id}},
         subject_hint=None
       }
```

Modbus carries no object model, no device identifier field beyond
`unit_id`/`source_address`, and no priority or origin concept. This is
deliberately the lower bound: what can be preserved is exactly what
Modbus's wire format contains — a function code, a unit/address pair, and,
where present, a `transaction_id`. `basis-adapters` does not invent
meaning the protocol does not provide (no synthesized "device class," no
synthesized "safety mode"); the normalization contract's own text is
explicit that "protocols do not converge... outputs converge," not that
missing protocol semantics should be backfilled. A future
`adapter_evidence_reference` for a Modbus operation would be no less valid
than one for BACnet — its `evidence_digest` would simply cover sparser
material — but the canonicalization question from §5 applies identically.

### Scenario C — Read-only / discovery operation (OPC UA `Browse`)

```text
OPC UA Browse (parent node ns=2;s=Building.AHU1)
    → OpcuaAdapter.normalize()
    → NormalizedAuthorizationRequest{
         protocol="opcua", action="browse", resource_type="node" (example),
         resource_id="<rendered from node_id template>",
         protocol_evidence={protocol, method="Browse",
           path="<node_id>",
           metadata={service, node_id, browse_name, parent_node_id,
             session_id, endpoint_url, ...}},
         subject_hint=None (session_id/endpoint_url are evidence only,
           documented as "never treated as verified identity")
       }
```

This confirms the handoff is not designed only around write/control
behavior: `action="browse"` carries no operation-intent ambiguity in the
way a write does (browsing is read-only by construction, though
`basis-adapters` does not itself assert `operation_intent="read_only"` —
that remains a producer-runtime or policy-time classification, not an
adapter-level one). `session_id` and `endpoint_url` are explicitly
documented as evidence-only, reinforcing §6's identity-boundary finding
independent of protocol.

No scenario fixture is added to this repository's test suite by this plan;
`basis-adapters` does not currently require documentation examples to carry
executable validation beyond the existing `examples/handoff/*.example.json`
files, which already cover these protocols' normalized-request shape.

---

## 9. Compatibility Assessment

Every possible future change identified by this assessment, classified.
None of these are committed by this plan; all are candidates gated on the
decisions named in §5 and §12.

| Candidate future change | Classification |
| - | - |
| Add `docs/operation-aware-handoff-alignment-plan.md` (this document) | Documentation-only |
| Add a link to this plan from `README.md` | Documentation-only |
| Add a `normalization_version` constant/field, if a decision authorizes one | Additive optional model field |
| Add a `mapping_version` field to mapping-config classes, if a decision authorizes one | Additive optional model field |
| Add an `adapter_source`-construction helper in a producer-facing utility, if wanted | Additive helper or builder |
| Add an evidence-reference construction helper, once canonicalization and `reference_id`-minting ownership are decided | Additive helper or builder — blocked on an architecture decision first |
| Add a deterministic evidence-material canonicalization rule | Architecture decision required before any implementation |
| Decide who mints `reference_id` | Architecture decision required |
| Add `redaction_classification` assignment logic | Explicitly out of scope for `basis-adapters` per architecture (correct owner is elsewhere) |
| Add a pass-through `request_id`/`correlation_id` parameter to `normalize()` | Additive optional model field / additive new parameter — open question, not yet justified by a real consumer (§5) |
| Contract-conformance tests validating `basis-adapters` output against the published `adapter-evidence-reference` schema fields it *does* supply (`protocol`) | Additive conformance test |
| Any change to `action`, `resource_type`, `resource_id`, or `protocol_evidence` semantics | Not proposed by this plan; would be breaking per `docs/compatibility.md` and requires a proven defect, not found here |

No breaking serialization change, no breaking public API change, and no
schema change are proposed by this plan. Whether any of the additive
candidates above justify a future `v0.2.0` is not assumed here — it depends
on which, if any, of §5's open architecture decisions the ecosystem resolves
in `basis-adapters`' favor, and how many resulting fields accumulate. A
single small additive field (for example, `normalization_version` alone)
would not by itself require a minor version bump under this repository's own
pre-v1 compatibility policy (`docs/compatibility.md`), which treats new
optional fields as additive rather than breaking.

---

## 10. Repository-Boundary Findings

| Gap | Correct owner |
| - | - |
| No authenticated producer-runtime role exists anywhere in the ecosystem | operation-producer runtime (role named, not yet assigned a repository — `operation-producer-and-execution-boundary.md` §11) |
| No mechanism authenticates a producer runtime to `basis-gateway` beyond the subject-ID allowlist | `basis-gateway` (§13 Stage 4 of the boundary document) |
| No `evidence_digest` canonicalization rule exists | `basis-architecture` decision, implemented by whichever component ultimately mints digests (unresolved — could be `basis-adapters`, the producer runtime, or a future dedicated evidence component) |
| No `reference_id`-minting owner is decided | `basis-architecture` decision (§5 of this plan; §4 and §11 of the boundary document) |
| No sensitivity/redaction classification of adapter evidence exists | operation-producer runtime or a future evidence component — not `basis-adapters` |
| No execution-evidence contract or producer exists | future protocol executor / execution-evidence producer — not `basis-adapters`, not this plan (`basis-schemas` publication gated on a reference implementation, per the boundary document §13 Stage 6) |
| No `basis-identity` production of `identity-evidence-reference` exists | `basis-identity` (confirmed absent in that repository's source during this review; a pre-existing, separately tracked gap, not created or resolved by this plan) |
| `basis-adapters` has no `normalization_version` or `mapping_version` field | `basis-adapters`, if a future decision authorizes adding either (additive; see §9) |

Consistent with this plan's instructions, none of the following are
reassigned to `basis-adapters` merely because this assessment surfaced them
while working inside this repository: producer authentication, producer
enrollment, producer trust classification, gateway request admission,
identity verification, kernel invocation, authorization enforcement,
network retry behavior, protocol dispatch, execution-result evidence, or
durable evidence storage. Each remains exactly where
`operation-producer-and-execution-boundary.md` §10 places it.

---

## 11. Schema Impact Assessment

No current published schema is found to be actually insufficient by this
assessment. Applying the required test to each candidate gap from §5:

- **`evidence_digest` canonicalization** — no real producer has been built
  yet (the producer runtime does not exist), so there is no concrete
  scenario demonstrating that the *schema* (as opposed to the *missing
  runtime canonicalization behavior*) cannot represent a digest. The schema
  already accepts an `algorithm`/`value` pair in the exact shape a future
  canonicalization rule would produce. This is a missing runtime behavior,
  not a schema defect — explicitly, per this plan's instructions, "do not
  treat missing runtime behavior as a schema defect."
- **`reference_id` minting ownership** — the schema already accepts any
  non-empty string; nothing about the schema's shape blocks either
  `basis-adapters` or a producer runtime from populating it. This is an
  ownership question, not a schema gap.
- **`normalization_version` / `mapping_version`** — both are already
  optional, nullable fields in the published `adapter-evidence-reference`
  contract. `basis-adapters` simply does not yet produce values for them.
  No schema change is needed for `basis-adapters` to start supplying them,
  if a future decision authorizes that.
- **`redaction_classification`** — the five-value vocabulary is already
  published and closed by design; nothing in this assessment found a
  scenario the five values cannot represent.

**Conclusion: no schema change is currently justified.** This is the
preferred outcome per this plan's own instructions, and it is reached here
because every gap identified in §5 and §10 is a missing runtime decision or
missing runtime implementation, not a structural shortfall in what
`basis-schemas` has already published.

---

## 12. Recommended Future PR Sequence

Based on the findings above, not predetermined. Because the current public
surface is sufficient for the majority of the handoff, and the remaining
gaps are gated on architecture decisions this plan does not have the
authority to make, the smallest practical sequence is short.

### PR 1 — Contract-conformance tests against the published `adapter-evidence-reference` schema

**Objective.** Add tests asserting that `NormalizedAuthorizationRequest.protocol`
values, for all nine adapters, satisfy `adapter-evidence-reference.protocol`'s
pattern, and that a producer-runtime-style construction of `adapter_source`
from existing fields (`protocol` plus a caller-supplied label) round-trips
through the published schema's structural rules (exercised against a
vendored or fetched copy of the schema, consistent with how this repository
already validates other schemas in `tests/test_schema_examples.py`).

**Files/surfaces affected.** `tests/` only (new test module). No `src/`
change.

**Compatibility classification.** Additive conformance test.

**Prerequisite decision gates.** None — this PR tests what already exists.

**Required tests.** New; this PR *is* the tests.

**Explicit non-goals.** Does not implement `evidence_digest`,
`reference_id` minting, or any redaction logic. Does not add a
`basis-schemas` dependency to `pyproject.toml` — the vendoring/fetching
approach follows this repository's existing schema-validation pattern
(`docs/schema-validation.md`).

**Completion criteria.** Tests pass in CI; no `src/` behavior changes.

### PR 2 — `normalization_version` and `mapping_version` exposure, only if the architecture decision in §5 authorizes them

**Objective.** Expose a normalization-contract version distinct from the
package version (for example, a `NORMALIZATION_CONTRACT_VERSION` constant
in `basis_adapters/__init__.py`) and, per mapping-config class, an optional
`mapping_version` field, so a producer runtime can populate
`adapter-evidence-reference.normalization_version`/`mapping_version` without
guessing.

**Files/surfaces affected.** `src/basis_adapters/__init__.py`;
`src/basis_adapters/*/mapping.py` (nine files, additive optional field
each); `schemas/*-mapping.schema.json` (nine files, additive optional
property each); `docs/public-api.md`; `docs/contracts/normalization-contract.md`.

**Compatibility classification.** Additive optional model field
(mapping-config side) and additive new constant (package-version side).

**Prerequisite decision gates.** Whether either value is wanted at all by a
real producer-runtime consumer — not yet built, so this PR should not
proceed until one exists or the architecture process decides the value is
worth adding speculatively (this plan does not recommend the latter).

**Required tests.** Extend `tests/test_schema_examples.py` and each
adapter's existing mapping-validation tests to cover the new optional
fields; extend `tests/test_normalization_contract.py` if
`normalization_version` becomes part of the canonical shape (it would not
need to — it can live at package level instead, avoiding any change to
`NormalizedAuthorizationRequest` at all).

**Explicit non-goals.** Does not touch `NormalizedAuthorizationRequest`
itself if the package-level-constant approach is chosen. Does not implement
digest, reference-ID, or redaction logic.

**Completion criteria.** New optional fields validate correctly when
present and absent; existing mapping configs remain valid unchanged
(non-breaking); `docs/public-api.md` and `docs/compatibility.md` updated.

### PR 3 — Evidence-reference construction helper, only after Stage 4/5 of the boundary document's own sequence resolves canonicalization and minting ownership

**Objective.** If, and only if, a future architecture decision assigns
`basis-adapters` (rather than the producer runtime or a separate evidence
component) responsibility for `evidence_digest` canonicalization and/or
`reference_id` minting, add a helper that constructs an
`adapter-evidence-reference`-shaped object from an `AdapterResult`.

**Files/surfaces affected.** New module, e.g.
`src/basis_adapters/evidence.py`; `docs/public-api.md`;
`docs/contracts/normalization-contract.md`.

**Compatibility classification.** Additive new model / additive helper.

**Prerequisite decision gates.** Both open architecture decisions from §5
(`evidence_digest` canonicalization rule; `reference_id` minting owner)
must be resolved in `basis-adapters`' favor first. This PR must not proceed
speculatively ahead of those decisions.

**Required tests.** Digest determinism tests (same input → same digest,
across repeated calls and across process restarts); cross-protocol
contract tests extending the existing `test_normalization_contract.py`
pattern.

**Explicit non-goals.** Does not add a `basis-gateway` client. Does not add
authentication. Does not add redaction-classification logic — that remains
a producer-runtime or evidence-component responsibility per §10, even if
`basis-adapters` gains digest/reference-ID responsibility.

**Completion criteria.** Helper output validates against the published
`adapter-evidence-reference` schema for all nine adapters; existing
`NormalizedAuthorizationRequest` and `AdapterResult` shapes remain
unchanged.

### Not recommended at this time

A cross-protocol compatibility-scenario suite beyond PR 1's conformance
tests, an HTTP gateway client, an authentication mechanism, a long-running
adapter host, protocol execution, execution-result evidence, deployment
packaging, or a new repository — none of these are justified by this
assessment and all are explicit non-goals of this plan (see below).

If the architecture decisions in §5 resolve toward "producer runtime owns
minting and canonicalization entirely," PR 2 remains optional and PR 3
would not be recommended at all — the current public surface would already
be fully sufficient, and this plan's answer to its own governing question
would simplify to "sufficient as released."

---

## Non-Goals

Consistent with the work-item scope, this plan does not: add or modify
Python runtime code; add or modify JSON Schemas; add dependencies; import
`basis-gateway`; import `basis-core` runtime behavior; call a network
service; add authentication or token handling; add producer registration or
trust configuration; add a gateway client; add retries, timeouts, or
transport behavior; add protocol execution; add device communication; add
execution-result evidence; add evidence persistence; add hashing or
canonicalization behavior; add a new protocol; create an adapter host or
daemon; create a new repository; modify another BASIS repository; claim
operation-aware adapter integration is complete; or claim an `ALLOW` result
proves execution.

---

## Related Documents

- [`docs/contracts/normalization-contract.md`](contracts/normalization-contract.md)
- [`docs/contracts/adapter-contract.md`](contracts/adapter-contract.md)
- [`docs/public-api.md`](public-api.md)
- [`docs/compatibility.md`](compatibility.md)
- [`docs/architecture/basis-adapters.md`](architecture/basis-adapters.md)
- `basis-architecture`: `docs/architecture/operation-producer-and-execution-boundary.md`,
  `ROADMAP.md` ("Next Producer and Execution-Evidence Boundary"),
  `docs/architecture/ecosystem-contract-inventory.md`,
  `docs/security/threat-model.md`,
  `docs/roadmaps/identity-to-operation-contract-and-interoperability.md`
- `basis-schemas`: `docs/adapter-evidence-reference.md`,
  `docs/operation-aware-decision-request.md`,
  `docs/redaction-classification.md`
- `basis-gateway`: `docs/operation-aware-endpoint.md`
