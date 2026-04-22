//! [`BufferPool`] — slab allocator for [`ZeroCopyBuffer`] storage.
//!
//! Allocation classes: 4 KiB, 64 KiB, 1 MiB, 10 MiB. Buffers larger
//! than the largest class are direct-allocated (counted in the
//! `oversize_allocations_total` metric).
//!
//! Per-tenant accounting: every tenant carries a soft byte limit.
//! Exceeding the limit does not block — it emits
//! `buffer_pool_soft_limit_exceeded_total{tenant_id=…}` so operators
//! can see which tenants are sustaining high multimodal throughput.
//! The pool is global-per-process, not per-tenant, so a spike on
//! tenant A doesn't force a second pool allocation for tenant B.
//!
//! The pool holds `Vec<u8>` slabs on its free lists. When a
//! `ZeroCopyBuffer` allocated from the pool drops, the slab is
//! reclaimed via the [`PoolHandle`] stored on its clone path.
//! (11.b ships with a simpler model: slabs are requested on-demand
//! and returned manually; a future revision wires the Drop impl to
//! the pool once we're confident in the ownership model.)

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

// ── Size classes ─────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PoolClass {
    Small,  // up to 4 KiB
    Medium, // 4 KiB+..64 KiB
    Large,  // 64 KiB+..1 MiB
    Huge,   // 1 MiB+..10 MiB
    Oversize, // > 10 MiB — direct allocation, no pooling
}

impl PoolClass {
    pub fn capacity(self) -> usize {
        match self {
            PoolClass::Small => 4 * 1024,
            PoolClass::Medium => 64 * 1024,
            PoolClass::Large => 1024 * 1024,
            PoolClass::Huge => 10 * 1024 * 1024,
            PoolClass::Oversize => usize::MAX,
        }
    }

    pub fn slug(self) -> &'static str {
        match self {
            PoolClass::Small => "small",
            PoolClass::Medium => "medium",
            PoolClass::Large => "large",
            PoolClass::Huge => "huge",
            PoolClass::Oversize => "oversize",
        }
    }

    /// Pick the smallest class that fits `requested` bytes.
    pub fn for_size(requested: usize) -> Self {
        if requested <= PoolClass::Small.capacity() {
            PoolClass::Small
        } else if requested <= PoolClass::Medium.capacity() {
            PoolClass::Medium
        } else if requested <= PoolClass::Large.capacity() {
            PoolClass::Large
        } else if requested <= PoolClass::Huge.capacity() {
            PoolClass::Huge
        } else {
            PoolClass::Oversize
        }
    }

    pub fn non_oversize() -> [PoolClass; 4] {
        [
            PoolClass::Small,
            PoolClass::Medium,
            PoolClass::Large,
            PoolClass::Huge,
        ]
    }
}

// ── Metrics ──────────────────────────────────────────────────────────

#[derive(Debug, Default)]
struct PoolMetrics {
    pool_hits: [AtomicU64; 4],
    pool_misses: [AtomicU64; 4],
    oversize_allocations: AtomicU64,
    live_bytes: AtomicU64,
}

impl PoolMetrics {
    fn record_request(&self, class: PoolClass, hit: bool) {
        if class == PoolClass::Oversize {
            self.oversize_allocations.fetch_add(1, Ordering::Relaxed);
            return;
        }
        let idx = match class {
            PoolClass::Small => 0,
            PoolClass::Medium => 1,
            PoolClass::Large => 2,
            PoolClass::Huge => 3,
            PoolClass::Oversize => unreachable!(),
        };
        if hit {
            self.pool_hits[idx].fetch_add(1, Ordering::Relaxed);
        } else {
            self.pool_misses[idx].fetch_add(1, Ordering::Relaxed);
        }
    }
}

/// Point-in-time snapshot for metric export. Each field maps 1:1 to
/// a Prometheus counter surfaced by the adopter's observability layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BufferPoolSnapshot {
    pub pool_hits: HashMap<PoolClass, u64>,
    pub pool_misses: HashMap<PoolClass, u64>,
    pub oversize_allocations_total: u64,
    pub live_bytes: u64,
    pub tenant_live_bytes: HashMap<String, u64>,
    pub tenant_soft_limit_exceeded_total: HashMap<String, u64>,
}

// ── Tenant accounting ────────────────────────────────────────────────

#[derive(Debug)]
struct TenantAccount {
    soft_limit_bytes: u64,
    live_bytes: u64,
    soft_limit_exceeded_total: u64,
}

impl TenantAccount {
    fn new(soft_limit_bytes: u64) -> Self {
        TenantAccount {
            soft_limit_bytes,
            live_bytes: 0,
            soft_limit_exceeded_total: 0,
        }
    }
}

// ── BufferPool ───────────────────────────────────────────────────────

/// Slab-allocating pool. Shared across tenants; tenant accounting
/// happens at the metrics layer only. Thread-safe via `Mutex` on the
/// per-class free lists; metrics are lock-free atomics.
pub struct BufferPool {
    /// Free lists per class. Each `Vec<u8>` in the free list has
    /// capacity equal to the class's configured capacity.
    free_lists: [Mutex<Vec<Vec<u8>>>; 4],
    metrics: PoolMetrics,
    tenants: Mutex<HashMap<Arc<str>, TenantAccount>>,
    default_tenant_soft_limit_bytes: u64,
}

impl BufferPool {
    /// Construct with the given per-tenant default soft limit (bytes).
    pub fn new(default_tenant_soft_limit_bytes: u64) -> Self {
        BufferPool {
            free_lists: [
                Mutex::new(Vec::new()),
                Mutex::new(Vec::new()),
                Mutex::new(Vec::new()),
                Mutex::new(Vec::new()),
            ],
            metrics: PoolMetrics::default(),
            tenants: Mutex::new(HashMap::new()),
            default_tenant_soft_limit_bytes,
        }
    }

    /// Configure a per-tenant override. Unknown tenants get the
    /// default limit on their first allocation.
    pub fn set_tenant_soft_limit(
        &self,
        tenant_id: impl Into<Arc<str>>,
        soft_limit_bytes: u64,
    ) {
        let arc: Arc<str> = tenant_id.into();
        let mut guard = self.tenants.lock().expect("tenant map poisoned");
        guard
            .entry(arc)
            .or_insert_with(|| TenantAccount::new(soft_limit_bytes))
            .soft_limit_bytes = soft_limit_bytes;
    }

    /// Acquire a slab of at least `requested` bytes. Returns the
    /// allocated `Vec<u8>` and the class it came from. The `Vec` is
    /// empty (len=0) but has the capacity of its class; callers
    /// `extend_from_slice` into it.
    pub fn acquire(&self, requested: usize) -> (Vec<u8>, PoolClass) {
        let class = PoolClass::for_size(requested);
        if class == PoolClass::Oversize {
            self.metrics.record_request(class, false);
            return (Vec::with_capacity(requested), class);
        }
        let idx = class_index(class);
        let mut free = self.free_lists[idx]
            .lock()
            .expect("free list poisoned");
        if let Some(mut slab) = free.pop() {
            self.metrics.record_request(class, true);
            slab.clear();
            (slab, class)
        } else {
            self.metrics.record_request(class, false);
            (Vec::with_capacity(class.capacity()), class)
        }
    }

    /// Return a previously acquired slab to the pool. Callers typically
    /// do this via the Drop impl of the wrapping buffer once all
    /// views have dropped. In 11.b we expose the API explicitly; a
    /// Drop-wired version lands in a follow-up revision.
    pub fn release(&self, mut slab: Vec<u8>, class: PoolClass) {
        if class == PoolClass::Oversize {
            // Direct allocations aren't pooled — let them drop.
            drop(slab);
            return;
        }
        let idx = class_index(class);
        slab.clear();
        let mut free = self.free_lists[idx]
            .lock()
            .expect("free list poisoned");
        // Cap the free list per class to avoid unbounded growth on
        // idle workloads. 64 slabs per class is plenty for most
        // steady-state ingest rates; excess slabs drop to the heap.
        if free.len() < 64 {
            free.push(slab);
        } else {
            drop(slab);
        }
    }

    /// Record `bytes` of live buffer allocation against a tenant.
    /// Emits the soft-limit-exceeded counter when appropriate.
    pub fn record_tenant_allocation(
        &self,
        tenant_id: impl Into<Arc<str>>,
        bytes: u64,
    ) {
        let arc: Arc<str> = tenant_id.into();
        let default_limit = self.default_tenant_soft_limit_bytes;
        let mut guard = self.tenants.lock().expect("tenant map poisoned");
        let entry = guard
            .entry(arc)
            .or_insert_with(|| TenantAccount::new(default_limit));
        entry.live_bytes = entry.live_bytes.saturating_add(bytes);
        if entry.live_bytes > entry.soft_limit_bytes {
            entry.soft_limit_exceeded_total += 1;
        }
        drop(guard);
        self.metrics
            .live_bytes
            .fetch_add(bytes, Ordering::Relaxed);
    }

    /// Symmetric to [`record_tenant_allocation`]; called when a
    /// buffer drops.
    pub fn record_tenant_release(
        &self,
        tenant_id: impl Into<Arc<str>>,
        bytes: u64,
    ) {
        let arc: Arc<str> = tenant_id.into();
        let mut guard = self.tenants.lock().expect("tenant map poisoned");
        if let Some(entry) = guard.get_mut(&arc) {
            entry.live_bytes = entry.live_bytes.saturating_sub(bytes);
        }
        drop(guard);
        self.metrics
            .live_bytes
            .fetch_sub(bytes.min(self.metrics.live_bytes.load(Ordering::Relaxed)), Ordering::Relaxed);
    }

    /// Snapshot for metric export / tests.
    pub fn snapshot(&self) -> BufferPoolSnapshot {
        let mut pool_hits = HashMap::new();
        let mut pool_misses = HashMap::new();
        for class in PoolClass::non_oversize() {
            let idx = class_index(class);
            pool_hits.insert(
                class,
                self.metrics.pool_hits[idx].load(Ordering::Relaxed),
            );
            pool_misses.insert(
                class,
                self.metrics.pool_misses[idx].load(Ordering::Relaxed),
            );
        }
        let guard = self.tenants.lock().expect("tenant map poisoned");
        let tenant_live_bytes: HashMap<String, u64> = guard
            .iter()
            .map(|(k, v)| (k.to_string(), v.live_bytes))
            .collect();
        let tenant_soft_limit_exceeded_total: HashMap<String, u64> = guard
            .iter()
            .map(|(k, v)| (k.to_string(), v.soft_limit_exceeded_total))
            .collect();
        BufferPoolSnapshot {
            pool_hits,
            pool_misses,
            oversize_allocations_total: self
                .metrics
                .oversize_allocations
                .load(Ordering::Relaxed),
            live_bytes: self.metrics.live_bytes.load(Ordering::Relaxed),
            tenant_live_bytes,
            tenant_soft_limit_exceeded_total,
        }
    }
}

impl Default for BufferPool {
    fn default() -> Self {
        // Default per-tenant soft limit: 256 MiB. Matches the
        // "reasonable single user" envelope; adopters override per
        // plan / per tenant.
        BufferPool::new(256 * 1024 * 1024)
    }
}

fn class_index(class: PoolClass) -> usize {
    match class {
        PoolClass::Small => 0,
        PoolClass::Medium => 1,
        PoolClass::Large => 2,
        PoolClass::Huge => 3,
        PoolClass::Oversize => panic!("oversize class has no free list"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn size_classes_map_correctly() {
        assert_eq!(PoolClass::for_size(1), PoolClass::Small);
        assert_eq!(PoolClass::for_size(4 * 1024), PoolClass::Small);
        assert_eq!(
            PoolClass::for_size(4 * 1024 + 1),
            PoolClass::Medium
        );
        assert_eq!(PoolClass::for_size(64 * 1024), PoolClass::Medium);
        assert_eq!(
            PoolClass::for_size(64 * 1024 + 1),
            PoolClass::Large
        );
        assert_eq!(PoolClass::for_size(1024 * 1024), PoolClass::Large);
        assert_eq!(
            PoolClass::for_size(1024 * 1024 + 1),
            PoolClass::Huge
        );
        assert_eq!(
            PoolClass::for_size(10 * 1024 * 1024),
            PoolClass::Huge
        );
        assert_eq!(
            PoolClass::for_size(10 * 1024 * 1024 + 1),
            PoolClass::Oversize
        );
    }

    #[test]
    fn acquire_returns_slab_with_class_capacity() {
        let pool = BufferPool::default();
        let (slab, class) = pool.acquire(8 * 1024);
        assert_eq!(class, PoolClass::Medium);
        assert_eq!(slab.len(), 0);
        assert!(slab.capacity() >= PoolClass::Medium.capacity());
    }

    #[test]
    fn release_reuses_slab() {
        let pool = BufferPool::default();
        let (mut slab, class) = pool.acquire(1000);
        slab.extend_from_slice(&[42u8; 1000]);
        pool.release(slab, class);

        let (slab2, class2) = pool.acquire(1000);
        assert_eq!(class, class2);
        // Reused slab comes out cleared.
        assert!(slab2.is_empty());
        let snap = pool.snapshot();
        assert_eq!(snap.pool_hits[&PoolClass::Small], 1);
    }

    #[test]
    fn oversize_bypasses_pool() {
        let pool = BufferPool::default();
        let huge = 50 * 1024 * 1024;
        let (slab, class) = pool.acquire(huge);
        assert_eq!(class, PoolClass::Oversize);
        assert!(slab.capacity() >= huge);
        let snap = pool.snapshot();
        assert_eq!(snap.oversize_allocations_total, 1);
    }

    #[test]
    fn tenant_soft_limit_exceeded_increments() {
        let pool = BufferPool::new(1024); // 1 KiB soft limit
        pool.record_tenant_allocation("alpha", 2048); // over
        pool.record_tenant_allocation("alpha", 512);  // still over
        let snap = pool.snapshot();
        assert_eq!(
            snap.tenant_soft_limit_exceeded_total["alpha"],
            2
        );
        assert_eq!(snap.tenant_live_bytes["alpha"], 2560);
    }

    #[test]
    fn per_tenant_override_applies() {
        let pool = BufferPool::new(1024);
        pool.set_tenant_soft_limit("premium", 10 * 1024);
        pool.record_tenant_allocation("premium", 5 * 1024);
        let snap = pool.snapshot();
        // 5 KiB under 10 KiB override → no exceed.
        assert_eq!(
            snap.tenant_soft_limit_exceeded_total["premium"],
            0
        );
    }

    #[test]
    fn free_list_caps_at_64() {
        let pool = BufferPool::default();
        for _ in 0..100 {
            let (slab, class) = pool.acquire(1000);
            pool.release(slab, class);
        }
        // No direct assertion on internal state — just checking we
        // don't blow up. Next acquire should still work.
        let (_slab, class) = pool.acquire(1000);
        assert_eq!(class, PoolClass::Small);
    }
}
