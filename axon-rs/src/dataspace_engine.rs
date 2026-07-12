//! §Fase 108.b — the deterministic columnar engine behind `dataspace`.
//!
//! The physical store the data-plane verbs operate on (`ingest` §108.c;
//! `focus`/`aggregate`/`associate`/`explore` §108.d). First-party by
//! decision (D108.6-adjacent): the Arrow-class memory *layout* is what
//! buys correctness + scan performance, not the Arrow ecosystem — the
//! same posture as `ooxml.rs` (§99) and `idpe.rs` (§101).
//!
//! # The model (plan §5.1)
//!
//! A dataspace with schema `S = ⟨(name₁,T₁), …, (nameₖ,Tₖ)⟩` holds an
//! ordered sequence of **immutable record batches** (append-only,
//! D108.2 — the analytical dual of `axonstore`'s transactional rows).
//! A batch is `B = ⟨S, {A₁, …, Aₖ}, N, π_B⟩` with `N` the common
//! logical length, `π_B` the provenance stamp, and each column array:
//!
//! - **validity bitmap** `M ∈ {0,1}^⌈N/8⌉` — bit i = element i present.
//!   Nulls are structural; there are NO sentinel values.
//! - **fixed-width buffer** (Int/Float/Timestamp: 8 bytes/element;
//!   Bool: bit-packed) — element i at offset i·w.
//! - **variable-width** (Text/Json): offsets `O ∈ ℤ₊^{N+1}`, monotone,
//!   `O[0] = 0`, `O[N] = |bytes|`; element i = `bytes[O[i]..O[i+1])`.
//!
//! Every invariant is checked ONCE, at construction — a constructed
//! batch is immutable and never re-validated on read.
//!
//! # Zone maps (plan §5.3)
//!
//! Each column of each batch carries `[min, max]` + null-count,
//! computed at construction. §108.d's interval abstraction `φ̂` prunes
//! a batch only when the predicate is provably false over the zone —
//! sound by construction (a skipped batch contains no matching row);
//! completeness is not claimed.
//!
//! # Provenance (plan §5.4)
//!
//! Every batch is stamped at ingest: source + sha256 + declared-time +
//! [`crate::emcp::EpistemicTaint`] (born `Untrusted`, §98 — external
//! data never enters trusted). Query results take the MEET over the
//! batches they touched; no data-plane operation can raise a status.

use std::collections::HashMap;

use crate::emcp::EpistemicTaint;

// ─────────────────────────────────────────────────────────────────────
//  Column types (the D108.1 closed catalog, canonical spellings)
// ─────────────────────────────────────────────────────────────────────

/// The engine-side mirror of the frontend's closed catalog
/// (`DataspaceColumnType`, D108.1). Constructed from the CANONICAL
/// names the IR carries (`visit_dataspace` resolves aliases at IR
/// generation) — an unknown spelling here means a stale or hand-edited
/// artifact, and fails CLOSED.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ColumnType {
    Text,
    Int,
    Float,
    Bool,
    Timestamp,
    Json,
}

impl ColumnType {
    pub fn from_canonical(name: &str) -> Option<ColumnType> {
        match name {
            "Text" => Some(ColumnType::Text),
            "Int" => Some(ColumnType::Int),
            "Float" => Some(ColumnType::Float),
            "Bool" => Some(ColumnType::Bool),
            "Timestamp" => Some(ColumnType::Timestamp),
            "Json" => Some(ColumnType::Json),
            _ => None,
        }
    }

    pub fn canonical_name(self) -> &'static str {
        match self {
            ColumnType::Text => "Text",
            ColumnType::Int => "Int",
            ColumnType::Float => "Float",
            ColumnType::Bool => "Bool",
            ColumnType::Timestamp => "Timestamp",
            ColumnType::Json => "Json",
        }
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Validity bitmap helpers
// ─────────────────────────────────────────────────────────────────────

#[inline]
fn bitmap_len(n: usize) -> usize {
    n.div_ceil(8)
}

#[inline]
fn bitmap_get(bits: &[u8], i: usize) -> bool {
    (bits[i / 8] >> (i % 8)) & 1 == 1
}

#[inline]
fn bitmap_set(bits: &mut [u8], i: usize) {
    bits[i / 8] |= 1 << (i % 8);
}

// ─────────────────────────────────────────────────────────────────────
//  Column arrays
// ─────────────────────────────────────────────────────────────────────

/// The typed physical buffers of one column. Null slots in fixed-width
/// buffers hold a zero placeholder — NEVER read (the validity bitmap is
/// the single source of presence; there are no sentinel values).
#[derive(Debug, Clone)]
pub enum ColumnData {
    Int(Vec<i64>),
    Float(Vec<f64>),
    /// Bit-packed, `⌈N/8⌉` bytes.
    Bool(Vec<u8>),
    /// Epoch **microseconds** (i64) — one instant encoding, no strings.
    Timestamp(Vec<i64>),
    Text { offsets: Vec<u64>, bytes: Vec<u8> },
    Json { offsets: Vec<u64>, bytes: Vec<u8> },
}

impl ColumnData {
    pub fn column_type(&self) -> ColumnType {
        match self {
            ColumnData::Int(_) => ColumnType::Int,
            ColumnData::Float(_) => ColumnType::Float,
            ColumnData::Bool(_) => ColumnType::Bool,
            ColumnData::Timestamp(_) => ColumnType::Timestamp,
            ColumnData::Text { .. } => ColumnType::Text,
            ColumnData::Json { .. } => ColumnType::Json,
        }
    }
}

/// One immutable column array: validity bitmap + typed buffers.
/// Constructed only through [`ColumnBuilder`] (which enforces the §5.1
/// invariants) or [`ColumnArray::validated`] (which re-checks them).
#[derive(Debug, Clone)]
pub struct ColumnArray {
    len: usize,
    validity: Vec<u8>,
    data: ColumnData,
}

impl ColumnArray {
    /// Construct from raw parts, RE-CHECKING every §5.1 invariant.
    /// The engine's constructors go through [`ColumnBuilder`]; this
    /// exists for deserialization paths (108.e persistence) where the
    /// parts arrive from outside the process boundary.
    pub fn validated(len: usize, validity: Vec<u8>, data: ColumnData) -> Result<Self, String> {
        if validity.len() != bitmap_len(len) {
            return Err(format!(
                "validity bitmap is {} bytes; a column of length {len} requires exactly {}",
                validity.len(),
                bitmap_len(len)
            ));
        }
        match &data {
            ColumnData::Int(v) | ColumnData::Timestamp(v) => {
                if v.len() != len {
                    return Err(format!(
                        "fixed-width buffer holds {} elements; the column declares {len}",
                        v.len()
                    ));
                }
            }
            ColumnData::Float(v) => {
                if v.len() != len {
                    return Err(format!(
                        "fixed-width buffer holds {} elements; the column declares {len}",
                        v.len()
                    ));
                }
            }
            ColumnData::Bool(v) => {
                if v.len() != bitmap_len(len) {
                    return Err(format!(
                        "bit-packed Bool buffer is {} bytes; length {len} requires {}",
                        v.len(),
                        bitmap_len(len)
                    ));
                }
            }
            ColumnData::Text { offsets, bytes } | ColumnData::Json { offsets, bytes } => {
                if offsets.len() != len + 1 {
                    return Err(format!(
                        "offset buffer holds {} entries; a column of length {len} requires {}",
                        offsets.len(),
                        len + 1
                    ));
                }
                if offsets.first() != Some(&0) {
                    return Err("offset buffer must start at 0".to_string());
                }
                if offsets.windows(2).any(|w| w[0] > w[1]) {
                    return Err("offset buffer must be monotone non-decreasing".to_string());
                }
                if offsets.last().copied() != Some(bytes.len() as u64) {
                    return Err(format!(
                        "final offset {} must equal the raw byte buffer length {}",
                        offsets.last().copied().unwrap_or(0),
                        bytes.len()
                    ));
                }
            }
        }
        Ok(ColumnArray {
            len,
            validity,
            data,
        })
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn column_type(&self) -> ColumnType {
        self.data.column_type()
    }

    /// Presence of element `i` — the validity bitmap is the single
    /// source of truth.
    pub fn is_valid(&self, i: usize) -> bool {
        i < self.len && bitmap_get(&self.validity, i)
    }

    pub fn null_count(&self) -> usize {
        (0..self.len).filter(|&i| !self.is_valid(i)).count()
    }

    pub fn get_int(&self, i: usize) -> Option<i64> {
        if !self.is_valid(i) {
            return None;
        }
        match &self.data {
            ColumnData::Int(v) | ColumnData::Timestamp(v) => Some(v[i]),
            _ => None,
        }
    }

    pub fn get_float(&self, i: usize) -> Option<f64> {
        if !self.is_valid(i) {
            return None;
        }
        match &self.data {
            ColumnData::Float(v) => Some(v[i]),
            _ => None,
        }
    }

    pub fn get_bool(&self, i: usize) -> Option<bool> {
        if !self.is_valid(i) {
            return None;
        }
        match &self.data {
            ColumnData::Bool(v) => Some(bitmap_get(v, i)),
            _ => None,
        }
    }

    /// Raw bytes of a variable-width element (`Text` / `Json`).
    pub fn get_bytes(&self, i: usize) -> Option<&[u8]> {
        if !self.is_valid(i) {
            return None;
        }
        match &self.data {
            ColumnData::Text { offsets, bytes } | ColumnData::Json { offsets, bytes } => {
                Some(&bytes[offsets[i] as usize..offsets[i + 1] as usize])
            }
            _ => None,
        }
    }

    pub fn get_text(&self, i: usize) -> Option<&str> {
        self.get_bytes(i)
            .and_then(|b| std::str::from_utf8(b).ok())
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Column builder (ingest-side, §108.c)
// ─────────────────────────────────────────────────────────────────────

/// Append-only builder for one column. Type mismatches REFUSE (D108.7 —
/// silent coercion is data laundering); nullability via [`push_null`]
/// is the only flexibility.
///
/// [`push_null`]: ColumnBuilder::push_null
#[derive(Debug)]
pub struct ColumnBuilder {
    ty: ColumnType,
    len: usize,
    valid: Vec<bool>,
    ints: Vec<i64>,
    floats: Vec<f64>,
    bools: Vec<bool>,
    var_bytes: Vec<u8>,
    var_offsets: Vec<u64>,
}

impl ColumnBuilder {
    pub fn new(ty: ColumnType) -> Self {
        ColumnBuilder {
            ty,
            len: 0,
            valid: Vec::new(),
            ints: Vec::new(),
            floats: Vec::new(),
            bools: Vec::new(),
            var_bytes: Vec::new(),
            var_offsets: vec![0],
        }
    }

    pub fn push_null(&mut self) {
        self.valid.push(false);
        self.len += 1;
        match self.ty {
            ColumnType::Int | ColumnType::Timestamp => self.ints.push(0),
            ColumnType::Float => self.floats.push(0.0),
            ColumnType::Bool => self.bools.push(false),
            ColumnType::Text | ColumnType::Json => {
                self.var_offsets.push(self.var_bytes.len() as u64)
            }
        }
    }

    pub fn push_int(&mut self, v: i64) -> Result<(), String> {
        match self.ty {
            ColumnType::Int | ColumnType::Timestamp => {
                self.valid.push(true);
                self.len += 1;
                self.ints.push(v);
                Ok(())
            }
            other => Err(format!(
                "type mismatch: pushed Int into a {} column",
                other.canonical_name()
            )),
        }
    }

    pub fn push_float(&mut self, v: f64) -> Result<(), String> {
        match self.ty {
            ColumnType::Float => {
                self.valid.push(true);
                self.len += 1;
                self.floats.push(v);
                Ok(())
            }
            other => Err(format!(
                "type mismatch: pushed Float into a {} column",
                other.canonical_name()
            )),
        }
    }

    pub fn push_bool(&mut self, v: bool) -> Result<(), String> {
        match self.ty {
            ColumnType::Bool => {
                self.valid.push(true);
                self.len += 1;
                self.bools.push(v);
                Ok(())
            }
            other => Err(format!(
                "type mismatch: pushed Bool into a {} column",
                other.canonical_name()
            )),
        }
    }

    pub fn push_text(&mut self, v: &str) -> Result<(), String> {
        match self.ty {
            ColumnType::Text => {
                self.valid.push(true);
                self.len += 1;
                self.var_bytes.extend_from_slice(v.as_bytes());
                self.var_offsets.push(self.var_bytes.len() as u64);
                Ok(())
            }
            other => Err(format!(
                "type mismatch: pushed Text into a {} column",
                other.canonical_name()
            )),
        }
    }

    pub fn push_json_bytes(&mut self, v: &[u8]) -> Result<(), String> {
        match self.ty {
            ColumnType::Json => {
                self.valid.push(true);
                self.len += 1;
                self.var_bytes.extend_from_slice(v);
                self.var_offsets.push(self.var_bytes.len() as u64);
                Ok(())
            }
            other => Err(format!(
                "type mismatch: pushed Json into a {} column",
                other.canonical_name()
            )),
        }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn finish(self) -> ColumnArray {
        let mut validity = vec![0u8; bitmap_len(self.len)];
        for (i, &v) in self.valid.iter().enumerate() {
            if v {
                bitmap_set(&mut validity, i);
            }
        }
        let data = match self.ty {
            ColumnType::Int => ColumnData::Int(self.ints),
            ColumnType::Timestamp => ColumnData::Timestamp(self.ints),
            ColumnType::Float => ColumnData::Float(self.floats),
            ColumnType::Bool => {
                let mut packed = vec![0u8; bitmap_len(self.len)];
                for (i, &b) in self.bools.iter().enumerate() {
                    if b {
                        bitmap_set(&mut packed, i);
                    }
                }
                ColumnData::Bool(packed)
            }
            ColumnType::Text => ColumnData::Text {
                offsets: self.var_offsets,
                bytes: self.var_bytes,
            },
            ColumnType::Json => ColumnData::Json {
                offsets: self.var_offsets,
                bytes: self.var_bytes,
            },
        };
        // The builder maintains the invariants by construction; the
        // validated() pass is kept as the single choke point anyway —
        // cheap, and it means NO ColumnArray exists unchecked.
        ColumnArray::validated(self.len, validity, data)
            .expect("ColumnBuilder maintains the §5.1 invariants by construction")
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Zone maps (plan §5.3)
// ─────────────────────────────────────────────────────────────────────

/// Per-column, per-batch statistics — computed once at construction,
/// immutable thereafter. §108.d's interval abstraction reads these to
/// prune batches soundly (skip ⟹ provably no matching row).
#[derive(Debug, Clone, PartialEq)]
pub enum ZoneStats {
    Int { min: i64, max: i64 },
    Float { min: f64, max: f64 },
    Text { min: String, max: String },
    Bool { any_true: bool, any_false: bool },
    /// No valid values in this column of this batch (all null), or a
    /// type without an ordering abstraction (Json).
    None,
}

#[derive(Debug, Clone)]
pub struct ZoneMap {
    pub null_count: usize,
    pub stats: ZoneStats,
}

fn compute_zone_map(col: &ColumnArray) -> ZoneMap {
    let null_count = col.null_count();
    let n = col.len();
    let stats = match col.column_type() {
        ColumnType::Int | ColumnType::Timestamp => {
            let vals: Vec<i64> = (0..n).filter_map(|i| col.get_int(i)).collect();
            match (vals.iter().min(), vals.iter().max()) {
                (Some(&min), Some(&max)) => ZoneStats::Int { min, max },
                _ => ZoneStats::None,
            }
        }
        ColumnType::Float => {
            let vals: Vec<f64> = (0..n).filter_map(|i| col.get_float(i)).collect();
            if vals.is_empty() {
                ZoneStats::None
            } else {
                // f64 min/max via fold — total for non-NaN; a NaN would
                // poison the zone, so its presence degrades to None
                // (scan the batch — conservative, never unsound).
                if vals.iter().any(|v| v.is_nan()) {
                    ZoneStats::None
                } else {
                    let min = vals.iter().copied().fold(f64::INFINITY, f64::min);
                    let max = vals.iter().copied().fold(f64::NEG_INFINITY, f64::max);
                    ZoneStats::Float { min, max }
                }
            }
        }
        ColumnType::Bool => {
            let vals: Vec<bool> = (0..n).filter_map(|i| col.get_bool(i)).collect();
            if vals.is_empty() {
                ZoneStats::None
            } else {
                ZoneStats::Bool {
                    any_true: vals.iter().any(|&b| b),
                    any_false: vals.iter().any(|&b| !b),
                }
            }
        }
        ColumnType::Text => {
            let vals: Vec<&str> = (0..n).filter_map(|i| col.get_text(i)).collect();
            match (vals.iter().min(), vals.iter().max()) {
                (Some(min), Some(max)) => ZoneStats::Text {
                    min: min.to_string(),
                    max: max.to_string(),
                },
                _ => ZoneStats::None,
            }
        }
        ColumnType::Json => ZoneStats::None,
    };
    ZoneMap { null_count, stats }
}

// ─────────────────────────────────────────────────────────────────────
//  Provenance (plan §5.4)
// ─────────────────────────────────────────────────────────────────────

/// The stamp every batch carries from ingest. `ingested_at` is the
/// flow's DECLARED time (§91 — one instant per run), not a wall-clock
/// read. `taint` is born [`EpistemicTaint::Untrusted`] (§98) and no
/// data-plane operation can raise it — query results take the meet.
#[derive(Debug, Clone)]
pub struct BatchProvenance {
    pub source: String,
    pub source_sha256: String,
    pub ingested_at: String,
    pub taint: EpistemicTaint,
}

/// The §5.4 meet (⊓) on the taint lattice:
/// `Untrusted < SchemaValidated < Elevated`. An aggregate over any
/// untrusted batch is born untrusted — taint survives the algebra.
pub fn taint_meet(a: EpistemicTaint, b: EpistemicTaint) -> EpistemicTaint {
    fn rank(t: EpistemicTaint) -> u8 {
        match t {
            EpistemicTaint::Untrusted => 0,
            EpistemicTaint::SchemaValidated => 1,
            EpistemicTaint::Elevated => 2,
        }
    }
    if rank(a) <= rank(b) {
        a
    } else {
        b
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Record batches
// ─────────────────────────────────────────────────────────────────────

/// One immutable batch: `B = ⟨S, {A₁…Aₖ}, N, π_B⟩`. Constructed only
/// via [`RecordBatch::new`], which checks schema conformance + the
/// common-length invariant and computes the zone maps ONCE.
#[derive(Debug, Clone)]
pub struct RecordBatch {
    n: usize,
    columns: Vec<ColumnArray>,
    zone_maps: Vec<ZoneMap>,
    provenance: BatchProvenance,
}

impl RecordBatch {
    pub fn new(
        schema: &[(String, ColumnType)],
        columns: Vec<ColumnArray>,
        provenance: BatchProvenance,
    ) -> Result<Self, String> {
        if columns.len() != schema.len() {
            return Err(format!(
                "batch carries {} columns; the schema declares {}",
                columns.len(),
                schema.len()
            ));
        }
        for ((name, ty), col) in schema.iter().zip(&columns) {
            if col.column_type() != *ty {
                return Err(format!(
                    "column `{name}` is declared {} but the batch carries {}",
                    ty.canonical_name(),
                    col.column_type().canonical_name()
                ));
            }
        }
        let n = columns.first().map(|c| c.len()).unwrap_or(0);
        if let Some(bad) = columns.iter().find(|c| c.len() != n) {
            return Err(format!(
                "ragged batch: common logical length is {n}, but a {} column holds {}",
                bad.column_type().canonical_name(),
                bad.len()
            ));
        }
        let zone_maps = columns.iter().map(compute_zone_map).collect();
        Ok(RecordBatch {
            n,
            columns,
            zone_maps,
            provenance,
        })
    }

    pub fn len(&self) -> usize {
        self.n
    }

    pub fn is_empty(&self) -> bool {
        self.n == 0
    }

    pub fn column(&self, idx: usize) -> Option<&ColumnArray> {
        self.columns.get(idx)
    }

    pub fn zone_map(&self, idx: usize) -> Option<&ZoneMap> {
        self.zone_maps.get(idx)
    }

    pub fn provenance(&self) -> &BatchProvenance {
        &self.provenance
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Stores + the engine
// ─────────────────────────────────────────────────────────────────────

/// One declared dataspace: its schema + the append-only batch list.
#[derive(Debug)]
pub struct DataspaceStore {
    pub name: String,
    schema: Vec<(String, ColumnType)>,
    batches: Vec<RecordBatch>,
}

impl DataspaceStore {
    pub fn schema(&self) -> &[(String, ColumnType)] {
        &self.schema
    }

    pub fn column_index(&self, name: &str) -> Option<usize> {
        self.schema.iter().position(|(n, _)| n == name)
    }

    /// Append an ingested batch (§108.c). Schema conformance was
    /// checked at batch construction against THIS schema; re-checked
    /// here because `RecordBatch::new` and `append` may be fed from
    /// different call sites.
    pub fn append(&mut self, batch: RecordBatch) -> Result<(), String> {
        if batch.columns.len() != self.schema.len() {
            return Err(format!(
                "batch carries {} columns; dataspace `{}` declares {}",
                batch.columns.len(),
                self.name,
                self.schema.len()
            ));
        }
        for ((name, ty), col) in self.schema.iter().zip(&batch.columns) {
            if col.column_type() != *ty {
                return Err(format!(
                    "column `{name}` of dataspace `{}` is {} but the batch carries {}",
                    self.name,
                    ty.canonical_name(),
                    col.column_type().canonical_name()
                ));
            }
        }
        self.batches.push(batch);
        Ok(())
    }

    pub fn batches(&self) -> &[RecordBatch] {
        &self.batches
    }

    pub fn row_count(&self) -> usize {
        self.batches.iter().map(|b| b.n).sum()
    }

    /// Total resident bytes across all buffers — the quota signal for
    /// the §108.e per-tenant byte budget (refusal, not eviction).
    pub fn resident_bytes(&self) -> usize {
        self.batches
            .iter()
            .flat_map(|b| b.columns.iter())
            .map(|c| {
                c.validity.len()
                    + match &c.data {
                        ColumnData::Int(v) | ColumnData::Timestamp(v) => v.len() * 8,
                        ColumnData::Float(v) => v.len() * 8,
                        ColumnData::Bool(v) => v.len(),
                        ColumnData::Text { offsets, bytes }
                        | ColumnData::Json { offsets, bytes } => offsets.len() * 8 + bytes.len(),
                    }
            })
            .sum()
    }
}

/// The engine: every declared dataspace, instantiated at deploy from
/// the IR (`dataspace_specs`, un-skipped in §108.b). Shared behind
/// `Arc<RwLock<…>>` as the dispatcher port — absent port ⇒ the §108.a
/// handlers fail CLOSED.
#[derive(Debug, Default)]
pub struct DataspaceEngine {
    stores: HashMap<String, DataspaceStore>,
}

/// The dispatcher-port shape (`DispatchCtx.dataspace_engine`).
pub type SharedDataspaceEngine = std::sync::Arc<std::sync::RwLock<DataspaceEngine>>;

impl DataspaceEngine {
    /// Instantiate every declared dataspace from the compiled IR. An
    /// unknown canonical type means a stale or hand-edited artifact —
    /// the whole deploy REFUSES (fail closed), never a partial engine.
    pub fn from_ir(specs: &[axon_frontend::ir_nodes::IRDataspace]) -> Result<Self, String> {
        let mut stores = HashMap::new();
        for spec in specs {
            let mut schema = Vec::with_capacity(spec.columns.len());
            for col in &spec.columns {
                let ty = ColumnType::from_canonical(&col.column_type).ok_or_else(|| {
                    format!(
                        "dataspace `{}` column `{}` carries unknown canonical type `{}` — \
                         the compile-time axon-T928 check did not run over this IR \
                         (stale or hand-edited artifact)",
                        spec.name, col.name, col.column_type
                    )
                })?;
                schema.push((col.name.clone(), ty));
            }
            stores.insert(
                spec.name.clone(),
                DataspaceStore {
                    name: spec.name.clone(),
                    schema,
                    batches: Vec::new(),
                },
            );
        }
        Ok(DataspaceEngine { stores })
    }

    /// Merge a deployed program's declared dataspaces into a live engine
    /// (the OSS server hosts several programs). A NEW name creates an
    /// empty store; a RE-declared name **replaces** its store (the schema
    /// may have changed, and the OSS engine is in-memory — redeploy has
    /// restart-equivalent semantics for that dataspace, D108.8). Names
    /// not in `specs` are untouched. Validation is all-or-nothing: an
    /// unknown canonical type refuses the whole merge, mutating nothing.
    pub fn merge_from_ir(
        &mut self,
        specs: &[axon_frontend::ir_nodes::IRDataspace],
    ) -> Result<(), String> {
        let incoming = DataspaceEngine::from_ir(specs)?;
        for (name, store) in incoming.stores {
            self.stores.insert(name, store);
        }
        Ok(())
    }

    pub fn store(&self, name: &str) -> Option<&DataspaceStore> {
        self.stores.get(name)
    }

    pub fn store_mut(&mut self, name: &str) -> Option<&mut DataspaceStore> {
        self.stores.get_mut(name)
    }

    pub fn store_names(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.stores.keys().map(|s| s.as_str()).collect();
        names.sort_unstable();
        names
    }

    pub fn len(&self) -> usize {
        self.stores.len()
    }

    pub fn is_empty(&self) -> bool {
        self.stores.is_empty()
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Governed ingest — deterministic loaders (§108.c)
// ─────────────────────────────────────────────────────────────────────

/// The closed loader catalog (axon-T929). Deterministic + first-party
/// — the §100 posture. Parquet / Arrow-IPC are deferred §108.x surface.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IngestFormat {
    Csv,
    Json,
}

impl IngestFormat {
    pub fn from_declared(s: &str) -> Option<IngestFormat> {
        match s {
            "csv" => Some(IngestFormat::Csv),
            "json" => Some(IngestFormat::Json),
            _ => None,
        }
    }
}

/// Bounds enforced on the RAW byte stream BEFORE any parsing (§100 —
/// bounds-BEFORE-parse). The defaults are deliberately conservative:
/// an ingest is bounded BY DEFAULT, never unbounded.
#[derive(Debug, Clone, Copy)]
pub struct IngestLimits {
    pub max_bytes: u64,
    pub max_rows: u64,
}

impl Default for IngestLimits {
    fn default() -> Self {
        IngestLimits {
            max_bytes: 16 * 1024 * 1024, // 16 MiB
            max_rows: 1_000_000,
        }
    }
}

/// Parse + type raw source bytes into ONE immutable [`RecordBatch`]
/// against the declared schema.
///
/// The §108.c laws, in order:
/// 1. **Bounds BEFORE parse** (§100): the byte bound is checked against
///    the raw stream before a single byte is interpreted; the row bound
///    during parsing, before typing each excess row.
/// 2. **Type refusal, not coercion** (D108.7): a value that does not
///    fit its column type refuses the WHOLE batch, naming row + column.
///    A missing value (empty CSV field / absent JSON key / JSON null)
///    is a structural null in the validity bitmap — the only
///    flexibility.
/// 3. The batch is stamped with `provenance` (born-Untrusted, §98) —
///    stamping happens HERE so no unstamped batch can exist.
pub fn ingest_bytes(
    schema: &[(String, ColumnType)],
    format: IngestFormat,
    raw: &[u8],
    limits: &IngestLimits,
    provenance: BatchProvenance,
) -> Result<RecordBatch, String> {
    // Law 1 — the byte bound, before ANY interpretation of the stream.
    if raw.len() as u64 > limits.max_bytes {
        return Err(format!(
            "ingest refused BEFORE parse: source is {} bytes, the declared bound is {} \
             (§100 bounds-BEFORE-parse — raise `limits {{ max_bytes: … }}` if intended)",
            raw.len(),
            limits.max_bytes
        ));
    }
    let mut builders: Vec<ColumnBuilder> = schema
        .iter()
        .map(|(_, ty)| ColumnBuilder::new(*ty))
        .collect();
    match format {
        IngestFormat::Csv => fill_from_csv(schema, raw, limits, &mut builders)?,
        IngestFormat::Json => fill_from_json(schema, raw, limits, &mut builders)?,
    }
    let columns: Vec<ColumnArray> = builders.into_iter().map(|b| b.finish()).collect();
    RecordBatch::new(schema, columns, provenance)
}

/// Minimal deterministic CSV reader (RFC 4180 core): quoted fields,
/// `""` escapes inside quotes, commas + LF/CRLF inside quotes, header
/// row REQUIRED. Returns rows of raw string fields.
fn parse_csv_rows(text: &str) -> Result<Vec<Vec<String>>, String> {
    let mut rows: Vec<Vec<String>> = Vec::new();
    let mut row: Vec<String> = Vec::new();
    let mut field = String::new();
    let mut in_quotes = false;
    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if in_quotes {
            match c {
                '"' => {
                    if chars.peek() == Some(&'"') {
                        chars.next();
                        field.push('"');
                    } else {
                        in_quotes = false;
                    }
                }
                other => field.push(other),
            }
        } else {
            match c {
                '"' => {
                    if field.is_empty() {
                        in_quotes = true;
                    } else {
                        return Err(format!(
                            "malformed CSV at row {}: a quote may only open an empty field",
                            rows.len() + 1
                        ));
                    }
                }
                ',' => {
                    row.push(std::mem::take(&mut field));
                }
                '\r' => { /* swallowed; the LF closes the record */ }
                '\n' => {
                    row.push(std::mem::take(&mut field));
                    rows.push(std::mem::take(&mut row));
                }
                other => field.push(other),
            }
        }
    }
    if in_quotes {
        return Err("malformed CSV: unclosed quoted field at end of input".to_string());
    }
    if !field.is_empty() || !row.is_empty() {
        row.push(field);
        rows.push(row);
    }
    Ok(rows)
}

fn fill_from_csv(
    schema: &[(String, ColumnType)],
    raw: &[u8],
    limits: &IngestLimits,
    builders: &mut [ColumnBuilder],
) -> Result<(), String> {
    let text = std::str::from_utf8(raw).map_err(|_| "source is not valid UTF-8".to_string())?;
    let rows = parse_csv_rows(text)?;
    let Some((header, data_rows)) = rows.split_first() else {
        return Ok(()); // empty source → empty batch (0 rows is honest)
    };
    // Column mapping is BY NAME: every schema column must appear in the
    // header (a load that silently fills a declared column with nulls
    // because the header lacks it would be laundering); EXTRA source
    // columns are projected away (π, not coercion).
    let mut col_idx: Vec<usize> = Vec::with_capacity(schema.len());
    for (name, _) in schema {
        match header.iter().position(|h| h.trim() == name) {
            Some(i) => col_idx.push(i),
            None => {
                return Err(format!(
                    "CSV header does not contain declared column `{name}` — the header is \
                     {header:?}. Every schema column must be present (extra source columns \
                     are ignored; missing ones are refused, not null-filled)."
                ));
            }
        }
    }
    // Law 1 (rows) — bound checked BEFORE typing any excess row.
    if data_rows.len() as u64 > limits.max_rows {
        return Err(format!(
            "ingest refused: source carries {} rows, the declared bound is {} \
             (`limits {{ max_rows: … }}`)",
            data_rows.len(),
            limits.max_rows
        ));
    }
    for (r, row) in data_rows.iter().enumerate() {
        for (s, (name, ty)) in schema.iter().enumerate() {
            let raw_field = row.get(col_idx[s]).map(|f| f.as_str()).unwrap_or("");
            push_csv_field(&mut builders[s], *ty, raw_field)
                .map_err(|e| format!("row {} column `{name}`: {e}", r + 1))?;
        }
    }
    Ok(())
}

fn push_csv_field(b: &mut ColumnBuilder, ty: ColumnType, field: &str) -> Result<(), String> {
    if field.is_empty() {
        b.push_null(); // empty field = structural null (the ONLY flexibility)
        return Ok(());
    }
    match ty {
        ColumnType::Int => {
            let v: i64 = field
                .trim()
                .parse()
                .map_err(|_| format!("expected Int, got `{field}` (refusal, not coercion)"))?;
            b.push_int(v)
        }
        ColumnType::Float => {
            let v: f64 = field
                .trim()
                .parse()
                .map_err(|_| format!("expected Float, got `{field}` (refusal, not coercion)"))?;
            b.push_float(v)
        }
        ColumnType::Bool => match field.trim().to_ascii_lowercase().as_str() {
            "true" => b.push_bool(true),
            "false" => b.push_bool(false),
            other => Err(format!(
                "expected Bool (`true`/`false`), got `{other}` (refusal, not coercion)"
            )),
        },
        ColumnType::Timestamp => {
            let dt = chrono::DateTime::parse_from_rfc3339(field.trim()).map_err(|_| {
                format!("expected an RFC 3339 timestamp, got `{field}` (refusal, not coercion)")
            })?;
            b.push_int(dt.timestamp_micros())
        }
        ColumnType::Text => b.push_text(field),
        ColumnType::Json => {
            let v: serde_json::Value = serde_json::from_str(field)
                .map_err(|_| format!("expected valid JSON, got `{field}`"))?;
            // Re-serialized compact — ONE canonical byte form per value.
            b.push_json_bytes(v.to_string().as_bytes())
        }
    }
}

fn fill_from_json(
    schema: &[(String, ColumnType)],
    raw: &[u8],
    limits: &IngestLimits,
    builders: &mut [ColumnBuilder],
) -> Result<(), String> {
    let root: serde_json::Value =
        serde_json::from_slice(raw).map_err(|e| format!("source is not valid JSON: {e}"))?;
    let rows = root
        .as_array()
        .ok_or_else(|| "JSON source must be an ARRAY of row objects".to_string())?;
    if rows.len() as u64 > limits.max_rows {
        return Err(format!(
            "ingest refused: source carries {} rows, the declared bound is {} \
             (`limits {{ max_rows: … }}`)",
            rows.len(),
            limits.max_rows
        ));
    }
    for (r, row) in rows.iter().enumerate() {
        let obj = row.as_object().ok_or_else(|| {
            format!("row {}: every JSON row must be an object", r + 1)
        })?;
        for (s, (name, ty)) in schema.iter().enumerate() {
            let value = obj.get(name.as_str()).unwrap_or(&serde_json::Value::Null);
            push_json_field(&mut builders[s], *ty, value)
                .map_err(|e| format!("row {} column `{name}`: {e}", r + 1))?;
        }
    }
    Ok(())
}

fn push_json_field(
    b: &mut ColumnBuilder,
    ty: ColumnType,
    v: &serde_json::Value,
) -> Result<(), String> {
    if v.is_null() {
        b.push_null(); // absent key or explicit null = structural null
        return Ok(());
    }
    match ty {
        ColumnType::Int => match v.as_i64() {
            Some(i) => b.push_int(i),
            None => Err(format!(
                "expected Int, got {v} (a fractional number or non-number is a refusal, \
                 not a coercion)"
            )),
        },
        // JSON has ONE number type — an integer literal in a Float
        // column is the same JSON number, not a coercion.
        ColumnType::Float => match v.as_f64() {
            Some(f) => b.push_float(f),
            None => Err(format!("expected Float, got {v} (refusal, not coercion)")),
        },
        ColumnType::Bool => match v.as_bool() {
            Some(x) => b.push_bool(x),
            None => Err(format!("expected Bool, got {v} (refusal, not coercion)")),
        },
        ColumnType::Timestamp => match v.as_str() {
            Some(s) => {
                let dt = chrono::DateTime::parse_from_rfc3339(s).map_err(|_| {
                    format!("expected an RFC 3339 timestamp string, got `{s}`")
                })?;
                b.push_int(dt.timestamp_micros())
            }
            None => Err(format!("expected an RFC 3339 timestamp string, got {v}")),
        },
        ColumnType::Text => match v.as_str() {
            Some(s) => b.push_text(s),
            None => Err(format!(
                "expected Text, got {v} (a number is not silently stringified — \
                 refusal, not coercion)"
            )),
        },
        ColumnType::Json => b.push_json_bytes(v.to_string().as_bytes()),
    }
}

// ─────────────────────────────────────────────────────────────────────
//  Unit tests
// ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn provenance() -> BatchProvenance {
        BatchProvenance {
            source: "unit-test".into(),
            source_sha256: "0".repeat(64),
            ingested_at: "2026-07-12T00:00:00Z".into(),
            taint: EpistemicTaint::Untrusted,
        }
    }

    #[test]
    fn builder_roundtrips_every_type_with_nulls() {
        let mut ints = ColumnBuilder::new(ColumnType::Int);
        ints.push_int(7).unwrap();
        ints.push_null();
        ints.push_int(-3).unwrap();
        let ints = ints.finish();
        assert_eq!(ints.len(), 3);
        assert_eq!(ints.get_int(0), Some(7));
        assert_eq!(ints.get_int(1), None, "null is structural, no sentinel");
        assert_eq!(ints.get_int(2), Some(-3));
        assert_eq!(ints.null_count(), 1);

        let mut texts = ColumnBuilder::new(ColumnType::Text);
        texts.push_text("hola").unwrap();
        texts.push_null();
        texts.push_text("").unwrap(); // empty string ≠ null
        let texts = texts.finish();
        assert_eq!(texts.get_text(0), Some("hola"));
        assert_eq!(texts.get_text(1), None);
        assert_eq!(texts.get_text(2), Some(""), "empty string is present");

        let mut bools = ColumnBuilder::new(ColumnType::Bool);
        for i in 0..10 {
            bools.push_bool(i % 3 == 0).unwrap();
        }
        let bools = bools.finish();
        assert_eq!(bools.get_bool(0), Some(true));
        assert_eq!(bools.get_bool(1), Some(false));
        assert_eq!(bools.get_bool(9), Some(true));

        let mut floats = ColumnBuilder::new(ColumnType::Float);
        floats.push_float(1.5).unwrap();
        floats.push_float(-0.25).unwrap();
        let floats = floats.finish();
        assert_eq!(floats.get_float(1), Some(-0.25));
    }

    #[test]
    fn builder_refuses_a_type_mismatch() {
        // D108.7 — silent coercion is data laundering.
        let mut b = ColumnBuilder::new(ColumnType::Int);
        let err = b.push_text("42").unwrap_err();
        assert!(err.contains("type mismatch"), "{err}");
    }

    #[test]
    fn validated_refuses_broken_invariants() {
        // Bitmap length.
        assert!(ColumnArray::validated(9, vec![0u8; 1], ColumnData::Int(vec![0; 9])).is_err());
        // Fixed-width length.
        assert!(ColumnArray::validated(3, vec![0u8; 1], ColumnData::Int(vec![0; 2])).is_err());
        // Offsets must start at 0.
        assert!(ColumnArray::validated(
            1,
            vec![1u8],
            ColumnData::Text {
                offsets: vec![1, 2],
                bytes: vec![b'a', b'b'],
            }
        )
        .is_err());
        // Offsets monotone.
        assert!(ColumnArray::validated(
            2,
            vec![3u8],
            ColumnData::Text {
                offsets: vec![0, 5, 2],
                bytes: vec![0; 2],
            }
        )
        .is_err());
        // Final offset ≡ byte length.
        assert!(ColumnArray::validated(
            1,
            vec![1u8],
            ColumnData::Text {
                offsets: vec![0, 3],
                bytes: vec![b'a'],
            }
        )
        .is_err());
    }

    #[test]
    fn record_batch_refuses_schema_and_length_violations() {
        let schema = vec![
            ("a".to_string(), ColumnType::Int),
            ("b".to_string(), ColumnType::Text),
        ];
        let mut a = ColumnBuilder::new(ColumnType::Int);
        a.push_int(1).unwrap();
        // Wrong arity.
        assert!(RecordBatch::new(&schema, vec![a.finish()], provenance()).is_err());

        // Wrong type in slot b.
        let mut a = ColumnBuilder::new(ColumnType::Int);
        a.push_int(1).unwrap();
        let mut not_text = ColumnBuilder::new(ColumnType::Float);
        not_text.push_float(0.5).unwrap();
        assert!(
            RecordBatch::new(&schema, vec![a.finish(), not_text.finish()], provenance()).is_err()
        );

        // Ragged lengths.
        let mut a = ColumnBuilder::new(ColumnType::Int);
        a.push_int(1).unwrap();
        a.push_int(2).unwrap();
        let mut b = ColumnBuilder::new(ColumnType::Text);
        b.push_text("only-one").unwrap();
        let err =
            RecordBatch::new(&schema, vec![a.finish(), b.finish()], provenance()).unwrap_err();
        assert!(err.contains("ragged"), "{err}");
    }

    #[test]
    fn zone_maps_are_computed_at_construction() {
        let schema = vec![
            ("n".to_string(), ColumnType::Int),
            ("name".to_string(), ColumnType::Text),
        ];
        let mut n = ColumnBuilder::new(ColumnType::Int);
        n.push_int(10).unwrap();
        n.push_null();
        n.push_int(-4).unwrap();
        n.push_int(7).unwrap();
        let mut name = ColumnBuilder::new(ColumnType::Text);
        name.push_text("beta").unwrap();
        name.push_text("alpha").unwrap();
        name.push_text("gamma").unwrap();
        name.push_null();
        let batch =
            RecordBatch::new(&schema, vec![n.finish(), name.finish()], provenance()).unwrap();

        let zm = batch.zone_map(0).unwrap();
        assert_eq!(zm.null_count, 1);
        assert_eq!(zm.stats, ZoneStats::Int { min: -4, max: 10 });

        let zm = batch.zone_map(1).unwrap();
        assert_eq!(
            zm.stats,
            ZoneStats::Text {
                min: "alpha".into(),
                max: "gamma".into()
            }
        );
    }

    #[test]
    fn all_null_column_yields_zone_none() {
        let schema = vec![("x".to_string(), ColumnType::Float)];
        let mut x = ColumnBuilder::new(ColumnType::Float);
        x.push_null();
        x.push_null();
        let batch = RecordBatch::new(&schema, vec![x.finish()], provenance()).unwrap();
        assert_eq!(batch.zone_map(0).unwrap().stats, ZoneStats::None);
        assert_eq!(batch.zone_map(0).unwrap().null_count, 2);
    }

    #[test]
    fn nan_poisons_the_float_zone_to_none_never_unsound() {
        let schema = vec![("x".to_string(), ColumnType::Float)];
        let mut x = ColumnBuilder::new(ColumnType::Float);
        x.push_float(1.0).unwrap();
        x.push_float(f64::NAN).unwrap();
        let batch = RecordBatch::new(&schema, vec![x.finish()], provenance()).unwrap();
        // A NaN cannot be bounded by an interval — the zone degrades to
        // None (always scan) rather than risk an unsound prune.
        assert_eq!(batch.zone_map(0).unwrap().stats, ZoneStats::None);
    }

    #[test]
    fn taint_meet_is_the_lattice_min() {
        use EpistemicTaint::*;
        assert_eq!(taint_meet(Untrusted, Elevated), Untrusted);
        assert_eq!(taint_meet(Elevated, SchemaValidated), SchemaValidated);
        assert_eq!(taint_meet(Elevated, Elevated), Elevated);
    }

    fn ir_spec(name: &str, cols: &[(&str, &str)]) -> axon_frontend::ir_nodes::IRDataspace {
        axon_frontend::ir_nodes::IRDataspace {
            node_type: "dataspace",
            source_line: 1,
            source_column: 1,
            name: name.to_string(),
            columns: cols
                .iter()
                .map(|(n, t)| axon_frontend::ir_nodes::IRDataspaceColumn {
                    name: n.to_string(),
                    column_type: t.to_string(),
                })
                .collect(),
        }
    }

    #[test]
    fn engine_instantiates_from_ir_specs() {
        let engine = DataspaceEngine::from_ir(&[
            ir_spec("Leads", &[("email", "Text"), ("score", "Float")]),
            ir_spec("Events", &[("at", "Timestamp"), ("payload", "Json")]),
        ])
        .unwrap();
        assert_eq!(engine.len(), 2);
        let leads = engine.store("Leads").unwrap();
        assert_eq!(leads.schema().len(), 2);
        assert_eq!(leads.column_index("score"), Some(1));
        assert_eq!(leads.row_count(), 0);
    }

    #[test]
    fn engine_refuses_a_stale_ir_with_unknown_type() {
        // Fail CLOSED on the whole deploy — never a partial engine.
        let err = DataspaceEngine::from_ir(&[ir_spec("X", &[("a", "Decimal")])]).unwrap_err();
        assert!(err.contains("axon-T928"), "names the bypassed law: {err}");
    }

    #[test]
    fn store_append_and_scan_via_batches() {
        let mut engine =
            DataspaceEngine::from_ir(&[ir_spec("M", &[("k", "Text"), ("v", "Int")])]).unwrap();
        let store = engine.store_mut("M").unwrap();
        let schema: Vec<(String, ColumnType)> = store.schema().to_vec();

        let mut k = ColumnBuilder::new(ColumnType::Text);
        k.push_text("a").unwrap();
        k.push_text("b").unwrap();
        let mut v = ColumnBuilder::new(ColumnType::Int);
        v.push_int(1).unwrap();
        v.push_int(2).unwrap();
        let batch = RecordBatch::new(&schema, vec![k.finish(), v.finish()], provenance()).unwrap();
        store.append(batch).unwrap();
        assert_eq!(store.row_count(), 2);
        assert!(store.resident_bytes() > 0);

        // Append-only (D108.2): a second batch accumulates; nothing mutates.
        let mut k = ColumnBuilder::new(ColumnType::Text);
        k.push_text("c").unwrap();
        let mut v = ColumnBuilder::new(ColumnType::Int);
        v.push_int(3).unwrap();
        let b2 = RecordBatch::new(&schema, vec![k.finish(), v.finish()], provenance()).unwrap();
        store.append(b2).unwrap();
        assert_eq!(store.batches().len(), 2);
        assert_eq!(store.row_count(), 3);
    }

    // ── §108.c — the governed loaders ────────────────────────────────

    fn lead_schema() -> Vec<(String, ColumnType)> {
        vec![
            ("email".to_string(), ColumnType::Text),
            ("score".to_string(), ColumnType::Float),
            ("visits".to_string(), ColumnType::Int),
        ]
    }

    #[test]
    fn ingest_csv_types_rows_against_the_schema() {
        let csv = "email,score,visits,extra\na@x.com,0.9,3,zz\nb@x.com,,7,zz\n";
        let batch = ingest_bytes(
            &lead_schema(),
            IngestFormat::Csv,
            csv.as_bytes(),
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap();
        assert_eq!(batch.len(), 2);
        assert_eq!(batch.column(0).unwrap().get_text(1), Some("b@x.com"));
        assert_eq!(
            batch.column(1).unwrap().get_float(1),
            None,
            "empty CSV field = structural null"
        );
        assert_eq!(batch.column(2).unwrap().get_int(1), Some(7));
        // Extra source column projected away; provenance stamped.
        assert_eq!(batch.provenance().taint, EpistemicTaint::Untrusted);
    }

    #[test]
    fn ingest_refuses_bytes_bound_before_any_parse() {
        // §100 — the refusal must be the BOUNDS error, not a parse error,
        // even though the payload is also malformed CSV.
        let garbage = vec![b'"'; 4096]; // unclosed quote AND oversized
        let err = ingest_bytes(
            &lead_schema(),
            IngestFormat::Csv,
            &garbage,
            &IngestLimits {
                max_bytes: 1024,
                max_rows: 10,
            },
            provenance(),
        )
        .unwrap_err();
        assert!(
            err.contains("BEFORE parse"),
            "bounds must precede parsing: {err}"
        );
    }

    #[test]
    fn ingest_refuses_rows_bound() {
        let mut csv = String::from("email,score,visits\n");
        for i in 0..5 {
            csv.push_str(&format!("u{i}@x.com,0.5,1\n"));
        }
        let err = ingest_bytes(
            &lead_schema(),
            IngestFormat::Csv,
            csv.as_bytes(),
            &IngestLimits {
                max_bytes: 1024 * 1024,
                max_rows: 3,
            },
            provenance(),
        )
        .unwrap_err();
        assert!(err.contains("5 rows"), "{err}");
    }

    #[test]
    fn ingest_type_mismatch_refuses_naming_row_and_column() {
        // D108.7 — refusal, not coercion; the error is actionable.
        let csv = "email,score,visits\na@x.com,not_a_number,3\n";
        let err = ingest_bytes(
            &lead_schema(),
            IngestFormat::Csv,
            csv.as_bytes(),
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap_err();
        assert!(err.contains("row 1"), "{err}");
        assert!(err.contains("`score`"), "{err}");
    }

    #[test]
    fn ingest_csv_missing_schema_column_in_header_refuses() {
        let csv = "email,visits\na@x.com,3\n"; // no `score`
        let err = ingest_bytes(
            &lead_schema(),
            IngestFormat::Csv,
            csv.as_bytes(),
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap_err();
        assert!(err.contains("`score`"), "null-filling is laundering: {err}");
    }

    #[test]
    fn ingest_csv_quoted_fields_roundtrip() {
        let csv = "email,score,visits\n\"a,with,commas@x.com\",0.5,1\n\"say \"\"hi\"\"\",0.1,2\n";
        let schema = vec![
            ("email".to_string(), ColumnType::Text),
            ("score".to_string(), ColumnType::Float),
            ("visits".to_string(), ColumnType::Int),
        ];
        let batch = ingest_bytes(
            &schema,
            IngestFormat::Csv,
            csv.as_bytes(),
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap();
        assert_eq!(
            batch.column(0).unwrap().get_text(0),
            Some("a,with,commas@x.com")
        );
        assert_eq!(batch.column(0).unwrap().get_text(1), Some("say \"hi\""));
    }

    #[test]
    fn ingest_json_rows_with_nulls_timestamps_and_json_columns() {
        let schema = vec![
            ("who".to_string(), ColumnType::Text),
            ("at".to_string(), ColumnType::Timestamp),
            ("meta".to_string(), ColumnType::Json),
        ];
        let src = r#"[
            {"who":"ana","at":"2026-07-12T10:00:00Z","meta":{"k":1}},
            {"who":null,"at":null}
        ]"#;
        let batch = ingest_bytes(
            &schema,
            IngestFormat::Json,
            src.as_bytes(),
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap();
        assert_eq!(batch.len(), 2);
        assert!(batch.column(1).unwrap().get_int(0).unwrap() > 0);
        assert_eq!(batch.column(1).unwrap().get_int(1), None, "null + absent = null");
        assert_eq!(
            batch.column(2).unwrap().get_text(0),
            Some(r#"{"k":1}"#),
            "Json column keeps ONE canonical compact byte form"
        );
        assert_eq!(batch.column(2).unwrap().get_bytes(1), None);
    }

    #[test]
    fn ingest_json_int_column_refuses_fractional_number() {
        let schema = vec![("n".to_string(), ColumnType::Int)];
        let err = ingest_bytes(
            &schema,
            IngestFormat::Json,
            br#"[{"n": 1.5}]"#,
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap_err();
        assert!(err.contains("expected Int"), "{err}");
    }

    #[test]
    fn ingest_json_non_array_root_refuses() {
        let schema = vec![("n".to_string(), ColumnType::Int)];
        let err = ingest_bytes(
            &schema,
            IngestFormat::Json,
            br#"{"n": 1}"#,
            &IngestLimits::default(),
            provenance(),
        )
        .unwrap_err();
        assert!(err.contains("ARRAY"), "{err}");
    }

    #[test]
    fn store_append_refuses_schema_mismatch() {
        let mut engine = DataspaceEngine::from_ir(&[ir_spec("M", &[("v", "Int")])]).unwrap();
        // A batch built against a DIFFERENT schema shape.
        let other_schema = vec![("v".to_string(), ColumnType::Float)];
        let mut v = ColumnBuilder::new(ColumnType::Float);
        v.push_float(0.5).unwrap();
        let batch = RecordBatch::new(&other_schema, vec![v.finish()], provenance()).unwrap();
        let err = engine.store_mut("M").unwrap().append(batch).unwrap_err();
        assert!(err.contains("Int"), "{err}");
    }
}
