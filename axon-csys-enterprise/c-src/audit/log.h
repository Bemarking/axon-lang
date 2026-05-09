/* §Fase 27.d — Tamper-evident mmap-backed audit log.
 *
 * Public C ABI for the append-only audit log kernel. Adopter
 * intent: ~10× faster than the existing axon-rs trace_store path
 * (~500 ns/event versus ~5 µs warm/~25 µs cold) AND tamper-evident
 * via per-block HMAC-SHA256 chain with a per-tenant seal key.
 *
 * Threading model:
 *
 *   Writer side: a single `AxonAuditLogWriter` instance is
 *   intended to serve a single-process, multi-threaded producer.
 *   The internal append path holds a short-lived mutex
 *   (~hundreds of ns) — the lock is uncontested in the warm case
 *   because the bottleneck is HMAC computation. Concurrent
 *   appends from multiple threads are SAFE; concurrent appends
 *   from multiple processes onto the SAME segment file are NOT
 *   supported (each process opens its own segment).
 *
 *   Reader side: `AxonAuditLogVerifier::iterate` walks the segment
 *   without acquiring the writer's lock — readers see a consistent
 *   snapshot up to the published `event_count` atomic in the
 *   segment header. Events past `event_count` may still be in flight
 *   and are skipped.
 *
 * Tamper-evidence model:
 *
 *   Each block's `seal_mac = HMAC-SHA256(tenant_key, prev_hash || header || payload)`.
 *   Mutating any byte in the segment (header, prev_hash, timestamp,
 *   payload, or seal_mac itself) breaks the chain at verify time.
 *   The first block's `prev_hash` is the segment header's
 *   `prev_segment_tail_hash` field — segments chain transitively,
 *   so a tampered byte in segment N is detected even if segment
 *   N's HMAC is forged (the auditor cross-checks N+1's prev_hash).
 *
 * Per-tenant key rotation:
 *
 *   The writer opens with one tenant key. Rotating the key requires
 *   closing the writer + opening a new segment with the new key.
 *   Old segments stay verifiable in perpetuity using their original
 *   key (kept in the tenant's vault per D8 ratified 2026-05-09).
 */

#ifndef AXON_CSYS_ENTERPRISE_AUDIT_LOG_H
#define AXON_CSYS_ENTERPRISE_AUDIT_LOG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ──────────────────────────────────────────────────────────────────
 * On-disk format constants — load-bearing for cross-platform
 * byte-identical drift gate (D7 + D4 — every adopter platform
 * must produce the same bytes for the same input).
 * ────────────────────────────────────────────────────────────────── */

#define AXON_AUDIT_MAGIC                   "AXENALOG"  /* 8 bytes */
#define AXON_AUDIT_MAGIC_LEN               ((size_t)8)
#define AXON_AUDIT_FORMAT_VERSION          ((uint32_t)1)
#define AXON_AUDIT_HEADER_SIZE             ((size_t)256)
#define AXON_AUDIT_HASH_SIZE               ((size_t)32)
#define AXON_AUDIT_BLOCK_HEADER_SIZE       ((size_t)64)
#define AXON_AUDIT_MIN_SEGMENT_BYTES       ((size_t)4096)
#define AXON_AUDIT_DEFAULT_SEGMENT_BYTES   ((size_t)(1024 * 1024))    /* 1 MiB */
#define AXON_AUDIT_MAX_PAYLOAD_BYTES       ((size_t)(16 * 1024 * 1024)) /* 16 MiB */
#define AXON_AUDIT_MAX_TENANT_KEY_BYTES    ((size_t)256)

/* ──────────────────────────────────────────────────────────────────
 * Error codes — stable across releases. Negative for failure;
 * 0 == success. Adopters can match against these constants.
 * ────────────────────────────────────────────────────────────────── */

#define AXON_AUDIT_OK                      ((int)0)
#define AXON_AUDIT_ERR_NULL_ARG            ((int)-1)
#define AXON_AUDIT_ERR_INVALID_PATH        ((int)-2)
#define AXON_AUDIT_ERR_OPEN_FAILED         ((int)-3)
#define AXON_AUDIT_ERR_MMAP_FAILED         ((int)-4)
#define AXON_AUDIT_ERR_BAD_MAGIC           ((int)-5)
#define AXON_AUDIT_ERR_BAD_VERSION         ((int)-6)
#define AXON_AUDIT_ERR_SEGMENT_FULL        ((int)-7)
#define AXON_AUDIT_ERR_PAYLOAD_TOO_LARGE   ((int)-8)
#define AXON_AUDIT_ERR_KEY_TOO_LARGE       ((int)-9)
#define AXON_AUDIT_ERR_SEGMENT_TOO_SMALL   ((int)-10)
#define AXON_AUDIT_ERR_CHAIN_BROKEN        ((int)-11)
#define AXON_AUDIT_ERR_TRUNCATED           ((int)-12)
#define AXON_AUDIT_ERR_BAD_PAYLOAD_LEN     ((int)-13)
#define AXON_AUDIT_ERR_TENANT_MISMATCH     ((int)-14)
#define AXON_AUDIT_ERR_IO                  ((int)-15)
#define AXON_AUDIT_ERR_OUT_OF_MEMORY       ((int)-16)
#define AXON_AUDIT_ERR_BUFFER_TOO_SMALL    ((int)-17)

/* ──────────────────────────────────────────────────────────────────
 * Opaque writer + verifier handles. Allocated by the corresponding
 * `_open` / `_init` functions; freed via `_close` / `_free`.
 * ────────────────────────────────────────────────────────────────── */

typedef struct AxonAuditLogWriter   AxonAuditLogWriter;
typedef struct AxonAuditLogVerifier AxonAuditLogVerifier;

/* Per-segment statistics surface, populated by `axon_audit_log_writer_stats`. */
typedef struct {
    uint64_t tenant_id;
    uint64_t segment_id;
    uint64_t segment_capacity_bytes;
    uint64_t head_offset;        /* current append cursor (post-header) */
    uint64_t event_count;        /* number of committed events */
    int64_t  created_ms;
} AxonAuditLogStats;

/* One iterated block. `payload` points into the segment's mmap; the
 * pointer is valid until the verifier is freed. The verifier keeps
 * the segment mmapped read-only for its lifetime. */
typedef struct {
    int64_t  timestamp_ms;
    uint64_t event_id;
    uint32_t payload_len;
    const uint8_t *payload;
    uint8_t  prev_hash[AXON_AUDIT_HASH_SIZE];
    uint8_t  seal_mac[AXON_AUDIT_HASH_SIZE];
} AxonAuditLogBlock;

/* ──────────────────────────────────────────────────────────────────
 * Writer surface
 *
 * `axon_audit_log_writer_open` creates or re-opens a segment file
 * at `path`. If the file does not exist, it is created and
 * pre-allocated to `segment_capacity_bytes`. If the file exists,
 * the magic + format + tenant_id are verified and the writer
 * resumes appending after the last committed event.
 *
 * `tenant_key` is the per-tenant HMAC seal key. It is NOT persisted
 * to disk — adopters keep it in their vault. The writer copies it
 * internally; the caller may free `tenant_key` after this call
 * returns.
 *
 * `prev_segment_tail_hash` is the seal_mac of the last block in the
 * preceding segment, or NULL/all-zeros for the first segment of a
 * new audit log. This is what makes the chain transitive across
 * segment rotations.
 * ────────────────────────────────────────────────────────────────── */

int axon_audit_log_writer_open(
    const char *path,
    uint64_t tenant_id,
    uint64_t segment_id,
    size_t segment_capacity_bytes,
    const uint8_t *tenant_key,
    size_t tenant_key_len,
    const uint8_t *prev_segment_tail_hash,  /* may be NULL */
    AxonAuditLogWriter **out_writer);

/* Append one event. Returns AXON_AUDIT_OK on success; on segment-
 * full returns AXON_AUDIT_ERR_SEGMENT_FULL (caller should rotate to
 * a new segment + carry over `out_seal_mac` as the new segment's
 * `prev_segment_tail_hash`). On any other error the segment is left
 * in a consistent state (uncommitted bytes, if any, are not exposed
 * to readers).
 *
 * `out_seal_mac` (if non-NULL) receives a copy of the new block's
 * seal_mac — useful for the segment-rotation handoff path.
 * `out_event_id` (if non-NULL) receives the assigned event_id. */
int axon_audit_log_writer_append(
    AxonAuditLogWriter *writer,
    int64_t timestamp_ms,
    const uint8_t *payload,
    size_t payload_len,
    uint8_t *out_seal_mac,        /* may be NULL */
    uint64_t *out_event_id);      /* may be NULL */

/* Read a snapshot of writer stats. Lock-free read of the atomic
 * counters in the segment header. */
int axon_audit_log_writer_stats(
    const AxonAuditLogWriter *writer,
    AxonAuditLogStats *out_stats);

/* Force any pending mmap pages to disk (msync MS_SYNC / FlushViewOfFile).
 * Adopters running federal workloads with strict durability requirements
 * call this after every audit-relevant event; lower-criticality adopters
 * rely on the kernel's natural writeback cadence. */
int axon_audit_log_writer_sync(AxonAuditLogWriter *writer);

/* Close the writer + unmap the segment. After this call, the segment
 * file remains on disk and can be opened by a verifier. */
void axon_audit_log_writer_close(AxonAuditLogWriter *writer);

/* ──────────────────────────────────────────────────────────────────
 * Verifier surface
 *
 * Opens a segment file read-only, walks every committed block,
 * recomputes the HMAC chain, and checks each block's seal_mac
 * against the tenant key. Returns AXON_AUDIT_OK iff every block
 * passes; otherwise the first failure is returned + the offset of
 * the offending block (or AXON_AUDIT_ERR_TRUNCATED for cleanly
 * truncated streams).
 *
 * `iterate` exposes each block via the user callback. The callback
 * may return non-zero to stop iteration early; the verifier
 * propagates the value as the iterate return. The chain is verified
 * even when the callback returns early — partial verification is a
 * useful stat for tooling.
 * ────────────────────────────────────────────────────────────────── */

int axon_audit_log_verifier_open(
    const char *path,
    const uint8_t *tenant_key,
    size_t tenant_key_len,
    AxonAuditLogVerifier **out_verifier);

int axon_audit_log_verifier_stats(
    const AxonAuditLogVerifier *verifier,
    AxonAuditLogStats *out_stats);

/* Verify every committed block. Returns AXON_AUDIT_OK if the chain
 * is intact + every seal_mac matches; otherwise the first failure.
 * `out_failure_event_id` (if non-NULL) receives the event_id of the
 * first failing block — useful for surfacing in the audit-log UI. */
int axon_audit_log_verifier_verify(
    AxonAuditLogVerifier *verifier,
    uint64_t *out_failure_event_id);

/* Iterate each committed block. The callback is called in event-id
 * order. Stops on first AXON_AUDIT_ERR_* or on user callback return
 * != 0. */
typedef int (*AxonAuditLogIterateCb)(const AxonAuditLogBlock *block, void *user);

int axon_audit_log_verifier_iterate(
    AxonAuditLogVerifier *verifier,
    AxonAuditLogIterateCb callback,
    void *user);

/* Read the seal_mac of the last committed block — the value to
 * pass as `prev_segment_tail_hash` when rotating to a new segment. */
int axon_audit_log_verifier_tail_hash(
    const AxonAuditLogVerifier *verifier,
    uint8_t out_hash[AXON_AUDIT_HASH_SIZE]);

void axon_audit_log_verifier_close(AxonAuditLogVerifier *verifier);

/* ──────────────────────────────────────────────────────────────────
 * Stable C string for an error code. Returned pointer has program
 * lifetime; caller MUST NOT free.
 * ────────────────────────────────────────────────────────────────── */

const char *axon_audit_log_error_str(int rc);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* AXON_CSYS_ENTERPRISE_AUDIT_LOG_H */
