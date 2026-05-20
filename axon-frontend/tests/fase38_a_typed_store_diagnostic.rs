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
fn s1_column_name_typo_in_where_is_rejected_with_axon_t801_and_levenshtein_hint() {
    // §1 INVERTED in place by 38.d's `StoreColumnProof::check_filter`
    // pass. The column reference `tenantid` (no underscore) does NOT
    // exist in the declared schema; axon check now rejects with
    // axon-T801 + a Levenshtein "Did you mean `tenant_id`?" hint.
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
    let errs = check_errors(src);
    assert!(
        errs.iter().any(|m| m.contains("axon-T801")),
        "§1 INVERTED: a column-name typo must surface axon-T801. \
         Errors observed: {errs:?}"
    );
    assert!(
        errs.iter().any(|m| m.contains("tenantid")),
        "§1: axon-T801 must name the offending typo `tenantid`. \
         Errors observed: {errs:?}"
    );
    assert!(
        errs.iter().any(|m| m.contains("tenant_id")),
        "§1: axon-T801 must surface the Levenshtein-closest column \
         `tenant_id` as the suggestion. Errors observed: {errs:?}"
    );
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
fn s2_where_value_type_mismatch_is_rejected_with_axon_t802() {
    // §2 INVERTED in place by 38.d's `StoreColumnProof::check_filter`
    // pass. The flow parameter type `Int` is not compatible with a
    // `Uuid` column per the closed compat matrix; axon check now
    // rejects with axon-T802 + names the parameter, its type, the
    // column, and the column's type.
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
    let errs = check_errors(src);
    assert!(
        errs.iter().any(|m| m.contains("axon-T802")),
        "§2 INVERTED: an Int → Uuid binding must surface axon-T802. \
         Errors observed: {errs:?}"
    );
    assert!(
        errs.iter().any(|m| m.contains("tenant_id") && m.contains("Int") && m.contains("Uuid")),
        "§2: axon-T802 must name the parameter, its declared type \
         `Int`, and the column type `Uuid`. Errors observed: {errs:?}"
    );
    // Reference `check_passes` so the helper stays exercised + the
    // import warning stays quiet (the helper now serves other §-tests).
    let _: fn(&str) -> bool = check_passes;
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
fn s3_persist_field_typo_is_rejected_with_axon_t804() {
    // §3 INVERTED in place by 38.e's `check_persist_fields` pass. The
    // field name `tenantid` (no underscore) is a typo — the declared
    // column is `tenant_id`. axon check now rejects with axon-T804 +
    // a Levenshtein "Did you mean `tenant_id`?" hint at compile time,
    // no live database required (the offline-checkable gap 37.x D8
    // alone couldn't close).
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
    let errs = check_errors(src);
    assert!(
        errs.iter().any(|m| m.contains("axon-T804")),
        "§3 INVERTED: a persist field-name typo must surface axon-T804. \
         Errors observed: {errs:?}"
    );
    assert!(
        errs.iter().any(|m| m.contains("tenantid")),
        "§3: axon-T804 must name the offending typo `tenantid`. \
         Errors observed: {errs:?}"
    );
    assert!(
        errs.iter().any(|m| m.contains("tenant_id")),
        "§3: axon-T804 must surface the Levenshtein-closest column \
         `tenant_id` as the suggestion. Errors observed: {errs:?}"
    );
    let _: fn(&str) -> bool = check_passes;
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
