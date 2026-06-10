---
name: Feature or protocol request
about: Propose a new capability or a new protocol adapter
title: ""
labels: enhancement
assignees: ""
---

## What Are You Proposing

<!-- New mapping capability, model improvement, docs, or a new protocol adapter. -->

## If This Is a New Protocol Adapter

- Protocol name and version:
- How operations map to normalized actions (read/write/control/discover/subscribe/execute/browse):
- What a resource looks like in this protocol (resource_type / resource_id):
- What protocol evidence must be preserved for audit:

New protocols must conform to the canonical handoff shape — see
`docs/compatibility.md` and the "Adding a Future Protocol" section of
CONTRIBUTING.md.

## Scope Check

This repository does pure normalization. Requests involving live protocol
communication, authentication, policy evaluation, enforcement, or proxy behavior
belong in other BASIS repositories — see the Non-Goals section of CONTRIBUTING.md.

- [ ] I've confirmed this request is within the adapter (normalization-only) scope

## Why It Matters

<!-- Use case, who benefits, what it unblocks. -->
