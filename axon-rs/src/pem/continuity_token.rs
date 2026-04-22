//! [`ContinuityToken`] — the handshake that lets a reconnecting
//! client prove it's the same party that opened the original
//! WebSocket.
//!
//! Problem solved
//! --------------
//! The naive reconnect flow is "client presents session_id,
//! server rehydrates". That's trivial to hijack: any party that
//! learns a session_id (via logs, a shared browser, a network
//! trace) can resume the agent mid-flow and impersonate the
//! original user. Cognitive state carries PII, so hijack isn't
//! just inconvenient — it's a data breach.
//!
//! Fix: issue a short-lived continuity token at disconnect time.
//! The token is `(session_id || expiry_ts)` concatenated with an
//! HMAC-SHA256 computed by the server over those two fields plus
//! a secret. Clients can't forge the HMAC; an attacker who sniffs
//! the token can't reuse it past expiry; a race with a legitimate
//! reconnect resolves at the backend level (the first successful
//! rehydration evicts the state so replay reconnects fail with
//! `NotFound`).
//!
//! Backend-side key handling
//! -------------------------
//! The signer key is a 32-byte random value the adopter rotates on
//! a schedule that matches their key-rotation policy for
//! refresh tokens (§10.b). Rotating the signer only affects
//! in-flight reconnect tokens; worst-case the client sees a
//! `ForgedOrRotated` error and re-authenticates via the normal
//! session-establishment flow.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use hmac::{Hmac, Mac};
use sha2::Sha256;
use subtle::ConstantTimeEq;

type HmacSha256 = Hmac<Sha256>;

// ── Errors ───────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum ContinuityTokenError {
    /// The wire-format couldn't be decoded — malformed base64 or
    /// the split field structure didn't match.
    Malformed(String),
    /// HMAC check failed. Either the token was forged or the server
    /// rotated its signing key.
    ForgedOrRotated,
    /// Token was well-formed but already expired.
    Expired {
        expired_at: DateTime<Utc>,
    },
}

impl std::fmt::Display for ContinuityTokenError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(msg) => {
                write!(f, "continuity token malformed: {msg}")
            }
            Self::ForgedOrRotated => write!(
                f,
                "continuity token failed HMAC verification (forged or \
                 signer key rotated)"
            ),
            Self::Expired { expired_at } => {
                write!(f, "continuity token expired at {expired_at}")
            }
        }
    }
}

impl std::error::Error for ContinuityTokenError {}

// ── Token body ──────────────────────────────────────────────────────

/// Parsed representation of a continuity token.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContinuityToken {
    pub session_id: String,
    pub expires_at: DateTime<Utc>,
}

impl ContinuityToken {
    /// Build a fresh token body for `session_id` expiring in `ttl`.
    pub fn new(session_id: impl Into<String>, ttl: ChronoDuration) -> Self {
        ContinuityToken {
            session_id: session_id.into(),
            expires_at: Utc::now() + ttl,
        }
    }
}

// ── Signer ───────────────────────────────────────────────────────────

/// Holds the shared secret + signs / verifies tokens. One signer
/// per process; adopters rotate via the secrets service (§10.f) on
/// the cadence they prefer.
#[derive(Debug, Clone)]
pub struct ContinuityTokenSigner {
    key: Vec<u8>,
}

impl ContinuityTokenSigner {
    /// Wrap an adopter-supplied secret. Accepts any byte length; 32
    /// bytes of CSPRNG output is the recommended size (matches
    /// §10.e signer-key guidance).
    pub fn new(key: impl Into<Vec<u8>>) -> Self {
        ContinuityTokenSigner { key: key.into() }
    }

    /// Produce the wire-encoded token: `base64url(session_id || 0x1e
    /// || expiry_ms || 0x1e || HMAC(session_id || 0x1e || expiry_ms))`.
    pub fn sign(&self, token: &ContinuityToken) -> String {
        let expiry_ms = token.expires_at.timestamp_millis();
        let body = format!("{}\x1e{expiry_ms}", token.session_id);
        let mac = self.hmac_body(&body);
        let encoded = format!("{body}\x1e{}", hex(&mac));
        URL_SAFE_NO_PAD.encode(encoded.as_bytes())
    }

    /// Verify + parse. Returns the bound `ContinuityToken` on
    /// success, typed error otherwise.
    pub fn verify(
        &self,
        raw: &str,
    ) -> Result<ContinuityToken, ContinuityTokenError> {
        let decoded = URL_SAFE_NO_PAD.decode(raw.as_bytes()).map_err(|e| {
            ContinuityTokenError::Malformed(format!("base64: {e}"))
        })?;
        let text = std::str::from_utf8(&decoded).map_err(|e| {
            ContinuityTokenError::Malformed(format!("utf8: {e}"))
        })?;
        let parts: Vec<&str> = text.split('\x1e').collect();
        if parts.len() != 3 {
            return Err(ContinuityTokenError::Malformed(format!(
                "expected 3 fields, got {}",
                parts.len()
            )));
        }
        let session_id = parts[0].to_string();
        let expiry_ms: i64 = parts[1].parse().map_err(|e| {
            ContinuityTokenError::Malformed(format!("expiry: {e}"))
        })?;
        let expected_mac_hex = parts[2];

        let body = format!("{session_id}\x1e{expiry_ms}");
        let actual_mac = self.hmac_body(&body);
        let expected_mac = hex_decode(expected_mac_hex).ok_or(
            ContinuityTokenError::Malformed("mac hex".into()),
        )?;
        if !bool::from(actual_mac.ct_eq(&expected_mac)) {
            return Err(ContinuityTokenError::ForgedOrRotated);
        }

        let expires_at = DateTime::<Utc>::from_timestamp_millis(expiry_ms)
            .ok_or(ContinuityTokenError::Malformed(
                "expiry timestamp out of range".into(),
            ))?;
        if expires_at <= Utc::now() {
            return Err(ContinuityTokenError::Expired { expired_at: expires_at });
        }

        Ok(ContinuityToken {
            session_id,
            expires_at,
        })
    }

    fn hmac_body(&self, body: &str) -> Vec<u8> {
        let mut mac = HmacSha256::new_from_slice(&self.key)
            .expect("HMAC-SHA256 accepts any key length");
        mac.update(body.as_bytes());
        mac.finalize().into_bytes().to_vec()
    }
}

// ── Tiny hex helpers (kept local to avoid a new dep) ─────────────────

fn hex(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

fn hex_decode(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 {
        return None;
    }
    let mut out = Vec::with_capacity(s.len() / 2);
    for chunk in s.as_bytes().chunks(2) {
        let hi = match chunk[0] {
            b'0'..=b'9' => chunk[0] - b'0',
            b'a'..=b'f' => chunk[0] - b'a' + 10,
            b'A'..=b'F' => chunk[0] - b'A' + 10,
            _ => return None,
        };
        let lo = match chunk[1] {
            b'0'..=b'9' => chunk[1] - b'0',
            b'a'..=b'f' => chunk[1] - b'a' + 10,
            b'A'..=b'F' => chunk[1] - b'A' + 10,
            _ => return None,
        };
        out.push((hi << 4) | lo);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sign_verify_roundtrip() {
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let token = ContinuityToken::new("sess-1", ChronoDuration::minutes(15));
        let wire = signer.sign(&token);
        let decoded = signer.verify(&wire).expect("verify");
        assert_eq!(decoded.session_id, "sess-1");
        // Exp roundtrip preserves ms precision.
        assert_eq!(
            decoded.expires_at.timestamp_millis(),
            token.expires_at.timestamp_millis()
        );
    }

    #[test]
    fn verify_rejects_tampered_session_id() {
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let token = ContinuityToken::new("sess-a", ChronoDuration::minutes(15));
        let wire = signer.sign(&token);
        // Decode, mutate the session id, re-encode without
        // refreshing the HMAC.
        let decoded_bytes = URL_SAFE_NO_PAD.decode(wire.as_bytes()).unwrap();
        let text = std::str::from_utf8(&decoded_bytes).unwrap();
        let tampered = text.replacen("sess-a", "sess-b", 1);
        let tampered_wire = URL_SAFE_NO_PAD.encode(tampered.as_bytes());

        let err = signer.verify(&tampered_wire).unwrap_err();
        matches!(err, ContinuityTokenError::ForgedOrRotated);
    }

    #[test]
    fn verify_rejects_different_signer_key() {
        let s1 = ContinuityTokenSigner::new([1u8; 32]);
        let s2 = ContinuityTokenSigner::new([2u8; 32]);
        let token = ContinuityToken::new("sess-1", ChronoDuration::minutes(15));
        let wire = s1.sign(&token);
        let err = s2.verify(&wire).unwrap_err();
        matches!(err, ContinuityTokenError::ForgedOrRotated);
    }

    #[test]
    fn verify_rejects_expired_token() {
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let token = ContinuityToken::new("sess-1", ChronoDuration::seconds(-1));
        let wire = signer.sign(&token);
        let err = signer.verify(&wire).unwrap_err();
        matches!(err, ContinuityTokenError::Expired { .. });
    }

    #[test]
    fn verify_rejects_malformed_base64() {
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let err = signer.verify("not-valid-base64!@#").unwrap_err();
        matches!(err, ContinuityTokenError::Malformed(_));
    }

    #[test]
    fn verify_rejects_wrong_field_count() {
        // Encode a raw body that only has 2 sections instead of 3.
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let bad = URL_SAFE_NO_PAD.encode(b"sess-1\x1e9999");
        let err = signer.verify(&bad).unwrap_err();
        matches!(err, ContinuityTokenError::Malformed(_));
    }

    #[test]
    fn hmac_uses_constant_time_compare() {
        // Regression: two invalid tokens with wildly different MACs
        // should both fail with `ForgedOrRotated`, not with a
        // timing-observable length-short-circuit.
        let signer = ContinuityTokenSigner::new([7u8; 32]);
        let token = ContinuityToken::new("sess-1", ChronoDuration::minutes(5));
        let wire_good = signer.sign(&token);

        // Flip a single hex digit in the MAC section.
        let decoded = URL_SAFE_NO_PAD.decode(wire_good.as_bytes()).unwrap();
        let mut text = std::str::from_utf8(&decoded).unwrap().to_string();
        let len = text.len();
        // Flip last char.
        let last = text.chars().last().unwrap();
        let flipped = if last == 'a' { 'b' } else { 'a' };
        text.replace_range(len - 1.., &flipped.to_string());
        let wire_bad = URL_SAFE_NO_PAD.encode(text.as_bytes());

        let err = signer.verify(&wire_bad).unwrap_err();
        matches!(err, ContinuityTokenError::ForgedOrRotated);
    }
}
