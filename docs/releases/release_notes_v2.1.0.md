# axon-lang v2.1.0 — Shield scanner extension point

**A public, language-level hook for downstream shield scanners.**

## What's new

`axon-lang` now exposes a public **shield-scanner registration hook**
(`axon::shield_registry`). The `shield apply <name> to <target>` algebraic
effect consults a process-global registry of scanners; a registered scanner
returns a verdict — `Pass` (with possibly-redacted content) or `Reject` (with
a stable blame code + adopter-facing reason). When no scanner is registered
for a name, the OSS identity passthrough applies, exactly as before.

This is a deliberate language extension point: it lets a privileged downstream
layer inject domain scanners (e.g. healthcare / legal / fintech compliance)
without forking the language, and it does so in a way that makes axon a better
host for *any* such layer — independent of who registers scanners.

### Public API (new)

- `axon::shield_registry::ShieldScanner` — the trait downstream scanners implement.
- `ShieldVerdict::{Pass, Reject}` + `ShieldScanContext`.
- `register_shield_scanner` / `lookup_shield_scanner` / `unregister_shield_scanner`
  / `registered_shield_names` / `has_registered_scanners` / `clear_shield_registry`.

## Compatibility

- **Backwards-compatible (MINOR).** No existing behaviour changes: with no
  scanner registered, `shield apply` remains an identity passthrough. The wire
  shape (`step_type: "shield_apply"`, StepStart/StepComplete) is unchanged.
- A rejecting scanner surfaces a structured
  `DispatchError::BackendError { name: "shield:<name>", message: "[<code>] <reason>" }`
  on the dispatch path; no output binds for a rejected shield.
- `axon-frontend` (1.0.0) and `axon-csys` (0.2.0) are unchanged and not
  re-published; `axon-lang 2.1.0` depends on the same pinned versions.

## Why now

This unblocks the enterprise Pure-Silicon migration (Fase 40): the BSL
`axon-enterprise` workspace consumes `axon-lang 2.1.0` via a versioned Cargo
dependency and registers its vertical scanners against this hook — no fork, no
hybrid runtime.

## Verification

- 2204 axon-rs lib tests green (+7 new: 4 registry + 3 dispatcher), zero regressions.
- OSS identity default preserved; registered scanner transforms; rejecting
  scanner surfaces a structured error and binds no output.
