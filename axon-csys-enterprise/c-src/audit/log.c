/* §Fase 27.d — Tamper-evident mmap-backed audit log (impl).
 *
 * On-disk layout (little-endian throughout — drift gate verifies
 * cross-platform byte-identity):
 *
 *   [segment_header  :256]
 *   [block_0         :variable]
 *   [block_1         :variable]
 *   ...
 *   [block_N         :variable]
 *   [unused capacity :variable]
 *
 * Segment header (256 bytes total, cache-line-aligned to 64 bytes):
 *
 *   offset 0    char     magic[8]                 // "AXENALOG"
 *   offset 8    u32      format_version           // = 1
 *   offset 12   u32      header_size              // = 256
 *   offset 16   u64      tenant_id
 *   offset 24   u64      segment_id
 *   offset 32   u64      segment_capacity_bytes
 *   offset 40   i64      created_ms
 *   offset 48   u8       prev_segment_tail_hash[32]
 *   offset 80   _Atomic u64 head_offset           // committed cursor (post-header)
 *   offset 88   _Atomic u64 event_count           // committed event total
 *   offset 96   u8       reserved[160]            // zeroed; future fields
 *
 * Block layout (64-byte aligned header + payload + 32-byte seal):
 *
 *   offset 0    u8       prev_hash[32]            // previous block's seal_mac
 *                                                  // (or segment header's prev_segment_tail_hash for block 0)
 *   offset 32   i64      timestamp_ms
 *   offset 40   u64      event_id
 *   offset 48   u32      payload_len
 *   offset 52   u8       reserved[12]             // zeroed
 *   offset 64   u8       payload[payload_len]
 *   offset 64+L u8       seal_mac[32]
 *
 *   seal_mac = HMAC-SHA256(tenant_key, header[..64] || payload[..len])
 *
 * The chain is forward-only: appending event N requires reading
 * event N-1's seal_mac (or, for N=0, the segment's
 * prev_segment_tail_hash). Tamper detection runs by walking events
 * in order, recomputing each seal_mac, and asserting the chain
 * matches.
 */

#include "log.h"

#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#else
#  include <fcntl.h>
#  include <pthread.h>
#  include <sys/mman.h>
#  include <sys/stat.h>
#  include <sys/types.h>
#  include <unistd.h>
#endif

/* ──────────────────────────────────────────────────────────────────
 * HMAC-SHA256 routing — picks up the FIPS-routed path under a FIPS
 * feature, else the OSS pure-C path. Same convention as the rest
 * of the enterprise crate: a single trampoline keeps the per-site
 * #ifdef noise contained.
 *
 * The void-return-form is OSS axon-csys's signature; we wrap it to
 * the int-return shape this kernel uses internally.
 * ────────────────────────────────────────────────────────────────── */

#if defined(AXON_CSYS_ENTERPRISE_FIPS_BORINGSSL) \
 || defined(AXON_CSYS_ENTERPRISE_FIPS_OPENSSL)
extern int axon_csys_enterprise_hmac_sha256(
    const uint8_t *key, size_t key_len,
    const uint8_t *data, size_t data_len,
    uint8_t *out);
#  define AUDIT_HMAC_BACKEND axon_csys_enterprise_hmac_sha256
#else
/* OSS axon-csys signature (Fase 25.h c-src/crypto/hmac.h). */
extern void axon_csys_hmac_sha256(
    const uint8_t *key, size_t key_len,
    const uint8_t *data, size_t data_len,
    uint8_t *out);
static int audit_oss_hmac_trampoline(
    const uint8_t *key, size_t key_len,
    const uint8_t *data, size_t data_len,
    uint8_t *out) {
    axon_csys_hmac_sha256(key, key_len, data, data_len, out);
    return 0;
}
#  define AUDIT_HMAC_BACKEND audit_oss_hmac_trampoline
#endif

/* ──────────────────────────────────────────────────────────────────
 * On-disk byte-offset helpers — explicit memcpy + little-endian
 * encoding so cross-platform builds produce byte-identical files.
 * Byte-identity verified by the cross-stack drift gate (Fase 27.i).
 * ────────────────────────────────────────────────────────────────── */

static void le_store_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xff);
    p[1] = (uint8_t)((v >> 8) & 0xff);
    p[2] = (uint8_t)((v >> 16) & 0xff);
    p[3] = (uint8_t)((v >> 24) & 0xff);
}

static void le_store_u64(uint8_t *p, uint64_t v) {
    for (size_t i = 0; i < 8; ++i) {
        p[i] = (uint8_t)((v >> (i * 8)) & 0xff);
    }
}

static void le_store_i64(uint8_t *p, int64_t v) {
    /* Two's complement is C23-mandated for signed integers; bitwise
     * cast to u64 preserves the byte representation. */
    le_store_u64(p, (uint64_t)v);
}

static uint32_t le_load_u32(const uint8_t *p) {
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

static uint64_t le_load_u64(const uint8_t *p) {
    uint64_t v = 0;
    for (size_t i = 0; i < 8; ++i) {
        v |= (uint64_t)p[i] << (i * 8);
    }
    return v;
}

static int64_t le_load_i64(const uint8_t *p) {
    return (int64_t)le_load_u64(p);
}

/* ──────────────────────────────────────────────────────────────────
 * Header field offsets (verified against the spec block at the top
 * of this file). Compile-time `static_assert` would be nice here
 * but C23's _Static_assert is at file scope — kept as constants and
 * checked at runtime via _Static_assert at the bottom.
 * ────────────────────────────────────────────────────────────────── */

#define HDR_OFF_MAGIC                  ((size_t)0)
#define HDR_OFF_FORMAT_VERSION         ((size_t)8)
#define HDR_OFF_HEADER_SIZE            ((size_t)12)
#define HDR_OFF_TENANT_ID              ((size_t)16)
#define HDR_OFF_SEGMENT_ID             ((size_t)24)
#define HDR_OFF_SEGMENT_CAPACITY       ((size_t)32)
#define HDR_OFF_CREATED_MS             ((size_t)40)
#define HDR_OFF_PREV_SEGMENT_TAIL_HASH ((size_t)48)
#define HDR_OFF_HEAD_OFFSET            ((size_t)80)
#define HDR_OFF_EVENT_COUNT            ((size_t)88)

#define BLK_OFF_PREV_HASH              ((size_t)0)
#define BLK_OFF_TIMESTAMP_MS           ((size_t)32)
#define BLK_OFF_EVENT_ID               ((size_t)40)
#define BLK_OFF_PAYLOAD_LEN            ((size_t)48)

/* ──────────────────────────────────────────────────────────────────
 * Cross-platform mmap abstraction
 *
 * Two distinct paths:
 *
 *   POSIX (Linux + macOS + BSD): file descriptor + mmap + msync;
 *   pthread mutex for the writer's append serialization.
 *
 *   Windows: HANDLE + CreateFileMapping + MapViewOfFile +
 *   FlushViewOfFile; CRITICAL_SECTION for the writer's mutex.
 *
 * Both paths share the same `audit_mmap` struct that the upper
 * layers consume. Failures funnel into AXON_AUDIT_ERR_* codes.
 * ────────────────────────────────────────────────────────────────── */

typedef struct {
    void *addr;
    size_t size;
    int writable;
#ifdef _WIN32
    HANDLE file_handle;
    HANDLE map_handle;
#else
    int fd;
#endif
} audit_mmap;

#ifdef _WIN32
typedef CRITICAL_SECTION audit_mutex;
static void audit_mutex_init(audit_mutex *m) { InitializeCriticalSection(m); }
static void audit_mutex_destroy(audit_mutex *m) { DeleteCriticalSection(m); }
static void audit_mutex_lock(audit_mutex *m) { EnterCriticalSection(m); }
static void audit_mutex_unlock(audit_mutex *m) { LeaveCriticalSection(m); }
#else
typedef pthread_mutex_t audit_mutex;
static void audit_mutex_init(audit_mutex *m) { pthread_mutex_init(m, NULL); }
static void audit_mutex_destroy(audit_mutex *m) { pthread_mutex_destroy(m); }
static void audit_mutex_lock(audit_mutex *m) { pthread_mutex_lock(m); }
static void audit_mutex_unlock(audit_mutex *m) { pthread_mutex_unlock(m); }
#endif

static int audit_mmap_open(const char *path, int writable, size_t want_size,
                           audit_mmap *out) {
    if (path == NULL || out == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    memset(out, 0, sizeof(*out));
    out->writable = writable;

#ifdef _WIN32
    DWORD desired_access = writable ? (GENERIC_READ | GENERIC_WRITE) : GENERIC_READ;
    DWORD share_mode = FILE_SHARE_READ;
    DWORD creation = writable ? OPEN_ALWAYS : OPEN_EXISTING;
    HANDLE fh = CreateFileA(path, desired_access, share_mode, NULL, creation,
                            FILE_ATTRIBUTE_NORMAL, NULL);
    if (fh == INVALID_HANDLE_VALUE) {
        return AXON_AUDIT_ERR_OPEN_FAILED;
    }
    LARGE_INTEGER current_size;
    if (!GetFileSizeEx(fh, &current_size)) {
        CloseHandle(fh);
        return AXON_AUDIT_ERR_IO;
    }
    size_t actual_size = (size_t)current_size.QuadPart;
    if (writable && want_size > actual_size) {
        LARGE_INTEGER target = {0};
        target.QuadPart = (LONGLONG)want_size;
        if (!SetFilePointerEx(fh, target, NULL, FILE_BEGIN) || !SetEndOfFile(fh)) {
            CloseHandle(fh);
            return AXON_AUDIT_ERR_IO;
        }
        actual_size = want_size;
    }
    if (actual_size == 0) {
        CloseHandle(fh);
        return AXON_AUDIT_ERR_TRUNCATED;
    }
    DWORD prot = writable ? PAGE_READWRITE : PAGE_READONLY;
    HANDLE mh = CreateFileMappingA(fh, NULL, prot, 0, 0, NULL);
    if (mh == NULL) {
        CloseHandle(fh);
        return AXON_AUDIT_ERR_MMAP_FAILED;
    }
    DWORD view_access = writable ? FILE_MAP_ALL_ACCESS : FILE_MAP_READ;
    void *addr = MapViewOfFile(mh, view_access, 0, 0, actual_size);
    if (addr == NULL) {
        CloseHandle(mh);
        CloseHandle(fh);
        return AXON_AUDIT_ERR_MMAP_FAILED;
    }
    out->file_handle = fh;
    out->map_handle = mh;
    out->addr = addr;
    out->size = actual_size;
    return AXON_AUDIT_OK;
#else
    int flags = writable ? (O_RDWR | O_CREAT) : O_RDONLY;
    int fd = open(path, flags, 0600);
    if (fd < 0) {
        return AXON_AUDIT_ERR_OPEN_FAILED;
    }
    struct stat st;
    if (fstat(fd, &st) < 0) {
        close(fd);
        return AXON_AUDIT_ERR_IO;
    }
    size_t actual_size = (size_t)st.st_size;
    if (writable && want_size > actual_size) {
        if (ftruncate(fd, (off_t)want_size) < 0) {
            close(fd);
            return AXON_AUDIT_ERR_IO;
        }
        actual_size = want_size;
    }
    if (actual_size == 0) {
        close(fd);
        return AXON_AUDIT_ERR_TRUNCATED;
    }
    int prot = writable ? (PROT_READ | PROT_WRITE) : PROT_READ;
    void *addr = mmap(NULL, actual_size, prot, MAP_SHARED, fd, 0);
    if (addr == MAP_FAILED) {
        close(fd);
        return AXON_AUDIT_ERR_MMAP_FAILED;
    }
    out->fd = fd;
    out->addr = addr;
    out->size = actual_size;
    return AXON_AUDIT_OK;
#endif
}

static int audit_mmap_sync(audit_mmap *m) {
    if (m == NULL || m->addr == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
#ifdef _WIN32
    if (!FlushViewOfFile(m->addr, m->size)) {
        return AXON_AUDIT_ERR_IO;
    }
    if (!FlushFileBuffers(m->file_handle)) {
        return AXON_AUDIT_ERR_IO;
    }
#else
    if (msync(m->addr, m->size, MS_SYNC) < 0) {
        return AXON_AUDIT_ERR_IO;
    }
#endif
    return AXON_AUDIT_OK;
}

static void audit_mmap_close(audit_mmap *m) {
    if (m == NULL) return;
#ifdef _WIN32
    if (m->addr != NULL) UnmapViewOfFile(m->addr);
    if (m->map_handle != NULL) CloseHandle(m->map_handle);
    if (m->file_handle != NULL && m->file_handle != INVALID_HANDLE_VALUE) {
        CloseHandle(m->file_handle);
    }
#else
    if (m->addr != NULL && m->size > 0) munmap(m->addr, m->size);
    if (m->fd > 0) close(m->fd);
#endif
    memset(m, 0, sizeof(*m));
}

/* ──────────────────────────────────────────────────────────────────
 * Writer + Verifier internals
 * ────────────────────────────────────────────────────────────────── */

struct AxonAuditLogWriter {
    audit_mmap mmap;
    audit_mutex append_lock;
    uint8_t tenant_key[AXON_AUDIT_MAX_TENANT_KEY_BYTES];
    size_t tenant_key_len;
    uint64_t tenant_id;
    uint64_t segment_id;
    uint8_t last_seal_mac[AXON_AUDIT_HASH_SIZE]; /* cached for prev_hash chaining */
    int last_seal_initialized;                   /* 0 until we know the chain anchor */
};

struct AxonAuditLogVerifier {
    audit_mmap mmap;
    uint8_t tenant_key[AXON_AUDIT_MAX_TENANT_KEY_BYTES];
    size_t tenant_key_len;
    uint8_t last_seal_mac[AXON_AUDIT_HASH_SIZE]; /* populated by verify/iterate */
    int last_seal_initialized;
};

/* Helpers — read + atomic-load fields from the segment header. */
static uint64_t header_load_atomic_u64(const uint8_t *base, size_t off) {
    /* The atomic fields live at fixed offsets; we cast the storage
     * to _Atomic u64 for the load. cc-rs ensures the underlying
     * memory is naturally 8-byte aligned because the segment header
     * itself is page-aligned (mmap returns a page-aligned address). */
    const _Atomic uint64_t *p = (const _Atomic uint64_t *)(base + off);
    return atomic_load_explicit(p, memory_order_acquire);
}

static void header_store_atomic_u64(uint8_t *base, size_t off, uint64_t val) {
    _Atomic uint64_t *p = (_Atomic uint64_t *)(base + off);
    atomic_store_explicit(p, val, memory_order_release);
}

/* Write the magic + format + size fields into a freshly-zeroed
 * mmap region. */
static void header_init(uint8_t *base, uint64_t tenant_id, uint64_t segment_id,
                        size_t segment_capacity_bytes,
                        const uint8_t *prev_segment_tail_hash) {
    memset(base, 0, AXON_AUDIT_HEADER_SIZE);
    memcpy(base + HDR_OFF_MAGIC, AXON_AUDIT_MAGIC, AXON_AUDIT_MAGIC_LEN);
    le_store_u32(base + HDR_OFF_FORMAT_VERSION, AXON_AUDIT_FORMAT_VERSION);
    le_store_u32(base + HDR_OFF_HEADER_SIZE, (uint32_t)AXON_AUDIT_HEADER_SIZE);
    le_store_u64(base + HDR_OFF_TENANT_ID, tenant_id);
    le_store_u64(base + HDR_OFF_SEGMENT_ID, segment_id);
    le_store_u64(base + HDR_OFF_SEGMENT_CAPACITY, (uint64_t)segment_capacity_bytes);

    /* Wall-clock created_ms — adopters that want a monotonic clock
     * can post-process. We use realtime + millisecond conversion;
     * test code can mock this via setting AXON_AUDIT_FIXED_CREATED_MS
     * env var (handled at a higher layer). */
    int64_t now_ms = 0;
#ifdef _WIN32
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER u;
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    /* FILETIME is 100-ns intervals since 1601-01-01; convert to ms
     * since epoch (1970-01-01). */
    now_ms = (int64_t)((u.QuadPart - 116444736000000000ULL) / 10000ULL);
#else
    struct timespec ts;
    if (clock_gettime(CLOCK_REALTIME, &ts) == 0) {
        now_ms = (int64_t)ts.tv_sec * 1000 + (int64_t)(ts.tv_nsec / 1000000);
    }
#endif
    le_store_i64(base + HDR_OFF_CREATED_MS, now_ms);

    if (prev_segment_tail_hash != NULL) {
        memcpy(base + HDR_OFF_PREV_SEGMENT_TAIL_HASH, prev_segment_tail_hash,
               AXON_AUDIT_HASH_SIZE);
    }
    header_store_atomic_u64(base, HDR_OFF_HEAD_OFFSET, AXON_AUDIT_HEADER_SIZE);
    header_store_atomic_u64(base, HDR_OFF_EVENT_COUNT, 0);
}

/* Validate magic + format + tenant_id of an existing header. */
static int header_validate(const uint8_t *base, size_t total_size, uint64_t tenant_id) {
    if (total_size < AXON_AUDIT_HEADER_SIZE) {
        return AXON_AUDIT_ERR_TRUNCATED;
    }
    if (memcmp(base + HDR_OFF_MAGIC, AXON_AUDIT_MAGIC, AXON_AUDIT_MAGIC_LEN) != 0) {
        return AXON_AUDIT_ERR_BAD_MAGIC;
    }
    if (le_load_u32(base + HDR_OFF_FORMAT_VERSION) != AXON_AUDIT_FORMAT_VERSION) {
        return AXON_AUDIT_ERR_BAD_VERSION;
    }
    if (tenant_id != UINT64_MAX) {
        uint64_t got = le_load_u64(base + HDR_OFF_TENANT_ID);
        if (got != tenant_id) {
            return AXON_AUDIT_ERR_TENANT_MISMATCH;
        }
    }
    return AXON_AUDIT_OK;
}

/* ──────────────────────────────────────────────────────────────────
 * Public writer surface
 * ────────────────────────────────────────────────────────────────── */

int axon_audit_log_writer_open(
    const char *path,
    uint64_t tenant_id,
    uint64_t segment_id,
    size_t segment_capacity_bytes,
    const uint8_t *tenant_key,
    size_t tenant_key_len,
    const uint8_t *prev_segment_tail_hash,
    AxonAuditLogWriter **out_writer) {
    if (path == NULL || tenant_key == NULL || out_writer == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    if (tenant_key_len == 0 || tenant_key_len > AXON_AUDIT_MAX_TENANT_KEY_BYTES) {
        return AXON_AUDIT_ERR_KEY_TOO_LARGE;
    }
    if (segment_capacity_bytes < AXON_AUDIT_MIN_SEGMENT_BYTES) {
        return AXON_AUDIT_ERR_SEGMENT_TOO_SMALL;
    }

    AxonAuditLogWriter *w = (AxonAuditLogWriter *)calloc(1, sizeof(*w));
    if (w == NULL) {
        return AXON_AUDIT_ERR_OUT_OF_MEMORY;
    }
    audit_mutex_init(&w->append_lock);
    memcpy(w->tenant_key, tenant_key, tenant_key_len);
    w->tenant_key_len = tenant_key_len;
    w->tenant_id = tenant_id;
    w->segment_id = segment_id;

    int rc = audit_mmap_open(path, /*writable=*/1, segment_capacity_bytes, &w->mmap);
    if (rc != AXON_AUDIT_OK) {
        audit_mutex_destroy(&w->append_lock);
        free(w);
        return rc;
    }

    uint8_t *base = (uint8_t *)w->mmap.addr;

    /* Detect first-open-of-fresh-file vs reopen-of-existing-segment.
     * A freshly-truncated file is all zeros; the magic field will
     * NOT match. In that case we initialize the header. */
    int validate_rc = header_validate(base, w->mmap.size, UINT64_MAX);
    if (validate_rc == AXON_AUDIT_ERR_BAD_MAGIC) {
        header_init(base, tenant_id, segment_id, segment_capacity_bytes,
                    prev_segment_tail_hash);
        if (prev_segment_tail_hash != NULL) {
            memcpy(w->last_seal_mac, prev_segment_tail_hash, AXON_AUDIT_HASH_SIZE);
            w->last_seal_initialized = 1;
        }
    } else if (validate_rc != AXON_AUDIT_OK) {
        audit_mmap_close(&w->mmap);
        audit_mutex_destroy(&w->append_lock);
        free(w);
        return validate_rc;
    } else {
        /* Existing segment — confirm tenant_id matches. */
        if (le_load_u64(base + HDR_OFF_TENANT_ID) != tenant_id) {
            audit_mmap_close(&w->mmap);
            audit_mutex_destroy(&w->append_lock);
            free(w);
            return AXON_AUDIT_ERR_TENANT_MISMATCH;
        }
        /* Best-effort recovery of last_seal_mac: walk the chain
         * to populate `last_seal_mac` for prev_hash chaining. The
         * verifier re-uses this code path. */
        uint64_t head = header_load_atomic_u64(base, HDR_OFF_HEAD_OFFSET);
        if (head > AXON_AUDIT_HEADER_SIZE) {
            /* Walk to the last block. We trust the head offset is
             * consistent (the writer-side mutex guarantees it).
             *
             * The simplest recovery is to scan from the start; for
             * the v1.0 ship that's acceptable since reopens are
             * rare. A future v0.2 optimization could store a
             * tail-hash-cache in the segment trailer. */
            uint64_t off = AXON_AUDIT_HEADER_SIZE;
            while (off + AXON_AUDIT_BLOCK_HEADER_SIZE <= head) {
                uint8_t *blk = base + off;
                uint32_t payload_len = le_load_u32(blk + BLK_OFF_PAYLOAD_LEN);
                uint64_t blk_size = AXON_AUDIT_BLOCK_HEADER_SIZE
                                  + (uint64_t)payload_len
                                  + AXON_AUDIT_HASH_SIZE;
                if (off + blk_size > head) break;
                /* Copy this block's seal_mac. */
                memcpy(w->last_seal_mac,
                       blk + AXON_AUDIT_BLOCK_HEADER_SIZE + payload_len,
                       AXON_AUDIT_HASH_SIZE);
                w->last_seal_initialized = 1;
                off += blk_size;
            }
        } else if (prev_segment_tail_hash != NULL) {
            memcpy(w->last_seal_mac, prev_segment_tail_hash, AXON_AUDIT_HASH_SIZE);
            w->last_seal_initialized = 1;
        }
    }

    *out_writer = w;
    return AXON_AUDIT_OK;
}

int axon_audit_log_writer_append(
    AxonAuditLogWriter *writer,
    int64_t timestamp_ms,
    const uint8_t *payload,
    size_t payload_len,
    uint8_t *out_seal_mac,
    uint64_t *out_event_id) {
    if (writer == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    if (payload == NULL && payload_len > 0) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    if (payload_len > AXON_AUDIT_MAX_PAYLOAD_BYTES) {
        return AXON_AUDIT_ERR_PAYLOAD_TOO_LARGE;
    }

    audit_mutex_lock(&writer->append_lock);

    uint8_t *base = (uint8_t *)writer->mmap.addr;
    uint64_t head = header_load_atomic_u64(base, HDR_OFF_HEAD_OFFSET);
    uint64_t blk_size = AXON_AUDIT_BLOCK_HEADER_SIZE + (uint64_t)payload_len
                      + AXON_AUDIT_HASH_SIZE;
    if (head + blk_size > writer->mmap.size) {
        audit_mutex_unlock(&writer->append_lock);
        return AXON_AUDIT_ERR_SEGMENT_FULL;
    }

    /* Build the block header in-place (mmap memory). */
    uint8_t *blk = base + head;
    /* prev_hash field — chained from last_seal_mac (or zeros if
     * this is a brand-new chain with no prior seal). */
    if (writer->last_seal_initialized) {
        memcpy(blk + BLK_OFF_PREV_HASH, writer->last_seal_mac,
               AXON_AUDIT_HASH_SIZE);
    } else {
        /* prev_segment_tail_hash from header, even if zeroed. */
        memcpy(blk + BLK_OFF_PREV_HASH, base + HDR_OFF_PREV_SEGMENT_TAIL_HASH,
               AXON_AUDIT_HASH_SIZE);
    }
    le_store_i64(blk + BLK_OFF_TIMESTAMP_MS, timestamp_ms);
    uint64_t event_id = header_load_atomic_u64(base, HDR_OFF_EVENT_COUNT);
    le_store_u64(blk + BLK_OFF_EVENT_ID, event_id);
    le_store_u32(blk + BLK_OFF_PAYLOAD_LEN, (uint32_t)payload_len);
    /* Reserved bytes (52..64) are already zero from header_init or
     * a fresh truncate; explicitly write zeros to be safe on reopen
     * paths where the bytes might be stale. */
    memset(blk + 52, 0, 12);

    /* Copy payload. */
    if (payload_len > 0) {
        memcpy(blk + AXON_AUDIT_BLOCK_HEADER_SIZE, payload, payload_len);
    }

    /* Compute seal_mac = HMAC-SHA256(tenant_key,
     *   header_bytes[0..64] || payload[0..payload_len])
     *
     * We HMAC over the header + payload as one stream — equivalent
     * to two updates with one final, byte-identical to the OSS
     * one-shot path used in tests/drift_gate. */
    size_t mac_len = AXON_AUDIT_BLOCK_HEADER_SIZE + payload_len;
    uint8_t *mac_target = blk + AXON_AUDIT_BLOCK_HEADER_SIZE + payload_len;

    int hmac_rc = AUDIT_HMAC_BACKEND(writer->tenant_key, writer->tenant_key_len,
                                     blk, mac_len, mac_target);
    if (hmac_rc != 0) {
        /* HMAC failure (FIPS POST fail). Don't commit the block —
         * roll back by leaving head_offset unchanged. The bytes we
         * scribbled into the mmap are NOT visible to readers because
         * we haven't bumped the atomic head yet. */
        audit_mutex_unlock(&writer->append_lock);
        return AXON_AUDIT_ERR_IO;
    }

    /* Update last_seal_mac for the next append's prev_hash. */
    memcpy(writer->last_seal_mac, mac_target, AXON_AUDIT_HASH_SIZE);
    writer->last_seal_initialized = 1;

    /* Out-params first, then the atomic publish. */
    if (out_seal_mac != NULL) {
        memcpy(out_seal_mac, mac_target, AXON_AUDIT_HASH_SIZE);
    }
    if (out_event_id != NULL) {
        *out_event_id = event_id;
    }

    /* Publish: bump event_count first (acts as visibility fence),
     * then head_offset. Readers load event_count → confirm the
     * block at `head_offset - blk_size` is committed. */
    header_store_atomic_u64(base, HDR_OFF_EVENT_COUNT, event_id + 1);
    header_store_atomic_u64(base, HDR_OFF_HEAD_OFFSET, head + blk_size);

    audit_mutex_unlock(&writer->append_lock);
    return AXON_AUDIT_OK;
}

int axon_audit_log_writer_stats(
    const AxonAuditLogWriter *writer,
    AxonAuditLogStats *out_stats) {
    if (writer == NULL || out_stats == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    const uint8_t *base = (const uint8_t *)writer->mmap.addr;
    out_stats->tenant_id = le_load_u64(base + HDR_OFF_TENANT_ID);
    out_stats->segment_id = le_load_u64(base + HDR_OFF_SEGMENT_ID);
    out_stats->segment_capacity_bytes = le_load_u64(base + HDR_OFF_SEGMENT_CAPACITY);
    out_stats->created_ms = le_load_i64(base + HDR_OFF_CREATED_MS);
    out_stats->head_offset = header_load_atomic_u64(base, HDR_OFF_HEAD_OFFSET);
    out_stats->event_count = header_load_atomic_u64(base, HDR_OFF_EVENT_COUNT);
    return AXON_AUDIT_OK;
}

int axon_audit_log_writer_sync(AxonAuditLogWriter *writer) {
    if (writer == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    return audit_mmap_sync(&writer->mmap);
}

void axon_audit_log_writer_close(AxonAuditLogWriter *writer) {
    if (writer == NULL) return;
    audit_mmap_close(&writer->mmap);
    audit_mutex_destroy(&writer->append_lock);
    /* Defense in depth — wipe the tenant key on close. Heap memory
     * is about to be free()d but a kernel-level scrubber may scrape
     * the page. */
    memset(writer->tenant_key, 0, sizeof(writer->tenant_key));
    free(writer);
}

/* ──────────────────────────────────────────────────────────────────
 * Public verifier surface
 * ────────────────────────────────────────────────────────────────── */

int axon_audit_log_verifier_open(
    const char *path,
    const uint8_t *tenant_key,
    size_t tenant_key_len,
    AxonAuditLogVerifier **out_verifier) {
    if (path == NULL || tenant_key == NULL || out_verifier == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    if (tenant_key_len == 0 || tenant_key_len > AXON_AUDIT_MAX_TENANT_KEY_BYTES) {
        return AXON_AUDIT_ERR_KEY_TOO_LARGE;
    }

    AxonAuditLogVerifier *v = (AxonAuditLogVerifier *)calloc(1, sizeof(*v));
    if (v == NULL) {
        return AXON_AUDIT_ERR_OUT_OF_MEMORY;
    }
    memcpy(v->tenant_key, tenant_key, tenant_key_len);
    v->tenant_key_len = tenant_key_len;

    int rc = audit_mmap_open(path, /*writable=*/0, 0, &v->mmap);
    if (rc != AXON_AUDIT_OK) {
        free(v);
        return rc;
    }

    rc = header_validate((const uint8_t *)v->mmap.addr, v->mmap.size, UINT64_MAX);
    if (rc != AXON_AUDIT_OK) {
        audit_mmap_close(&v->mmap);
        free(v);
        return rc;
    }

    *out_verifier = v;
    return AXON_AUDIT_OK;
}

int axon_audit_log_verifier_stats(
    const AxonAuditLogVerifier *verifier,
    AxonAuditLogStats *out_stats) {
    if (verifier == NULL || out_stats == NULL) {
        return AXON_AUDIT_ERR_NULL_ARG;
    }
    const uint8_t *base = (const uint8_t *)verifier->mmap.addr;
    out_stats->tenant_id = le_load_u64(base + HDR_OFF_TENANT_ID);
    out_stats->segment_id = le_load_u64(base + HDR_OFF_SEGMENT_ID);
    out_stats->segment_capacity_bytes = le_load_u64(base + HDR_OFF_SEGMENT_CAPACITY);
    out_stats->created_ms = le_load_i64(base + HDR_OFF_CREATED_MS);
    out_stats->head_offset = header_load_atomic_u64(base, HDR_OFF_HEAD_OFFSET);
    out_stats->event_count = header_load_atomic_u64(base, HDR_OFF_EVENT_COUNT);
    return AXON_AUDIT_OK;
}

/* Internal walker used by both verify + iterate. Walks every
 * committed block (up to event_count) and either:
 *   - Checks each seal_mac (if `verify=1`), OR
 *   - Calls the callback (if `cb != NULL`).
 *
 * Sets verifier->last_seal_mac to the last block's seal_mac on
 * success.
 */
static int verifier_walk(
    AxonAuditLogVerifier *v,
    int verify,
    AxonAuditLogIterateCb cb,
    void *user,
    uint64_t *out_failure_event_id,
    int *out_user_rc) {
    const uint8_t *base = (const uint8_t *)v->mmap.addr;
    uint64_t expected_count = header_load_atomic_u64(base, HDR_OFF_EVENT_COUNT);
    uint64_t head = header_load_atomic_u64(base, HDR_OFF_HEAD_OFFSET);
    if (head < AXON_AUDIT_HEADER_SIZE) {
        return AXON_AUDIT_ERR_TRUNCATED;
    }
    if (head > v->mmap.size) {
        return AXON_AUDIT_ERR_TRUNCATED;
    }

    uint64_t off = AXON_AUDIT_HEADER_SIZE;
    uint64_t seen = 0;

    /* prev_hash chain anchor — the segment header's
     * prev_segment_tail_hash. */
    uint8_t expected_prev_hash[AXON_AUDIT_HASH_SIZE];
    memcpy(expected_prev_hash, base + HDR_OFF_PREV_SEGMENT_TAIL_HASH,
           AXON_AUDIT_HASH_SIZE);

    /* Scratch buffer for the recomputed HMAC. */
    uint8_t recomputed_mac[AXON_AUDIT_HASH_SIZE];

    while (seen < expected_count) {
        if (off + AXON_AUDIT_BLOCK_HEADER_SIZE > head) {
            if (out_failure_event_id) *out_failure_event_id = seen;
            return AXON_AUDIT_ERR_TRUNCATED;
        }
        const uint8_t *blk = base + off;
        uint32_t payload_len = le_load_u32(blk + BLK_OFF_PAYLOAD_LEN);
        if (payload_len > AXON_AUDIT_MAX_PAYLOAD_BYTES) {
            if (out_failure_event_id) *out_failure_event_id = seen;
            return AXON_AUDIT_ERR_BAD_PAYLOAD_LEN;
        }
        uint64_t blk_size = AXON_AUDIT_BLOCK_HEADER_SIZE
                          + (uint64_t)payload_len
                          + AXON_AUDIT_HASH_SIZE;
        if (off + blk_size > head) {
            if (out_failure_event_id) *out_failure_event_id = seen;
            return AXON_AUDIT_ERR_TRUNCATED;
        }

        /* prev_hash chain check. */
        if (memcmp(blk + BLK_OFF_PREV_HASH, expected_prev_hash,
                   AXON_AUDIT_HASH_SIZE) != 0) {
            if (out_failure_event_id) *out_failure_event_id = seen;
            return AXON_AUDIT_ERR_CHAIN_BROKEN;
        }

        /* event_id monotonicity check. */
        uint64_t event_id = le_load_u64(blk + BLK_OFF_EVENT_ID);
        if (event_id != seen) {
            if (out_failure_event_id) *out_failure_event_id = seen;
            return AXON_AUDIT_ERR_CHAIN_BROKEN;
        }

        if (verify) {
            /* Recompute the seal_mac. */
            int hrc = AUDIT_HMAC_BACKEND(v->tenant_key, v->tenant_key_len,
                                         blk, AXON_AUDIT_BLOCK_HEADER_SIZE
                                            + (size_t)payload_len,
                                         recomputed_mac);
            if (hrc != 0) {
                if (out_failure_event_id) *out_failure_event_id = seen;
                return AXON_AUDIT_ERR_IO;
            }
            const uint8_t *stored_mac = blk + AXON_AUDIT_BLOCK_HEADER_SIZE
                                      + payload_len;
            if (memcmp(recomputed_mac, stored_mac, AXON_AUDIT_HASH_SIZE) != 0) {
                if (out_failure_event_id) *out_failure_event_id = seen;
                return AXON_AUDIT_ERR_CHAIN_BROKEN;
            }
            memcpy(expected_prev_hash, recomputed_mac, AXON_AUDIT_HASH_SIZE);
            memcpy(v->last_seal_mac, recomputed_mac, AXON_AUDIT_HASH_SIZE);
        } else {
            /* Skip HMAC recompute for non-verify iterate; chain on
             * stored seal_mac for prev_hash forwarding. */
            const uint8_t *stored_mac = blk + AXON_AUDIT_BLOCK_HEADER_SIZE
                                      + payload_len;
            memcpy(expected_prev_hash, stored_mac, AXON_AUDIT_HASH_SIZE);
            memcpy(v->last_seal_mac, stored_mac, AXON_AUDIT_HASH_SIZE);
        }
        v->last_seal_initialized = 1;

        /* Callback dispatch. */
        if (cb != NULL) {
            AxonAuditLogBlock view = {0};
            view.timestamp_ms = le_load_i64(blk + BLK_OFF_TIMESTAMP_MS);
            view.event_id = event_id;
            view.payload_len = payload_len;
            view.payload = blk + AXON_AUDIT_BLOCK_HEADER_SIZE;
            memcpy(view.prev_hash, blk + BLK_OFF_PREV_HASH,
                   AXON_AUDIT_HASH_SIZE);
            memcpy(view.seal_mac,
                   blk + AXON_AUDIT_BLOCK_HEADER_SIZE + payload_len,
                   AXON_AUDIT_HASH_SIZE);
            int user_rc = cb(&view, user);
            if (user_rc != 0) {
                if (out_user_rc) *out_user_rc = user_rc;
                return AXON_AUDIT_OK;
            }
        }

        off += blk_size;
        seen += 1;
    }

    if (off != head) {
        /* head_offset disagrees with walked block sum. Corruption
         * or in-flight write that wasn't published cleanly. */
        if (out_failure_event_id) *out_failure_event_id = seen;
        return AXON_AUDIT_ERR_TRUNCATED;
    }

    return AXON_AUDIT_OK;
}

int axon_audit_log_verifier_verify(
    AxonAuditLogVerifier *verifier,
    uint64_t *out_failure_event_id) {
    if (verifier == NULL) return AXON_AUDIT_ERR_NULL_ARG;
    return verifier_walk(verifier, /*verify=*/1, NULL, NULL,
                         out_failure_event_id, NULL);
}

int axon_audit_log_verifier_iterate(
    AxonAuditLogVerifier *verifier,
    AxonAuditLogIterateCb callback,
    void *user) {
    if (verifier == NULL || callback == NULL) return AXON_AUDIT_ERR_NULL_ARG;
    int user_rc = 0;
    int rc = verifier_walk(verifier, /*verify=*/0, callback, user, NULL,
                           &user_rc);
    if (rc == AXON_AUDIT_OK && user_rc != 0) {
        return user_rc;
    }
    return rc;
}

int axon_audit_log_verifier_tail_hash(
    const AxonAuditLogVerifier *verifier,
    uint8_t out_hash[AXON_AUDIT_HASH_SIZE]) {
    if (verifier == NULL || out_hash == NULL) return AXON_AUDIT_ERR_NULL_ARG;
    if (!verifier->last_seal_initialized) {
        /* Verifier hasn't walked yet — return the segment's
         * prev_segment_tail_hash, which is the chain anchor for an
         * empty segment. */
        const uint8_t *base = (const uint8_t *)verifier->mmap.addr;
        memcpy(out_hash, base + HDR_OFF_PREV_SEGMENT_TAIL_HASH,
               AXON_AUDIT_HASH_SIZE);
    } else {
        memcpy(out_hash, verifier->last_seal_mac, AXON_AUDIT_HASH_SIZE);
    }
    return AXON_AUDIT_OK;
}

void axon_audit_log_verifier_close(AxonAuditLogVerifier *verifier) {
    if (verifier == NULL) return;
    audit_mmap_close(&verifier->mmap);
    memset(verifier->tenant_key, 0, sizeof(verifier->tenant_key));
    free(verifier);
}

/* ──────────────────────────────────────────────────────────────────
 * Error string lookup
 * ────────────────────────────────────────────────────────────────── */

const char *axon_audit_log_error_str(int rc) {
    switch (rc) {
    case AXON_AUDIT_OK:                    return "ok";
    case AXON_AUDIT_ERR_NULL_ARG:          return "null pointer arg";
    case AXON_AUDIT_ERR_INVALID_PATH:      return "invalid path";
    case AXON_AUDIT_ERR_OPEN_FAILED:       return "file open failed";
    case AXON_AUDIT_ERR_MMAP_FAILED:       return "mmap failed";
    case AXON_AUDIT_ERR_BAD_MAGIC:         return "segment header magic mismatch";
    case AXON_AUDIT_ERR_BAD_VERSION:       return "segment header format version mismatch";
    case AXON_AUDIT_ERR_SEGMENT_FULL:      return "segment full (rotate to next)";
    case AXON_AUDIT_ERR_PAYLOAD_TOO_LARGE: return "payload exceeds 16 MiB cap";
    case AXON_AUDIT_ERR_KEY_TOO_LARGE:     return "tenant key length out of range";
    case AXON_AUDIT_ERR_SEGMENT_TOO_SMALL: return "segment capacity below 4 KiB minimum";
    case AXON_AUDIT_ERR_CHAIN_BROKEN:      return "HMAC chain broken (tampered or rotated key)";
    case AXON_AUDIT_ERR_TRUNCATED:         return "segment truncated mid-block";
    case AXON_AUDIT_ERR_BAD_PAYLOAD_LEN:   return "block payload_len exceeds cap";
    case AXON_AUDIT_ERR_TENANT_MISMATCH:   return "tenant_id mismatch";
    case AXON_AUDIT_ERR_IO:                return "I/O failure";
    case AXON_AUDIT_ERR_OUT_OF_MEMORY:     return "out of memory";
    case AXON_AUDIT_ERR_BUFFER_TOO_SMALL:  return "user buffer too small";
    default:                               return "unknown error";
    }
}

/* ──────────────────────────────────────────────────────────────────
 * Compile-time invariants — keep these in lockstep with the spec
 * comment block at the top of the file.
 * ────────────────────────────────────────────────────────────────── */

_Static_assert(AXON_AUDIT_HEADER_SIZE == 256,
               "Segment header size is the load-bearing on-disk constant");
_Static_assert(AXON_AUDIT_BLOCK_HEADER_SIZE == 64,
               "Block header size must match the BLK_OFF_* offsets");
_Static_assert(AXON_AUDIT_HASH_SIZE == 32,
               "SHA-256 / HMAC-SHA256 outputs are 32 bytes");
_Static_assert(HDR_OFF_HEAD_OFFSET == 80,
               "Atomic head_offset position is part of the on-disk ABI");
_Static_assert(HDR_OFF_EVENT_COUNT == 88,
               "Atomic event_count position is part of the on-disk ABI");
