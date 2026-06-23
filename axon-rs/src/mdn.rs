//! §Fase 62.B — Multi-Document Navigation (MDN).
//!
//! A faithful implementation of `docs/papers/paper_multi_document.md`: a document
//! corpus as a **labeled directed graph** `C = (D, R, τ, ω, σ)`, navigated by
//! relationship rather than by embedding similarity. This module ships **§62.B.1
//! — the corpus graph + signed Epistemic PageRank (EPR)**, the paper's most
//! distinctive result.
//!
//! # Signed Epistemic PageRank (paper §2.3, Def 4.2, Theorem 3)
//!
//! The corpus is decomposed by edge polarity into a *trust* subgraph `G⁺`
//! (`cite`, `elaborate`, `corroborate`) and a *distrust* subgraph `G⁻`
//! (`contradict`, `supersede`). On each we compute a PageRank-style stationary
//! distribution by power iteration
//!
//! ```text
//! EPR⁺ = (1-d)·u⁺ + d·(P⁺)ᵀ·EPR⁺      (trust propagation)
//! EPR⁻ = (1-d)·u⁻ + d·(P⁻)ᵀ·EPR⁻      (distrust propagation)
//! ```
//!
//! with row-stochastic `P⁺/P⁻` (dangling rows replaced by uniform, paper P4) and
//! **asymmetric** teleportation (`u⁺ ∝ 1/depth` — primary sources; `u⁻ ∝
//! recency` — corrections arrive late). The net epistemic reputation is
//!
//! ```text
//! EPR(Dᵢ) = EPR⁺(Dᵢ) - λ·EPR⁻(Dᵢ)
//! ```
//!
//! By Perron–Frobenius (Theorem 3) each of `EPR⁺`, `EPR⁻` exists, is unique and
//! strictly positive, and the power iteration converges geometrically. Unlike a
//! standard PageRank, `EPR` is a **signed reputation** — it may be negative for a
//! document more contested than endorsed (paper §2.3 WARNING), and it sums to
//! `1 - λ`, not 1. The property tests below verify each of these.
//!
//! Embeddings-free throughout (program invariant #1).

use std::collections::HashMap;

/// Stable identifier of a document within a [`Corpus`].
pub type DocId = u32;

/// The relationship a directed edge encodes (paper Def 2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EdgeType {
    Cite,
    Elaborate,
    Corroborate,
    Depend,
    Implement,
    Exemplify,
    Contradict,
    Supersede,
}

/// The epistemic polarity of an edge type — which signed subgraph it joins
/// (paper Def 4). `Neutral` edges (`depend`/`implement`/`exemplify`) are
/// structural but propagate neither trust nor distrust, so they sit in neither
/// `G⁺` nor `G⁻`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Polarity {
    Positive,
    Negative,
    Neutral,
}

impl EdgeType {
    /// The signed subgraph membership of this edge type (paper Def 4).
    pub fn polarity(self) -> Polarity {
        match self {
            EdgeType::Cite | EdgeType::Elaborate | EdgeType::Corroborate => Polarity::Positive,
            EdgeType::Contradict | EdgeType::Supersede => Polarity::Negative,
            EdgeType::Depend | EdgeType::Implement | EdgeType::Exemplify => Polarity::Neutral,
        }
    }
}

/// A labeled, weighted directed edge `(Dᵢ, Dⱼ, τ)` with weight `ω ∈ (0, 1]`.
#[derive(Debug, Clone)]
pub struct Edge {
    pub from: DocId,
    pub to: DocId,
    pub etype: EdgeType,
    /// `ω(r) ∈ (0, 1]` — relationship strength (paper Def 3, G4).
    pub weight: f64,
}

/// A corpus document `Dᵢ` with the structural priors the asymmetric
/// teleportation needs.
#[derive(Debug, Clone)]
pub struct Document {
    pub id: DocId,
    pub title: String,
    /// Dependency depth from the corpus roots — primary sources have small
    /// depth. Drives the trust teleportation prior `u⁺ ∝ 1/(depth+1)`.
    pub depth: u32,
    /// Recency in `[0, 1]` (1 = newest). Drives the distrust teleportation prior
    /// `u⁻ ∝ recency` (corrections/errata arrive late).
    pub recency: f64,
    /// The document's epistemic status `σ(Dᵢ)` (lattice level slug).
    pub epistemic: String,
}

/// A document corpus graph `C = (D, R, τ, ω, σ)` (paper Def 1).
#[derive(Debug, Clone)]
pub struct Corpus {
    docs: HashMap<DocId, Document>,
    edges: Vec<Edge>,
}

/// Why a node/edge set fails to form a valid corpus (paper G2/G4).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CorpusError {
    /// An edge references a document not in `D` (G2).
    UnknownEndpoint(DocId),
    /// An edge weight is outside `(0, 1]` (G4).
    BadWeight(DocId, DocId),
    /// The corpus has no documents.
    Empty,
}

impl Corpus {
    /// Build + validate a corpus: every edge connects corpus members (G2) and
    /// carries a weight `ω ∈ (0, 1]` (G4).
    pub fn new(docs: Vec<Document>, edges: Vec<Edge>) -> Result<Self, CorpusError> {
        if docs.is_empty() {
            return Err(CorpusError::Empty);
        }
        let map: HashMap<DocId, Document> = docs.into_iter().map(|d| (d.id, d)).collect();
        for e in &edges {
            if !map.contains_key(&e.from) {
                return Err(CorpusError::UnknownEndpoint(e.from));
            }
            if !map.contains_key(&e.to) {
                return Err(CorpusError::UnknownEndpoint(e.to));
            }
            if !(e.weight > 0.0 && e.weight <= 1.0) {
                return Err(CorpusError::BadWeight(e.from, e.to));
            }
        }
        Ok(Corpus { docs: map, edges })
    }

    /// `|D|`.
    pub fn len(&self) -> usize {
        self.docs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.docs.is_empty()
    }

    pub fn document(&self, id: DocId) -> Option<&Document> {
        self.docs.get(&id)
    }

    pub fn edges(&self) -> &[Edge] {
        &self.edges
    }

    /// Document ids in ascending order — a deterministic index ordering for the
    /// EPR vectors.
    fn ordered_ids(&self) -> Vec<DocId> {
        let mut ids: Vec<DocId> = self.docs.keys().copied().collect();
        ids.sort_unstable();
        ids
    }
}

/// Parameters of the signed Epistemic PageRank (paper Def 4.2).
#[derive(Debug, Clone)]
pub struct EprParams {
    /// Damping `d ∈ (0, 1)` — must be strict for Perron–Frobenius (Theorem 3).
    pub damping: f64,
    /// Distrust penalty `λ ∈ [0, 1]` weighting `EPR⁻` in the net `EPR`.
    pub lambda: f64,
    /// Convergence tolerance on the L1 change between iterations.
    pub tolerance: f64,
    /// Iteration cap (a safety bound; convergence is geometric).
    pub max_iter: usize,
}

impl Default for EprParams {
    fn default() -> Self {
        EprParams { damping: 0.85, lambda: 0.5, tolerance: 1e-10, max_iter: 200 }
    }
}

/// The result of an EPR computation (paper Def 4.2).
#[derive(Debug, Clone)]
pub struct EprResult {
    /// Net signed reputation `EPR = EPR⁺ - λ·EPR⁻` per document. May be negative.
    pub epr: HashMap<DocId, f64>,
    /// Trust distribution `EPR⁺` (sums to 1, strictly positive).
    pub epr_plus: HashMap<DocId, f64>,
    /// Distrust distribution `EPR⁻` (sums to 1, strictly positive).
    pub epr_minus: HashMap<DocId, f64>,
    /// Iterations the trust channel took to converge.
    pub iterations: usize,
}

/// Build a row-stochastic transition matrix for the edges of a given polarity,
/// in `ordered_ids` index space. `mat[j]` is the (target-index, prob) list for
/// source index `j`; a source with no out-edges of this polarity is *dangling*
/// and is flagged (its row is treated as uniform `1/n` — paper P4).
fn build_transition(
    corpus: &Corpus,
    ids: &[DocId],
    polarity: Polarity,
) -> (Vec<Vec<(usize, f64)>>, Vec<bool>) {
    let index: HashMap<DocId, usize> = ids.iter().enumerate().map(|(i, &id)| (id, i)).collect();
    let n = ids.len();
    // Accumulate out-weights per source over edges of the requested polarity.
    let mut out: Vec<Vec<(usize, f64)>> = vec![Vec::new(); n];
    let mut row_sum: Vec<f64> = vec![0.0; n];
    for e in &corpus.edges {
        if e.etype.polarity() != polarity {
            continue;
        }
        let (j, i) = (index[&e.from], index[&e.to]);
        out[j].push((i, e.weight));
        row_sum[j] += e.weight;
    }
    // Normalize each non-dangling row to sum 1 (row-stochastic, P1-P3).
    let mut dangling = vec![false; n];
    for j in 0..n {
        if row_sum[j] > 0.0 {
            for (_, w) in out[j].iter_mut() {
                *w /= row_sum[j];
            }
        } else {
            dangling[j] = true; // P4 — handled as uniform during iteration.
        }
    }
    (out, dangling)
}

/// One power-iteration fixed point `x = (1-d)·u + d·Pᵀ·x` with dangling mass
/// redistributed uniformly (paper P4). Returns `(x, iterations)`. `u` must be a
/// strictly-positive distribution (Perron–Frobenius requirement).
fn power_iterate(
    transition: &[Vec<(usize, f64)>],
    dangling: &[bool],
    u: &[f64],
    params: &EprParams,
) -> (Vec<f64>, usize) {
    let n = u.len();
    if n == 0 {
        return (Vec::new(), 0);
    }
    let d = params.damping;
    let mut x = vec![1.0 / n as f64; n];
    let mut iters = 0;
    for _ in 0..params.max_iter {
        iters += 1;
        // Dangling mass: a dangling source distributes its rank uniformly.
        let dangling_mass: f64 =
            (0..n).filter(|&j| dangling[j]).map(|j| x[j]).sum::<f64>() * d / n as f64;
        let mut next = vec![0.0_f64; n];
        for i in 0..n {
            next[i] = (1.0 - d) * u[i] + dangling_mass;
        }
        // d · (P)ᵀ · x : each source j pushes its rank along its out-edges.
        for (j, row) in transition.iter().enumerate() {
            if row.is_empty() {
                continue;
            }
            let xj = x[j] * d;
            for &(i, p) in row {
                next[i] += xj * p;
            }
        }
        let delta: f64 = (0..n).map(|i| (next[i] - x[i]).abs()).sum();
        x = next;
        if delta < params.tolerance {
            break;
        }
    }
    (x, iters)
}

/// Normalize a non-negative weight vector to a strictly-positive distribution on
/// the simplex (Perron–Frobenius needs `u > 0`). An all-zero input falls back to
/// uniform; otherwise a tiny ε floor keeps every entry strictly positive.
fn teleportation(weights: &[f64]) -> Vec<f64> {
    let n = weights.len();
    if n == 0 {
        return Vec::new();
    }
    const EPS: f64 = 1e-9;
    let floored: Vec<f64> = weights.iter().map(|&w| w.max(0.0) + EPS).collect();
    let sum: f64 = floored.iter().sum();
    floored.iter().map(|&w| w / sum).collect()
}

/// Compute the signed **Epistemic PageRank** of a corpus (paper Def 4.2,
/// Theorem 3). Embeddings-free.
pub fn epistemic_pagerank(corpus: &Corpus, params: &EprParams) -> EprResult {
    let ids = corpus.ordered_ids();
    let n = ids.len();

    // Asymmetric teleportation: trust ∝ 1/(depth+1); distrust ∝ recency.
    let u_plus: Vec<f64> = teleportation(
        &ids.iter()
            .map(|id| 1.0 / (corpus.docs[id].depth as f64 + 1.0))
            .collect::<Vec<_>>(),
    );
    let u_minus: Vec<f64> = teleportation(
        &ids.iter().map(|id| corpus.docs[id].recency).collect::<Vec<_>>(),
    );

    let (p_plus, dangle_plus) = build_transition(corpus, &ids, Polarity::Positive);
    let (p_minus, dangle_minus) = build_transition(corpus, &ids, Polarity::Negative);

    let (epr_plus_v, iters) = power_iterate(&p_plus, &dangle_plus, &u_plus, params);
    let (epr_minus_v, _) = power_iterate(&p_minus, &dangle_minus, &u_minus, params);

    let mut epr_plus = HashMap::with_capacity(n);
    let mut epr_minus = HashMap::with_capacity(n);
    let mut epr = HashMap::with_capacity(n);
    for (k, &id) in ids.iter().enumerate() {
        let p = epr_plus_v[k];
        let m = epr_minus_v[k];
        epr_plus.insert(id, p);
        epr_minus.insert(id, m);
        epr.insert(id, p - params.lambda * m);
    }

    EprResult { epr, epr_plus, epr_minus, iterations: iters }
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn doc(id: DocId, depth: u32, recency: f64) -> Document {
        Document {
            id,
            title: format!("D{id}"),
            depth,
            recency,
            epistemic: "believe".into(),
        }
    }

    fn edge(from: DocId, to: DocId, etype: EdgeType, weight: f64) -> Edge {
        Edge { from, to, etype, weight }
    }

    fn sum(m: &HashMap<DocId, f64>) -> f64 {
        m.values().sum()
    }

    // ── Polarity / construction ──────────────────────────────────────────────

    #[test]
    fn edge_polarity_matches_the_paper_decomposition() {
        assert_eq!(EdgeType::Cite.polarity(), Polarity::Positive);
        assert_eq!(EdgeType::Corroborate.polarity(), Polarity::Positive);
        assert_eq!(EdgeType::Contradict.polarity(), Polarity::Negative);
        assert_eq!(EdgeType::Supersede.polarity(), Polarity::Negative);
        assert_eq!(EdgeType::Depend.polarity(), Polarity::Neutral);
    }

    #[test]
    fn corpus_rejects_unknown_endpoint_and_bad_weight() {
        let docs = vec![doc(1, 0, 0.5), doc(2, 1, 0.5)];
        assert_eq!(
            Corpus::new(docs.clone(), vec![edge(1, 9, EdgeType::Cite, 0.5)]).unwrap_err(),
            CorpusError::UnknownEndpoint(9)
        );
        assert_eq!(
            Corpus::new(docs, vec![edge(1, 2, EdgeType::Cite, 1.5)]).unwrap_err(),
            CorpusError::BadWeight(1, 2)
        );
        assert_eq!(Corpus::new(vec![], vec![]).unwrap_err(), CorpusError::Empty);
    }

    // ── Signed EPR — the Perron–Frobenius guarantees ─────────────────────────

    #[test]
    fn epr_plus_and_minus_are_strictly_positive_distributions() {
        // A small citation chain + one contradiction.
        let docs = vec![doc(1, 0, 0.1), doc(2, 1, 0.3), doc(3, 2, 0.9)];
        let edges = vec![
            edge(2, 1, EdgeType::Cite, 0.9),
            edge(3, 1, EdgeType::Cite, 0.8),
            edge(3, 2, EdgeType::Contradict, 0.7),
        ];
        let c = Corpus::new(docs, edges).unwrap();
        let r = epistemic_pagerank(&c, &EprParams::default());

        // Each channel is a distribution (sums to 1) and strictly positive
        // (Perron–Frobenius).
        assert!((sum(&r.epr_plus) - 1.0).abs() < 1e-6, "EPR⁺ sums to 1");
        assert!((sum(&r.epr_minus) - 1.0).abs() < 1e-6, "EPR⁻ sums to 1");
        assert!(r.epr_plus.values().all(|&v| v > 0.0), "EPR⁺ strictly positive");
        assert!(r.epr_minus.values().all(|&v| v > 0.0), "EPR⁻ strictly positive");
    }

    #[test]
    fn net_epr_sums_to_one_minus_lambda() {
        let docs = vec![doc(1, 0, 0.1), doc(2, 1, 0.5)];
        let edges = vec![edge(2, 1, EdgeType::Cite, 0.9)];
        let c = Corpus::new(docs, edges).unwrap();
        let params = EprParams { lambda: 0.5, ..EprParams::default() };
        let r = epistemic_pagerank(&c, &params);
        // EPR = EPR⁺ - λ·EPR⁻ ⇒ Σ EPR = 1 - λ (paper §2.3 WARNING).
        assert!((sum(&r.epr) - (1.0 - params.lambda)).abs() < 1e-6);
    }

    #[test]
    fn a_heavily_cited_document_outranks_an_uncited_one() {
        // D1 is cited by D2 and D3; D4 is cited by nobody.
        let docs = vec![doc(1, 0, 0.1), doc(2, 1, 0.5), doc(3, 1, 0.5), doc(4, 1, 0.5)];
        let edges = vec![
            edge(2, 1, EdgeType::Cite, 0.9),
            edge(3, 1, EdgeType::Cite, 0.9),
        ];
        let c = Corpus::new(docs, edges).unwrap();
        let r = epistemic_pagerank(&c, &EprParams::default());
        assert!(
            r.epr_plus[&1] > r.epr_plus[&4],
            "the cited D1 ({}) must outrank the uncited D4 ({})",
            r.epr_plus[&1],
            r.epr_plus[&4]
        );
    }

    #[test]
    fn a_contested_document_can_have_negative_net_epr() {
        // D1 is lightly cited but heavily contradicted ⇒ more contested than
        // endorsed ⇒ negative net EPR (paper §2.3 WARNING — a meaningful signal
        // a probability distribution cannot express).
        let docs = vec![doc(1, 0, 0.9), doc(2, 1, 0.1), doc(3, 1, 0.1), doc(4, 1, 0.1)];
        let edges = vec![
            edge(2, 1, EdgeType::Cite, 0.1),
            edge(2, 1, EdgeType::Contradict, 1.0),
            edge(3, 1, EdgeType::Contradict, 1.0),
            edge(4, 1, EdgeType::Contradict, 1.0),
        ];
        let c = Corpus::new(docs, edges).unwrap();
        let params = EprParams { lambda: 1.0, ..EprParams::default() };
        let r = epistemic_pagerank(&c, &params);
        assert!(
            r.epr[&1] < 0.0,
            "a heavily-contradicted, lightly-cited doc has negative EPR: {}",
            r.epr[&1]
        );
    }

    #[test]
    fn power_iteration_converges_well_within_the_cap() {
        let docs = vec![doc(1, 0, 0.1), doc(2, 1, 0.5), doc(3, 2, 0.9)];
        let edges = vec![
            edge(2, 1, EdgeType::Cite, 0.9),
            edge(3, 2, EdgeType::Cite, 0.8),
        ];
        let c = Corpus::new(docs, edges).unwrap();
        let params = EprParams::default();
        let r = epistemic_pagerank(&c, &params);
        assert!(r.iterations < params.max_iter, "converged before the cap (geometric)");
        assert!(r.iterations > 0);
    }

    #[test]
    fn dangling_nodes_keep_epr_a_proper_distribution() {
        // D1 has NO outgoing positive edges (dangling in G⁺). The uniform-row
        // treatment (P4) must keep EPR⁺ summing to 1.
        let docs = vec![doc(1, 0, 0.1), doc(2, 1, 0.5)];
        let edges = vec![edge(2, 1, EdgeType::Cite, 0.9)];
        let c = Corpus::new(docs, edges).unwrap();
        let r = epistemic_pagerank(&c, &EprParams::default());
        assert!((sum(&r.epr_plus) - 1.0).abs() < 1e-6, "dangling handled, still a distribution");
    }

    #[test]
    fn single_document_corpus_is_well_defined() {
        let c = Corpus::new(vec![doc(1, 0, 0.5)], vec![]).unwrap();
        let r = epistemic_pagerank(&c, &EprParams::default());
        assert!((r.epr_plus[&1] - 1.0).abs() < 1e-9, "the lone doc holds all trust mass");
    }
}
