//! §Fase 92.c — runtime for `mint <Credential> as <binding>`
//! (`docs/fase/fase_92_ephemeral_visitor_credentials.md`, axon-enterprise repo).
//!
//! Pinned properties:
//! 1. Happy path: a mint with a configured port + a capability context
//!    covering the grants binds the raw bearer under the declared binding;
//!    the wire summary NEVER carries the token (the runtime half of
//!    `axon-T896`).
//! 2. No port configured ⇒ `MissingDependency` — fail-closed, no silent
//!    stub (§86 lesson).
//! 3. Attenuation: a capability context missing a grant refuses the mint
//!    naming `authority_only_attenuates` (handler-side) — and the port
//!    itself refuses standalone (`InMemoryMinter` unit lane).
//! 4. End-to-end through the production engine: a `mint`-bearing flow with
//!    NO minter port fails the flow loudly (never an LLM-hallucinated
//!    token).

use axon::cancel_token::CancellationFlag;
use axon::credential_minter::InMemoryMinter;
use axon::flow_dispatcher::{dispatch_node, DispatchCtx, NodeOutcome};
use axon::ir_nodes::{IRCredential, IRFlowNode, IRMintStep};
use std::sync::Arc;

fn mint_node() -> IRFlowNode {
    IRFlowNode::Mint(IRMintStep {
        node_type: "mint",
        source_line: 1,
        source_column: 1,
        credential_ref: "WidgetSession".to_string(),
        binding: "tok".to_string(),
    })
}

fn contract() -> IRCredential {
    IRCredential {
        node_type: "credential",
        source_line: 1,
        source_column: 1,
        name: "WidgetSession".to_string(),
        ttl_secs: 900,
        grants: vec!["chat.invoke".to_string()],
    }
}

fn ctx_with(
    minter: Option<Arc<InMemoryMinter>>,
    caps: Option<Vec<String>>,
) -> (
    DispatchCtx,
    tokio::sync::mpsc::UnboundedReceiver<axon::flow_execution_event::FlowExecutionEvent>,
) {
    let (tx, rx) = tokio::sync::mpsc::unbounded_channel();
    let mut ctx = DispatchCtx::new("F", "stub", "", CancellationFlag::new(), tx);
    ctx.credentials = Arc::new(
        [(contract().name.clone(), contract())].into_iter().collect(),
    );
    if let Some(m) = minter {
        ctx.credential_minter = Some(m);
    }
    ctx.held_capabilities = caps;
    (ctx, rx)
}

#[tokio::test]
async fn mint_binds_the_bearer_and_never_wires_the_token() {
    let minter = Arc::new(InMemoryMinter::new());
    let (mut ctx, mut rx) = ctx_with(
        Some(minter.clone()),
        Some(vec!["chat.invoke".to_string(), "flow.execute".to_string()]),
    );
    let outcome = dispatch_node(&mint_node(), &mut ctx).await.expect("mint admits");

    let token = ctx.let_bindings.get("tok").expect("binding present").clone();
    assert!(token.starts_with("axep_"), "reference token shape: {token}");
    // The minted token verifies against the reference minter.
    let rec = minter.verify(&token).expect("token verifies");
    assert_eq!(rec.grants, vec!["chat.invoke"]);

    // The wire summary + the outcome NEVER carry the raw bearer.
    let NodeOutcome::Completed { output, .. } = outcome else {
        panic!("expected Completed");
    };
    assert!(output.contains("credential 'WidgetSession' minted"), "{output}");
    assert!(!output.contains(&token), "token must not ride the outcome");
    drop(ctx); // close tx
    while let Ok(ev) = rx.try_recv() {
        let json = serde_json::to_string(&ev).unwrap();
        assert!(!json.contains(&token), "token must not ride the wire: {json}");
    }
}

#[tokio::test]
async fn missing_minter_port_fails_closed() {
    let (mut ctx, _rx) = ctx_with(None, Some(vec!["chat.invoke".to_string()]));
    let err = dispatch_node(&mint_node(), &mut ctx)
        .await
        .expect_err("no port ⇒ fail closed");
    let msg = format!("{err:?}");
    assert!(msg.contains("credential_minter"), "names the dependency: {msg}");
    assert!(ctx.let_bindings.get("tok").is_none(), "no binding on refusal");
}

#[tokio::test]
async fn attenuation_violation_is_refused_at_the_handler() {
    let minter = Arc::new(InMemoryMinter::new());
    // The bearer holds a DIFFERENT capability — grants ⊄ caps.
    let (mut ctx, _rx) = ctx_with(Some(minter), Some(vec!["flow.execute".to_string()]));
    let err = dispatch_node(&mint_node(), &mut ctx)
        .await
        .expect_err("amplification refused");
    let msg = format!("{err:?}");
    assert!(
        msg.contains("authority_only_attenuates"),
        "names the law: {msg}"
    );
    assert!(msg.contains("chat.invoke"), "names the missing grant: {msg}");
}

#[test]
fn e2e_mint_without_a_port_fails_the_flow_loudly() {
    // Through the PRODUCTION engine (execute_server_flow → dispatcher via
    // BufferSink): no minter is configured on the OSS server path, so the
    // flow fails closed — never an LLM-fabricated bearer.
    let src = "credential WidgetSession { ttl: 15m grants: [chat.invoke] }\n\
               flow Bootstrap() -> Unit {\n\
                   mint WidgetSession as tok\n\
                   step S { ask: \"hi\" }\n\
               }\n";
    let (_prog, ir) = axon::flow_plan::compile_source_to_ir(src, "<fase92>").expect("compile");
    let empty = std::collections::HashMap::new();
    let m = axon::runner::execute_server_flow(
        &ir, "Bootstrap", "stub", "", "<fase92>", None, None, &empty, &empty, None, None, None,
        None, None, None,
        None, // §Fase 94.d — secret custody (test: none)
        None, // §Fase 108.b dataspace_engine (tests: fail closed)
        None, // §Fase 102 scrape_overrides
)
    .expect("execute returns metrics");
    assert!(!m.success, "mint without a port must fail the flow");
    let err = m.error.expect("honest failure detail");
    assert!(err.contains("credential_minter"), "names the dependency: {err}");
}
