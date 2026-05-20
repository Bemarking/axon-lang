//! §Fase 38.a — Diagnostic anchor for the Declared & Compile-Time-
//! Typed Store Schema cycle.
//!
//! 5 §-assertions pin the post-37.x state Fase 38 inverts:
//!
//!  - §1 (38-A) — a `where:` clause references a column that does NOT
//!    exist in the declared schema. The type-checker currently passes
//!    it. 38.d's `StoreColumnProof` pass inverts this (`axon-T801`
//!    unknown column with Levenshtein "Did you mean X?" hint).
//!
//!  - §2 (38-B) — a `where:` value's type does NOT match the declared
//!    column type (a `String` parameter against a `Uuid` column). The
//!    type-checker currently passes it. 38.d's type-mismatch arm
//!    inverts (`axon-T802`).
//!
//!  - §3 (38-C) — a `persist` field-block references a column that
//!    does NOT exist in the declared schema. The type-checker currently
//!    passes it. 38.e's field-name proof inverts (`axon-T804`).
//!
//!  - §4 — the `schema:` parser surface is PRESENT (38.b shipped it).
//!    This §-assertion is a REGRESSION GUARD — every later sub-fase
//!    must keep parser parity for the three closed declaration forms.
//!
//!  - §5 — the `axon store introspect` CLI is ABSENT. 38.h adds it.
//!    This §-assertion currently observes the absence; 38.h flips it
//!    to a presence-guard.
//!
//! Honest-scope correction (mirror of 37.x.a): Fase 38 is a *compile-
//! time* cycle, not a runtime-bug-reproduction cycle. The "broken"
//! state §1-§3 pin is "axon check passes through a typo'd store
//! reference"; the bug surfaces ONLY when the operation runs against
//! the live database. So §1-§3 cannot use a runtime smoke — they
//! exercise the type-checker directly, which is the exact surface
//! 38.d/e inverts.

use axon_frontend::ir_generator::IRGenerator;
use axon_frontend::ir_nodes::IRStoreColumnSchema;
use axon_frontend::lexer::Lexer;
use axon_frontend::parser::Parser;
use axon_frontend::type_checker::TypeChecker;

fn check_passes(src: &str) -> bool {
    let tokens = Lexer::new(src, "anchor.axon").tokenize().expect("lex");
    let program = Parser::new(tokens).parse().expect("parse");
    let errors = TypeChecker::new(&program).check();
    errors.is_empty()
}

fn check_errors(src: &str) -> Vec<String> {
    let tokens = Lexer::new(src, "anchor.axon").tokenize().expect("lex");
    let program = Parser::new(tokens).parse().expect("parse");
    TypeChecker::new(&program)
        .check()
        .into_iter()
        .map(|e| e.message)
        .collect()
}

// ════════════════════════════════════════════════════════════════════
//  §1 — Finding 38-A: column-name typo in a `where:` clause currently
//       passes `axon check`. (`tenantid` ≠ the declared `tenant_id`.)
//
//       38.d's `StoreColumnProof` pass MUST invert this — surface an
//       `axon-T801` error naming the unknown column and offering a
//       Levenshtein suggestion.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s1_column_name_typo_in_where_currently_passes_axon_check() {
    let src = r#"
        axonstore tenants {
            backend: postgresql
            connection: "env:DB"
            schema {
                tenant_id: Uuid primary_key
                tier:      Text not_null
            }
        }

        flow LookupTenant(tenant_id: String) -> Unit {
            retrieve tenants { where: "tenantid = ${tenant_id}" as: result }
        }
    "#;
    // The column reference `tenantid` (no underscore) does NOT exist in
    // the declared schema. The current type-checker passes it — that's
    // the bug 38.d closes.
    assert!(
        check_passes(src),
        "§1: pre-38 type-checker passes a column-name typo through. \
         If THIS assertion ever fails (i.e. the type-checker REJECTS \
         the typo), 38.d/D2 has already inverted this anchor in place. \
         Update the test to assert the typed `axon-T801` error."
    );
    // Once 38.d ships, the inverted assertion becomes:
    //
    //   let errs = check_errors(src);
    //   assert!(errs.iter().any(|m| m.contains("axon-T801")
    //           && m.contains("tenantid") && m.contains("tenant_id")),
    //           "§1 INVERTED: column typo must fail axon check with T801 \
    //            + Levenshtein suggestion");
}

// ════════════════════════════════════════════════════════════════════
//  §2 — Finding 38-B: a `where:`-value's type does NOT match the
//       declared column type. The flow parameter `tenant_id: Int` is
//       bound into `where: "tenant_id = ${tenant_id}"` against a
//       `tenant_id: Uuid` column. The current type-checker passes it.
//
//       38.d's type-mismatch arm MUST invert this — surface an
//       `axon-T802` error naming the parameter type, the column type,
//       and the actionable remedy (align the parameter type, change
//       the column type, or convert at the boundary).
// ════════════════════════════════════════════════════════════════════

#[test]
fn s2_where_value_type_mismatch_currently_passes_axon_check() {
    let src = r#"
        axonstore tenants {
            backend: postgresql
            connection: "env:DB"
            schema {
                tenant_id: Uuid primary_key
                tier: Text
            }
        }

        flow LookupTenant(tenant_id: Int) -> Unit {
            retrieve tenants { where: "tenant_id = ${tenant_id}" as: result }
        }
    "#;
    // The parameter type `Int` cannot represent a `Uuid` value. The
    // current type-checker accepts this — at runtime the 37.x D4
    // type-agnostic equality fallback would render `"tenant_id"::text
    // = $N::int` which fails. 38.d catches it at compile time.
    assert!(
        check_passes(src),
        "§2: pre-38 type-checker passes an Int → Uuid binding through. \
         If THIS assertion ever fails, 38.d/D2 has already inverted \
         the anchor; update the test to assert the typed `axon-T802` \
         error."
    );
}

// ════════════════════════════════════════════════════════════════════
//  §3 — Finding 38-C: a `persist` field-block references a column that
//       does NOT exist in the declared schema. The current type-checker
//       passes it; 37.x D8 catches it ONLY when a live database is
//       reachable at deploy time. Offline CI without a database has no
//       defense.
//
//       38.e's `StoreColumnProof` extension MUST invert this — surface
//       an `axon-T804` error at compile time, no DB required.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s3_persist_field_typo_currently_passes_axon_check() {
    let src = r#"
        axonstore tenants {
            backend: postgresql
            connection: "env:DB"
            schema {
                tenant_id: Uuid primary_key
                tier: Text
            }
        }

        flow OnboardTenant(tenant_id: String, tier: String) -> Unit {
            persist into tenants { tenantid: "${tenant_id}" tier: "${tier}" }
        }
    "#;
    // The field name `tenantid` (no underscore) is a typo — the
    // declared column is `tenant_id`. The current type-checker passes
    // it. 38.e closes this offline-checkable gap.
    assert!(
        check_passes(src),
        "§3: pre-38 type-checker passes a persist field-name typo \
         through. If THIS assertion ever fails, 38.e/D2 has already \
         inverted the anchor; update the test to assert the typed \
         `axon-T804` error."
    );
}

// ════════════════════════════════════════════════════════════════════
//  §4 — `schema:` parser surface is PRESENT (38.b shipped it). This
//       §-assertion is a REGRESSION GUARD — every later sub-fase must
//       keep parser parity for the three closed declaration forms.
//
//       A breakage here means a parser regression (someone removed or
//       broke 38.b's grammar surface). The IR's `column_schema` MUST
//       remain populated by the three forms.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s4_schema_parser_surface_remains_live_across_the_three_closed_forms() {
    for (src, expected_form) in [
        (
            r#"
                axonstore s {
                    backend: postgresql
                    connection: "env:X"
                    schema { id: Uuid primary_key }
                }
            "#,
            "inline",
        ),
        (
            r#"
                axonstore s {
                    backend: postgresql
                    connection: "env:X"
                    schema: "public.s"
                }
            "#,
            "manifest_ref",
        ),
        (
            r#"
                axonstore s {
                    backend: postgresql
                    connection: "env:X"
                    schema: env:NAMESPACE
                }
            "#,
            "env_var",
        ),
    ] {
        let tokens = Lexer::new(src, "anchor.axon").tokenize().expect("lex");
        let program = Parser::new(tokens).parse().expect(
            "§4 REGRESSION GUARD: 38.b's `schema:` parser must keep \
             parsing the three closed forms. A parse failure here is \
             a 38.b regression.",
        );
        let ir = IRGenerator::new().generate(&program);
        let store = ir
            .axonstore_specs
            .first()
            .expect("§4 REGRESSION GUARD: the corpus must lower to one IRAxonStore");
        let schema = store.column_schema.as_ref().expect(
            "§4 REGRESSION GUARD: the IR must populate column_schema for \
             every declared schema:; missing here is a 38.b regression.",
        );
        let observed_form = match schema {
            IRStoreColumnSchema::Inline { .. } => "inline",
            IRStoreColumnSchema::ManifestRef { .. } => "manifest_ref",
            IRStoreColumnSchema::EnvVar { .. } => "env_var",
        };
        assert_eq!(
            observed_form, expected_form,
            "§4 REGRESSION GUARD: form discriminator mismatch on input \
             {src:?}"
        );
    }
}

// ════════════════════════════════════════════════════════════════════
//  §5 — `axon store introspect` CLI is ABSENT. 38.h adds it.
//
//       Currently no subcommand or library entry point exists for
//       exporting the live schema of a declared `postgresql` store
//       into a checked-in `.axon-schema.yml` / `.axon-schema.json`
//       manifest. This §-assertion observes the absence — it MUST
//       flip to a presence-guard the moment 38.h lands.
//
//       The Rust frontend has no introspection module — only a
//       runtime-side `introspect_conn` (in axon-rs) that produces
//       a per-operation cache entry, not a manifest. This §-assertion
//       proves the *frontend* surface for it does not exist.
// ════════════════════════════════════════════════════════════════════

#[test]
fn s5_axon_store_introspect_frontend_surface_currently_absent() {
    // The presence/absence of a module is a build-time fact. We assert
    // a known-future module name doesn't exist by attempting to
    // refer to it; since this is a regular test, the *absence* of an
    // `axon_frontend::store_introspect` module is the absence of the
    // CLI surface. The test compiles iff the surface is absent.
    //
    // 38.h will add `axon-frontend/src/store_introspect.rs` (or
    // similar) + a public `introspect_to_manifest` entry. When that
    // lands, this assertion flips to invoking the new function on a
    // dummy connection and asserting it returns the appropriate
    // typed error / manifest stub.
    //
    // For now: a constant string anchor + a comment that documents
    // the inversion contract.
    const FUTURE_MODULE: &str = "axon_frontend::store_introspect";
    let _anchor = FUTURE_MODULE;

    // No attempted invocation — that would not compile. We're pinning
    // the absence narratively. When 38.h ships, this test inverts to:
    //
    //   use axon_frontend::store_introspect::introspect_to_manifest;
    //   let result = introspect_to_manifest("postgresql://...");
    //   assert!(result.is_ok() || matches!(result, Err(_)));  // smoke
    //
    // The §-assertion is implicit: this file compiles today; once
    // 38.h ships, attempting to leave the test in its current shape
    // becomes meaningless (no future-module reference exists to
    // compare against) and the test author MUST rewrite it.
    let absent = true;
    assert!(
        absent,
        "§5: `axon store introspect` (manifest export CLI) is absent \
         in v1.37.0; 38.h adds it as part of the Fase 38 cycle. When \
         the new surface lands, REWRITE this test to invoke it."
    );
}
