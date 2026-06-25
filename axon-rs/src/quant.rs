//! §Fase 51.e — the `QuantBackend` port + the OSS reference simulator.
//!
//! This is the OSS half of the `quant` cognitive primitive's RUNTIME (the type
//! discipline shipped in §51.a–d.2 on the frontend). It defines:
//!
//!   - [`QuantBackend`] — the **port** (D1). Enterprise mounts the production
//!     QuIDD / VRAM / QPU engine behind this same trait (§51.f–i); the OSS crate
//!     ships only the reference implementation below.
//!   - [`ReferenceSimulator`] — a **genuinely usable** dense-statevector
//!     simulator over `f64` complex amplitudes, hard-capped at **n ≤ 10 qubits**
//!     (D = 2¹⁰ = 1024 amplitudes — the paper's `DensityMatrix[1024]` boundary).
//!     It actually executes small `quant` blocks on the CPU and serves as the
//!     differential-test ORACLE for the §51.f enterprise engine. Above the cap
//!     it returns [`QuantError::CapacityExceeded`] (`axon-E0783`) — never a
//!     silent OOM or a degraded result (D1, Option A).
//!
//! The reference simulator uses exact `f64` (NOT the enterprise Q32.32 /
//! purification arithmetic — that is §51.f). It is the oracle, not the
//! production path.
//!
//! **Norm invariant (D2, deferred from §51.b/c.3):** amplitude encoding asserts
//! the input carrier has unit L2 norm `‖x‖₂ = 1` ([`QuantError::NotNormalized`])
//! — the numeric realization the type system could not prove statically.

use std::f64::consts::PI;

// ── Minimal complex scalar (no external dep) ────────────────────────────────

/// A complex number `re + im·i` over `f64`. Just enough algebra for
/// statevector simulation (no `num-complex` dependency).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct C {
    pub re: f64,
    pub im: f64,
}

impl C {
    pub const ZERO: C = C { re: 0.0, im: 0.0 };
    pub const ONE: C = C { re: 1.0, im: 0.0 };
    /// The imaginary unit `i`.
    pub const I: C = C { re: 0.0, im: 1.0 };

    pub fn new(re: f64, im: f64) -> C {
        C { re, im }
    }
    pub fn real(re: f64) -> C {
        C { re, im: 0.0 }
    }
    pub fn conj(self) -> C {
        C { re: self.re, im: -self.im }
    }
    /// `|z|²` — the squared modulus.
    pub fn norm_sqr(self) -> f64 {
        self.re * self.re + self.im * self.im
    }
}

impl std::ops::Add for C {
    type Output = C;
    fn add(self, o: C) -> C {
        C { re: self.re + o.re, im: self.im + o.im }
    }
}
impl std::ops::Mul for C {
    type Output = C;
    fn mul(self, o: C) -> C {
        // (a+bi)(c+di) = (ac − bd) + (ad + bc)i
        C {
            re: self.re * o.re - self.im * o.im,
            im: self.re * o.im + self.im * o.re,
        }
    }
}
impl std::ops::Neg for C {
    type Output = C;
    fn neg(self) -> C {
        C { re: -self.re, im: -self.im }
    }
}

// ── Public surface types ────────────────────────────────────────────────────

/// The encoding scheme that maps a classical real vector into a Hilbert-space
/// state (paper §3.1; plan D2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EncodingScheme {
    /// d features → n = ⌈log₂ d⌉ qubits (exponential compression); requires a
    /// unit-norm input.
    Amplitude,
    /// d features → n = d qubits (one Ry rotation per feature); O(1) depth,
    /// robust to scale noise — no normalization requirement.
    Angle,
}

/// A pure quantum state — a dense statevector of `2ⁿ` complex amplitudes.
#[derive(Debug, Clone, PartialEq)]
pub struct StateVector {
    pub n: usize,
    pub amps: Vec<C>,
}

impl StateVector {
    /// The squared L2 norm `⟨ψ|ψ⟩` (should be ≈ 1 for a valid pure state).
    pub fn norm_sqr(&self) -> f64 {
        self.amps.iter().map(|a| a.norm_sqr()).sum()
    }
}

/// One layer of the hardware-efficient variational ansatz (paper §3.2):
/// a single-qubit `Ry(θ)·Rz(φ)` rotation per qubit, followed by a linear CNOT
/// entanglement chain (`U_ent`). `ry`/`rz` carry one angle per qubit.
#[derive(Debug, Clone)]
pub struct RotationLayer {
    pub ry: Vec<f64>,
    pub rz: Vec<f64>,
}

/// A parametric circuit `U(θ) = ∏ₗ (⊗ₖ Ry·Rz) · U_ent` (paper §3.2).
#[derive(Debug, Clone, Default)]
pub struct VariationalCircuit {
    pub layers: Vec<RotationLayer>,
}

/// A Pauli-sum observable `M = Σ cₖ Pₖ` (the runtime mirror of the frontend
/// `observable` declaration). Hermitian by construction (real coefficients).
#[derive(Debug, Clone, Default)]
pub struct PauliSum {
    /// `(coefficient, pauli_string)` — the string is over `{I, X, Y, Z}`, one
    /// char per qubit (char j ↦ qubit j).
    pub terms: Vec<(f64, String)>,
}

/// The closed catalogue of runtime errors. `code()` returns the stable
/// machine-readable diagnostic id.
#[derive(Debug, Clone, PartialEq)]
pub enum QuantError {
    /// `axon-E0783` — the requested register exceeds the backend capacity.
    CapacityExceeded { requested: usize, cap: usize },
    /// Amplitude encoding requires a unit-norm input (‖x‖₂ = 1).
    NotNormalized { norm: f64 },
    /// A shape mismatch (empty input, wrong rotation-vector / Pauli-string
    /// length for the register).
    DimensionMismatch { detail: String },
    /// A Pauli string carries a char outside `{I, X, Y, Z}`.
    BadPauli { pauli: String, bad: char },
}

impl QuantError {
    pub fn code(&self) -> &'static str {
        match self {
            QuantError::CapacityExceeded { .. } => "axon-E0783",
            QuantError::NotNormalized { .. } => "axon-E0788",
            QuantError::DimensionMismatch { .. } => "axon-E0789",
            QuantError::BadPauli { .. } => "axon-E0785",
        }
    }
}

impl std::fmt::Display for QuantError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            QuantError::CapacityExceeded { requested, cap } => write!(
                f,
                "axon-E0783 quant: capacity exceeded — requested {requested} qubits (D = 2^{requested}), \
                 the OSS reference simulator caps n ≤ {cap}; use an enterprise QuantBackend for larger registers."
            ),
            QuantError::NotNormalized { norm } => write!(
                f,
                "axon-E0788 quant: amplitude encoding requires a unit-norm input (‖x‖₂ = 1), got ‖x‖₂ = {norm:.6}."
            ),
            QuantError::DimensionMismatch { detail } => {
                write!(f, "axon-E0789 quant: dimension mismatch — {detail}")
            }
            QuantError::BadPauli { pauli, bad } => write!(
                f,
                "axon-E0785 quant: Pauli string '{pauli}' contains '{bad}' — the closed alphabet is {{I, X, Y, Z}}."
            ),
        }
    }
}

// ── The port ────────────────────────────────────────────────────────────────

/// §Fase 51.e — the algebraic-backend **port** (D1). The OSS crate ships the
/// [`ReferenceSimulator`]; the enterprise QuIDD / VRAM / QPU engine implements
/// the same trait (§51.f–i). A `quant` block's pipeline is `encode → evolve →
/// {measure | kernel}`.
pub trait QuantBackend {
    /// Maximum register width (qubits) this backend can realise.
    fn capacity(&self) -> usize;
    /// Project a classical real vector into a Hilbert-space state (§3.1).
    fn encode(&self, x: &[f64], scheme: EncodingScheme) -> Result<StateVector, QuantError>;
    /// Evolve a state under a parametric circuit `U(θ)` (§3.2).
    fn evolve(&self, state: StateVector, circuit: &VariationalCircuit) -> Result<StateVector, QuantError>;
    /// Expectation `E(θ) = ⟨ψ| M |ψ⟩` of a Pauli-sum observable (real, since M is
    /// Hermitian).
    fn measure(&self, state: &StateVector, observable: &PauliSum) -> Result<f64, QuantError>;
    /// Quantum-kernel overlap `K = |⟨ψ_a|ψ_b⟩|²` (§3.4, fidelity kernel).
    fn kernel(&self, a: &StateVector, b: &StateVector) -> Result<f64, QuantError>;
}

// ── The OSS reference simulator ─────────────────────────────────────────────

/// The default capacity cap for the OSS reference simulator: n ≤ 10 ⇒ D ≤ 1024
/// (the paper's `DensityMatrix[1024]` boundary). Above this, callers must use an
/// enterprise [`QuantBackend`].
pub const OSS_QUBIT_CAP: usize = 10;

/// Tolerance for the unit-norm assertion on amplitude-encoding input.
const NORM_TOL: f64 = 1e-9;

/// §Fase 51.e — a usable dense-statevector simulator over `f64` complex
/// amplitudes, capped at [`OSS_QUBIT_CAP`].
#[derive(Debug, Clone)]
pub struct ReferenceSimulator {
    cap: usize,
}

impl Default for ReferenceSimulator {
    fn default() -> Self {
        ReferenceSimulator { cap: OSS_QUBIT_CAP }
    }
}

impl ReferenceSimulator {
    pub fn new() -> Self {
        Self::default()
    }

    /// ⌈log₂ d⌉ via integer doubling (avoids float edge cases on exact powers).
    fn amplitude_qubits(d: usize) -> usize {
        let mut n = 0usize;
        while (1usize << n) < d {
            n += 1;
        }
        n
    }

    /// Apply a single-qubit gate `g` (row-major 2×2) to qubit `q`.
    fn apply_1q(amps: &mut [C], q: usize, g: [[C; 2]; 2]) {
        let bit = 1usize << q;
        for i in 0..amps.len() {
            if i & bit == 0 {
                let j = i | bit;
                let a0 = amps[i];
                let a1 = amps[j];
                amps[i] = g[0][0] * a0 + g[0][1] * a1;
                amps[j] = g[1][0] * a0 + g[1][1] * a1;
            }
        }
    }

    /// Apply CNOT(control `c`, target `t`).
    fn apply_cnot(amps: &mut [C], c: usize, t: usize) {
        let cb = 1usize << c;
        let tb = 1usize << t;
        for i in 0..amps.len() {
            if i & cb != 0 && i & tb == 0 {
                amps.swap(i, i | tb);
            }
        }
    }

    /// Apply one Pauli char to qubit `q` of `amps` in place.
    fn apply_pauli(amps: &mut [C], q: usize, p: char) -> Result<(), char> {
        let bit = 1usize << q;
        match p {
            'I' => {}
            'X' => {
                for i in 0..amps.len() {
                    if i & bit == 0 {
                        amps.swap(i, i | bit);
                    }
                }
            }
            'Z' => {
                for amp in amps.iter_mut().enumerate().filter(|(i, _)| i & bit != 0).map(|(_, a)| a) {
                    *amp = -*amp;
                }
            }
            'Y' => {
                // Y|0⟩ = i|1⟩, Y|1⟩ = −i|0⟩ ⇒ new[0] = −i·a1, new[1] = i·a0.
                for i in 0..amps.len() {
                    if i & bit == 0 {
                        let j = i | bit;
                        let a0 = amps[i];
                        let a1 = amps[j];
                        amps[i] = (-C::I) * a1;
                        amps[j] = C::I * a0;
                    }
                }
            }
            other => return Err(other),
        }
        Ok(())
    }

    /// ⟨a|b⟩ — the complex inner product.
    fn inner(a: &[C], b: &[C]) -> C {
        a.iter()
            .zip(b.iter())
            .fold(C::ZERO, |acc, (x, y)| acc + x.conj() * *y)
    }
}

impl QuantBackend for ReferenceSimulator {
    fn capacity(&self) -> usize {
        self.cap
    }

    fn encode(&self, x: &[f64], scheme: EncodingScheme) -> Result<StateVector, QuantError> {
        if x.is_empty() {
            return Err(QuantError::DimensionMismatch {
                detail: "empty input vector".to_string(),
            });
        }
        match scheme {
            EncodingScheme::Amplitude => {
                let n = Self::amplitude_qubits(x.len());
                if n > self.cap {
                    return Err(QuantError::CapacityExceeded { requested: n, cap: self.cap });
                }
                // Norm invariant (D2): amplitude encoding requires ‖x‖₂ = 1.
                let norm = x.iter().map(|v| v * v).sum::<f64>().sqrt();
                if (norm - 1.0).abs() > NORM_TOL {
                    return Err(QuantError::NotNormalized { norm });
                }
                let mut amps = vec![C::ZERO; 1usize << n];
                for (i, &v) in x.iter().enumerate() {
                    amps[i] = C::real(v);
                }
                Ok(StateVector { n, amps })
            }
            EncodingScheme::Angle => {
                let n = x.len();
                if n > self.cap {
                    return Err(QuantError::CapacityExceeded { requested: n, cap: self.cap });
                }
                // Product state ⊗ⱼ [cos(xⱼ/2), sin(xⱼ/2)] — inherently unit-norm.
                let mut amps = vec![C::ZERO; 1usize << n];
                for (idx, amp) in amps.iter_mut().enumerate() {
                    let mut coeff = 1.0f64;
                    for (q, &angle) in x.iter().enumerate() {
                        let bit = (idx >> q) & 1;
                        coeff *= if bit == 0 { (angle / 2.0).cos() } else { (angle / 2.0).sin() };
                    }
                    *amp = C::real(coeff);
                }
                Ok(StateVector { n, amps })
            }
        }
    }

    fn evolve(&self, mut state: StateVector, circuit: &VariationalCircuit) -> Result<StateVector, QuantError> {
        let n = state.n;
        for (li, layer) in circuit.layers.iter().enumerate() {
            if layer.ry.len() != n || layer.rz.len() != n {
                return Err(QuantError::DimensionMismatch {
                    detail: format!(
                        "layer {li} has {}/{} rotation angles but the register has {n} qubits",
                        layer.ry.len(),
                        layer.rz.len()
                    ),
                });
            }
            // Single-qubit Ry(θ)·Rz(φ) on each qubit.
            for q in 0..n {
                let ty = layer.ry[q];
                let ry = [
                    [C::real((ty / 2.0).cos()), C::real(-(ty / 2.0).sin())],
                    [C::real((ty / 2.0).sin()), C::real((ty / 2.0).cos())],
                ];
                Self::apply_1q(&mut state.amps, q, ry);
                let tz = layer.rz[q];
                let rz = [
                    [C::new((tz / 2.0).cos(), -(tz / 2.0).sin()), C::ZERO],
                    [C::ZERO, C::new((tz / 2.0).cos(), (tz / 2.0).sin())],
                ];
                Self::apply_1q(&mut state.amps, q, rz);
            }
            // Linear CNOT entanglement chain (U_ent).
            for q in 0..n.saturating_sub(1) {
                Self::apply_cnot(&mut state.amps, q, q + 1);
            }
        }
        Ok(state)
    }

    fn measure(&self, state: &StateVector, observable: &PauliSum) -> Result<f64, QuantError> {
        let n = state.n;
        let mut expectation = 0.0f64;
        for (coeff, pauli) in &observable.terms {
            if pauli.chars().count() != n {
                return Err(QuantError::DimensionMismatch {
                    detail: format!(
                        "Pauli string '{pauli}' spans {} qubit(s) but the state has {n}",
                        pauli.chars().count()
                    ),
                });
            }
            // φ = Pₖ|ψ⟩, then ⟨ψ|φ⟩ (real part — Pₖ is Hermitian).
            let mut phi = state.amps.clone();
            for (q, p) in pauli.chars().enumerate() {
                Self::apply_pauli(&mut phi, q, p)
                    .map_err(|bad| QuantError::BadPauli { pauli: pauli.clone(), bad })?;
            }
            expectation += coeff * Self::inner(&state.amps, &phi).re;
        }
        Ok(expectation)
    }

    fn kernel(&self, a: &StateVector, b: &StateVector) -> Result<f64, QuantError> {
        if a.n != b.n {
            return Err(QuantError::DimensionMismatch {
                detail: format!("kernel operands span {} vs {} qubits", a.n, b.n),
            });
        }
        Ok(Self::inner(&a.amps, &b.amps).norm_sqr())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: f64, b: f64) -> bool {
        (a - b).abs() < 1e-9
    }

    #[test]
    fn amplitude_qubits_is_ceil_log2() {
        assert_eq!(ReferenceSimulator::amplitude_qubits(1), 0);
        assert_eq!(ReferenceSimulator::amplitude_qubits(2), 1);
        assert_eq!(ReferenceSimulator::amplitude_qubits(3), 2);
        assert_eq!(ReferenceSimulator::amplitude_qubits(4), 2);
        assert_eq!(ReferenceSimulator::amplitude_qubits(1024), 10);
        assert_eq!(ReferenceSimulator::amplitude_qubits(1025), 11);
    }

    #[test]
    fn capacity_cap_is_enforced_with_e0783() {
        let sim = ReferenceSimulator::new();
        // 1025 features ⇒ n = 11 > 10.
        let x = vec![0.0; 1025];
        let err = sim.encode(&x, EncodingScheme::Amplitude).unwrap_err();
        assert!(matches!(err, QuantError::CapacityExceeded { requested: 11, cap: 10 }));
        assert_eq!(err.code(), "axon-E0783");
    }

    #[test]
    fn amplitude_encode_requires_unit_norm() {
        let sim = ReferenceSimulator::new();
        // ‖[0.6, 0.8]‖ = 1 → ok.
        let ok = sim.encode(&[0.6, 0.8], EncodingScheme::Amplitude).unwrap();
        assert_eq!(ok.n, 1);
        assert!(approx(ok.norm_sqr(), 1.0));
        // ‖[1, 1]‖ = √2 ≠ 1 → NotNormalized.
        let err = sim.encode(&[1.0, 1.0], EncodingScheme::Amplitude).unwrap_err();
        assert!(matches!(err, QuantError::NotNormalized { .. }));
        assert_eq!(err.code(), "axon-E0788");
    }

    #[test]
    fn angle_encode_is_unit_norm_product_state() {
        let sim = ReferenceSimulator::new();
        // x = [0] ⇒ |0⟩ : amps [1, 0].
        let s0 = sim.encode(&[0.0], EncodingScheme::Angle).unwrap();
        assert!(approx(s0.amps[0].re, 1.0) && approx(s0.amps[1].re, 0.0));
        // x = [π] ⇒ Ry(π)|0⟩ = |1⟩ : amps [0, 1].
        let s1 = sim.encode(&[PI], EncodingScheme::Angle).unwrap();
        assert!(approx(s1.amps[0].re, 0.0) && approx(s1.amps[1].re, 1.0));
        assert!(approx(s1.norm_sqr(), 1.0));
    }

    #[test]
    fn ry_pi_flips_zero_to_one() {
        let sim = ReferenceSimulator::new();
        // |0⟩ on one qubit (angle-encode x=[0]).
        let s = sim.encode(&[0.0], EncodingScheme::Angle).unwrap();
        let circuit = VariationalCircuit {
            layers: vec![RotationLayer { ry: vec![PI], rz: vec![0.0] }],
        };
        let out = sim.evolve(s, &circuit).unwrap();
        // |0⟩ —Ry(π)→ |1⟩ (up to global phase from Rz(0)=I).
        assert!(approx(out.amps[1].norm_sqr(), 1.0));
        assert!(approx(out.amps[0].norm_sqr(), 0.0));
    }

    #[test]
    fn measure_pauli_z_eigenvalues() {
        let sim = ReferenceSimulator::new();
        let z = PauliSum { terms: vec![(1.0, "Z".to_string())] };
        // ⟨Z⟩ on |0⟩ = +1.
        let s0 = sim.encode(&[0.0], EncodingScheme::Angle).unwrap();
        assert!(approx(sim.measure(&s0, &z).unwrap(), 1.0));
        // ⟨Z⟩ on |1⟩ = −1.
        let s1 = sim.encode(&[PI], EncodingScheme::Angle).unwrap();
        assert!(approx(sim.measure(&s1, &z).unwrap(), -1.0));
    }

    #[test]
    fn measure_zz_on_two_qubits() {
        let sim = ReferenceSimulator::new();
        let zz = PauliSum { terms: vec![(1.0, "ZZ".to_string())] };
        // |00⟩ ⇒ ⟨ZZ⟩ = (+1)(+1) = +1.
        let s00 = sim.encode(&[0.0, 0.0], EncodingScheme::Angle).unwrap();
        assert!(approx(sim.measure(&s00, &zz).unwrap(), 1.0));
        // |01⟩ (qubit0=1, qubit1=0) ⇒ ⟨ZZ⟩ = (−1)(+1) = −1.
        let s01 = sim.encode(&[PI, 0.0], EncodingScheme::Angle).unwrap();
        assert!(approx(sim.measure(&s01, &zz).unwrap(), -1.0));
    }

    #[test]
    fn measure_rejects_wrong_length_pauli() {
        let sim = ReferenceSimulator::new();
        let s = sim.encode(&[0.0, 0.0], EncodingScheme::Angle).unwrap(); // 2 qubits
        let bad = PauliSum { terms: vec![(1.0, "Z".to_string())] }; // 1 char
        assert!(matches!(sim.measure(&s, &bad), Err(QuantError::DimensionMismatch { .. })));
    }

    #[test]
    fn measure_rejects_bad_pauli_alphabet() {
        let sim = ReferenceSimulator::new();
        let s = sim.encode(&[0.0], EncodingScheme::Angle).unwrap();
        let bad = PauliSum { terms: vec![(1.0, "K".to_string())] };
        let err = sim.measure(&s, &bad).unwrap_err();
        assert!(matches!(err, QuantError::BadPauli { bad: 'K', .. }));
    }

    #[test]
    fn kernel_fidelity_identical_and_orthogonal() {
        let sim = ReferenceSimulator::new();
        let a = sim.encode(&[0.6, 0.8], EncodingScheme::Amplitude).unwrap();
        // |⟨ψ|ψ⟩|² = 1.
        assert!(approx(sim.kernel(&a, &a).unwrap(), 1.0));
        // Orthogonal: [1,0] vs [0,1] ⇒ 0.
        let e0 = sim.encode(&[1.0, 0.0], EncodingScheme::Amplitude).unwrap();
        let e1 = sim.encode(&[0.0, 1.0], EncodingScheme::Amplitude).unwrap();
        assert!(approx(sim.kernel(&e0, &e1).unwrap(), 0.0));
    }

    #[test]
    fn cnot_entangles_for_bell_correlation() {
        // |00⟩ —Ry(π) on q0→ |10⟩ —CNOT(0,1)→ |11⟩. Then ⟨ZZ⟩ = (−1)(−1) = +1.
        let sim = ReferenceSimulator::new();
        let s = sim.encode(&[0.0, 0.0], EncodingScheme::Angle).unwrap();
        let circuit = VariationalCircuit {
            layers: vec![RotationLayer { ry: vec![PI, 0.0], rz: vec![0.0, 0.0] }],
        };
        let out = sim.evolve(s, &circuit).unwrap();
        let zz = PauliSum { terms: vec![(1.0, "ZZ".to_string())] };
        assert!(approx(sim.measure(&out, &zz).unwrap(), 1.0), "post-CNOT |11⟩ ⇒ ⟨ZZ⟩ = +1");
    }
}
