# Trust Types — Untrusted\<T\> → Trusted\<T\> via a closed verifier catalogue

§λ-L-E Fase 11.a. Integrates security into Axon's type system: a
payload that enters the runtime from an untrusted source
(HTTP body, WebSocket frame, OAuth2 redirect code, signed webhook)
is **born** as `Untrusted<T>`. The only way to reach a `Trusted<T>`
— the type every sensitive effect consumes — is through a verifier
in the closed **Trust Catalogue**.

Forgetting to verify is not a runtime bug. It is a **compile
error**.

## The closed Trust Catalogue

| Slug | Verifier | When to use |
|---|---|---|
| `hmac` | HMAC-SHA256 over the raw payload | Webhook signatures (Stripe, GitHub, generic HMAC) |
| `jwt_sig` | RS256/RS384/RS512 signature verification via JWKS | Bearer tokens from your IdP (shared with Fase 10.e) |
| `oauth_code_exchange` | OAuth2 authorization-code exchange with PKCE S256 | Handling the redirect from an OIDC provider |
| `ed25519` | Ed25519 detached signature (`verify_strict`) | Sigstore attestations, signed binaries, detached receipts |

Catalogue is closed — extension requires a compiler patch + security
review. Adopters who need a domain-specific refinement (e.g. "valid
ISO-8583 message format") contribute the verifier upstream instead
of wiring their own `if check_something(payload): ...` — the
latter is what the type system exists to prevent.

## Source syntax

The refinement tag is a type constructor taking one generic
parameter:

```axon
tool verify_webhook_signature {
  provider: local
  timeout:  5s
  effects:  <trust:hmac>
}

flow HandleStripeEvent(body: Untrusted<HttpBody>) {
  step Verify {
    given: body
    ask:   "authenticate"
    apply: verify_webhook_signature
  }
  step Process {
    given: Verify.output
    ask:   "dispatch to state machine"
  }
}
```

Without `apply: verify_webhook_signature` the checker emits:

```
error: Flow 'HandleStripeEvent' accepts 'Untrusted<T>' in its
       signature but no reachable tool declares a 'trust:<proof>'
       effect. Untrusted payloads MUST be refined via one of the
       catalogue verifiers: hmac, jwt_sig, oauth_code_exchange,
       ed25519. Add the appropriate effect to the verifier tool
       (e.g. `effects: <trust:hmac>`).
```

## Runtime guarantees

Python: `axon.runtime.trust.verify_hmac_sha256(payload, tag, key, key_id=...)` and siblings
return a typed `Trusted[bytes]` carrying a `VerifiedPayload`
(proof kind + opaque key identifier — never the raw secret).

Rust: `axon_rs::trust_verifiers::verify_hmac_sha256(...)` and
siblings return a `VerifiedPayload`. Implementation notes:

- **HMAC** routes comparison through `hmac::Mac::verify_slice`
  which uses `subtle::ConstantTimeEq` internally — byte-by-byte
  comparison inside the MAC step would leak timing, and the
  catalogue entry documents this property so reviewers don't
  have to re-audit every release.
- **Ed25519** uses `verify_strict`, which rejects the low-order
  point attack pool that the non-strict API accepts. We never
  expose `verify()` without the `strict` suffix.
- **JWT** delegates to Fase 10.e `JwtVerifier` — the two
  catalogue entries refer to the same verifier, so new JWT
  algorithms enforced in 10.e (e.g. RS384 added) automatically
  propagate here.
- **OAuth2 PKCE S256** is a networked verifier: it performs an
  HTTP POST to the token endpoint. The compiler tolerates async
  in the OAuth branch.

## Closed-catalogue enforcement

Adding a new verifier requires three simultaneous changes:

1. Rust enum variant in `axon-rs/src/refinement.rs::TrustProof`
2. Python enum variant in `axon/runtime/trust.py::TrustProof`
3. Runtime verifier function in both `trust_verifiers.rs` and
   `trust.py` with an entry in `TRUST_VERIFIERS` so the compiler
   recognises the function as a catalogue member

A PR that touches only one side fails CI — the parity test suite
asserts the two catalogues are identical.

## Trust IS NOT safety

A `Trusted<T>` is a proof that the payload has a cryptographic
provenance — it is NOT a proof that the payload's *contents* are
safe to process. An HMAC-valid payload can still carry an SQL
injection; a JWT-valid token can still name an attacker as `sub`.

Trust types exist alongside content-safety primitives (shields,
schema validation, allow-lists); they do not replace them. The
difference:

- Trust: "where did this payload come from?"
- Safety: "does the content of this payload do anything harmful?"

Both are needed; neither subsumes the other.

## Compile-time errors (selected)

```
error: Effect 'trust' in tool 'verify_signature' requires a proof
       qualifier 'trust:<proof>'. Valid proofs: hmac, jwt_sig,
       oauth_code_exchange, ed25519.
```

```
error: Unknown trust proof 'crc32' in tool 'verify_signature'.
       Valid: hmac, jwt_sig, oauth_code_exchange, ed25519.
```

## Where to look in the code

- Closed catalogue + annotation parser: [`axon-rs/src/refinement.rs`](../axon-rs/src/refinement.rs)
- Runtime verifiers: [`axon-rs/src/trust_verifiers.rs`](../axon-rs/src/trust_verifiers.rs)
- Python mirror: [`axon/runtime/trust.py`](../axon/runtime/trust.py)
- Flow-level checker: `axon-rs::type_checker::check_refinement_and_stream_contracts`
- Python checker mirror: [`axon/compiler/refinement_check.py`](../axon/compiler/refinement_check.py)
- Integration tests: [`axon-rs/tests/fase_11a_refinement_and_stream.rs`](../axon-rs/tests/fase_11a_refinement_and_stream.rs)
- Python unit tests: [`tests/test_fase_11a_trust.py`](../tests/test_fase_11a_trust.py) + [`tests/test_fase_11a_refinement_check.py`](../tests/test_fase_11a_refinement_check.py)
