# Security Policy

## Project Status

`basis-adapters` is an early-stage project. The adapters in this repository perform
**pure normalization**: they translate protocol-specific operations into canonical
authorization requests. They do not currently perform live protocol communication,
open network sockets, authenticate callers, or enforce decisions.

No claims of production readiness are made. This library has not been audited and
should not be deployed in production OT environments in its current state.

## Reporting a Vulnerability

Please do **not** report security issues through public GitHub issues.

Use GitHub's private vulnerability reporting on this repository
(**Security** tab → **Report a vulnerability**). If private reporting is not
available, contact the maintainer directly rather than disclosing publicly.

<!-- Maintainer: add a security contact email here when one exists. -->

Please include a description of the issue, steps to reproduce, and an assessment of
impact if you have one. You can expect an acknowledgment within a reasonable
timeframe; as an early-stage project there is no formal SLA yet.

## What Counts as a Security Issue Here

Even though adapters do not speak to networks, normalization correctness is
security-relevant. Reports are welcome for issues such as:

- **Unsafe normalization** — an operation normalized into a request that
  misrepresents the action, resource, or protocol (e.g. a write normalized as a read).
- **Evidence loss** — normalized requests that drop, truncate, or mutate protocol
  evidence, undermining downstream audit.
- **Fail-open behavior** — any path where a normalization failure could be mistaken
  for, or produce, a forwardable request.
- **Accidental authorization or enforcement logic** — code that crosses the adapter
  boundary by making or implying an allow/deny decision.
- **Dependency vulnerabilities** — issues in development or (future) runtime
  dependencies.

## Scope Notes

Issues in policy evaluation belong to `basis-core`; issues in authentication,
identity, or enforcement belong to `basis-gateway`. If you are unsure which
repository an issue belongs to, report it here and it will be routed.
