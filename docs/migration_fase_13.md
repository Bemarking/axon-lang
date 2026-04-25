# Fase 13 Migration Guide — String Topics → Typed Channels

**Audience:** Adopters with existing `.axon` programs that use the
legacy `listen "topic"` form (introduced in Fase 11.d, Pre-Fase 13).

**Schedule (D4, paper §1.2):**

| Version | String topics | Typed channels |
|---|---|---|
| **v1.4.x** (current) | Legal — emit deprecation warning | Canonical form |
| **v1.5.0** (target) | Legal — `--strict` opt-in promotes warning to error | Canonical form |
| **v2.0** (planned) | **Compile error** — string topics removed | Required |

This document is the bridge.  It covers (i) what changed, (ii) how to
detect impacted code, (iii) how to migrate manually or via the script,
and (iv) how to gate CI so new code doesn't regress.

---

## 1. What changed

### Before (Fase 11.d — string topics)

```axon
daemon OrderProcessor() {
    goal: "process orders"
    listen "orders.created" as event {
        step Validate { ask: "validate" }
    }
}
```

The string `"orders.created"` is opaque to the compiler:

- no schema verification between producer and consumer
- no static topology graph (LSP, analyzer cannot resolve refs)
- no capability gating (publish/discover absent — see paper §1.1)

### After (Fase 13 — typed channels)

```axon
type Order { id: String }

channel OrdersCreated {
    message: Order
    qos: at_least_once
    lifetime: affine
    persistence: ephemeral
    shield: PublicBroker        // required for publish (D8)
}

daemon OrderProcessor() {
    goal: "process orders"
    listen OrdersCreated as event {
        step Validate { ask: "validate" }
    }
}
```

`OrdersCreated` is now a first-class affine resource the compiler
understands.  Schema (`message: Order`), QoS, lifetime, persistence
and shield are all checked at compile time and enforced at runtime
(see [`paper_mobile_channels.md`](paper_mobile_channels.md) §3 for
the typing rules and §4 for runtime semantics).

---

## 2. Detecting impacted code

### `axon check` surfaces every legacy listener

Running `axon check <file.axon>` against any program that still uses
string topics produces a deprecation warning per occurrence.  In the
default mode, the check still passes (exit 0):

```
$ axon check app.axon
⚠ app.axon  36 tokens · 1 declarations · 0 errors · 2 warning(s)
  warning  line 3: daemon 'D' uses string topic 'orders.created' which is deprecated since Fase 13 (v1.4.x). Migrate to a typed `channel` declaration; string topics will be removed in v2.0 (D4).
  warning  line 4: daemon 'D' uses string topic 'orders.cancelled' which is deprecated since Fase 13 (v1.4.x). Migrate to a typed `channel` declaration; string topics will be removed in v2.0 (D4).
```

### `--strict` for CI

Add `--strict` to your CI pipeline once you have migrated.  In strict
mode, every warning is treated as an error and the check exits 1:

```yaml
# .github/workflows/axon.yml
- name: Validate AXON sources
  run: axon check src/main.axon --strict
```

This guarantees your codebase doesn't regress while you're between
v1.4.x and v2.0.

---

## 3. Migration

### Option A — Automatic (recommended)

The repo includes a migration helper at
`scripts/migrate_string_topics.py`.  It rewrites your file in place,
generating `channel <Name>` declarations at the top with a default
schema (`message: Bytes`, `qos: at_least_once`, `lifetime: affine`)
and replacing each `listen "topic"` with `listen <Name>`.

```bash
# Preview the migration to stdout
python -m scripts.migrate_string_topics src/main.axon

# Migrate in place (creates src/main.axon.bak as backup)
python -m scripts.migrate_string_topics src/main.axon --in-place

# Override the default channel schema
python -m scripts.migrate_string_topics src/main.axon \
    --message Order --qos exactly_once --lifetime linear
```

The script:

- collects every unique string topic via regex match
- converts each topic to a PascalCase identifier
  (`orders.created → OrdersCreated`, `kebab-style → KebabStyle`)
- emits one `channel` block per unique topic, with `// review` hints
- rewrites every matching `listen "..."` to `listen <Identifier>`
- re-runs `axon check` on the output and fails if the result is not
  clean (use `--no-verify` to bypass)

After running the script, **review every generated channel** and
refine:

- `message:` — replace `Bytes` with the actual payload type, declared
  via `type <Name> { … }` (with a `compliance: [HIPAA, …]` annotation
  if the data is regulated — paper §3.4 + ESK Fase 6.1)
- `qos:` — pick `at_most_once` / `at_least_once` / `exactly_once` /
  `broadcast` / `queue` based on producer/consumer cardinality
- `lifetime:` — `linear` (must be consumed once), `affine` (default —
  drop OK, no aliasing), `persistent` (`!Channel`, replicable)
- `persistence:` — `ephemeral` (default) or `persistent_axonstore`
  (handle survives reboots via AxonStore — Fase §AS)
- `shield:` — required if you intend to call `publish <Channel>`
  on this channel (D8 — capability extrusion is shield-mediated)

### Option B — Manual

For each legacy listener `listen "topic" as alias { … }`:

1. Pick a PascalCase identifier (e.g., `OrdersCreated`)
2. Add a `channel <Identifier> { message: T … }` declaration at the
   top level
3. Replace `listen "topic"` with `listen <Identifier>`

Example diff:

```diff
+channel OrdersCreated {
+    message: Order
+    qos: at_least_once
+    lifetime: affine
+}
+
 daemon OrderProcessor() {
     goal: "process orders"
-    listen "orders.created" as event {
+    listen OrdersCreated as event {
         step Validate { ask: "validate" }
     }
 }
```

---

## 4. After migration

### 4.1 Lock CI to strict

Add `--strict` to your CI command so future PRs don't reintroduce
string topics:

```bash
axon check src/**/*.axon --strict
```

### 4.2 Take advantage of new capabilities

Migration unlocks features that string topics structurally denied:

- **Schema-checked emit/listen** — paper §3.1 Chan-Output
- **Mobility** — pass channel handles via other channels (paper §3.2)
- **Capability gating** — `publish C within Shield` exposes a handle
  with compile-time compliance enforcement (paper §3.4)
- **Discover** — type-safe dynamic import of published handles
- **LSP support** — go-to-definition, find-references, autocomplete
  on channel names (axon-lsp v0.2.0+)
- **Static topology** — analyzers can render the reactive graph

### 4.3 Reference

- [`docs/paper_mobile_channels.md`](paper_mobile_channels.md) — full
  formal specification of the typed-channel calculus
- [`docs/fase_13_mobile_typed_channels.md`](fase_13_mobile_typed_channels.md)
  — phase plan with implementation status
- `scripts/migrate_string_topics.py` — migration helper source
- `axon/runtime/channels/typed.py` — runtime layer reference

---

## 5. Troubleshooting

**`axon check` reports an error after migration**
- The script's default `message: Bytes` may not match what your
  producer emits. Refine the type and re-run `axon check`.

**`publish` errors with "is not publishable"**
- Add `shield: <Name>` to the channel declaration; the shield must
  exist as a `shield` declaration in scope (D8).

**Topic name collisions after PascalCase conversion**
- Two distinct topics like `"orders.created"` and `"OrdersCreated"`
  collapse to the same identifier.  Manually rename one before
  running the script, or post-edit the generated channel names.

**Backup `.bak` files cluttering the tree**
- The `--in-place` mode writes one `.bak` per migrated file. After
  verifying the migration, you can `git clean -e '*.bak'` or remove
  them manually.
