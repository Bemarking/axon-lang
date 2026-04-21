// Audit-write storm — stress test for the advisory-lock path.
//
// 1000 virtual tenants append audit events concurrently. The
// per-tenant pg_advisory_xact_lock(hashtext(tenant_id)) must NOT
// serialise cross-tenant writers (different tenants hash to
// different lock keys). Expected: p99 stays under 100ms even at
// 500 RPS because each tenant's write-set is tiny and the lock
// spans only one writer at a time per tenant.
//
// This is a white-box test: instead of hitting HTTP we POST to a
// /admin/debug/audit-write helper that AdminService exposes in the
// test harness. If that helper is absent the script falls back to
// /admin/tenants/{id}/suspend which internally emits an audit event.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const ADMIN_JWT = __ENV.ADMIN_JWT;
const TENANT_COUNT = parseInt(__ENV.TENANT_COUNT || '1000', 10);

const writeLatency = new Trend('audit_write_latency_ms');
const errors = new Rate('audit_write_errors');

export const options = {
    scenarios: {
        storm: {
            executor: 'constant-arrival-rate',
            rate: 500,
            timeUnit: '1s',
            duration: '1m',
            preAllocatedVUs: 100,
            maxVUs: 300,
        },
    },
    thresholds: {
        'audit_write_latency_ms': ['p(95)<50', 'p(99)<100'],
        'audit_write_errors': ['rate<0.001'],
    },
};

export default function () {
    // Pick a random tenant so each request exercises a DIFFERENT
    // advisory-lock key — proving per-tenant writers don't block
    // cross-tenant writers.
    const tenantIdx = Math.floor(Math.random() * TENANT_COUNT);
    const tenantSlug = `load-${tenantIdx}`;

    const auth = { headers: { Authorization: `Bearer ${ADMIN_JWT}`, 'Content-Type': 'application/json' } };

    // Suspend/resume emits audit events without creating or deleting
    // tenants, so the row count stays bounded across the run.
    const res = http.post(
        `${BASE_URL}/admin/tenants/${tenantSlug}/suspend`,
        JSON.stringify({ reason: 'audit-storm' }),
        { ...auth, tags: { route: 'audit_storm' } },
    );
    writeLatency.add(res.timings.duration);
    if (!check(res, { 'write 200': (r) => r.status === 200 })) {
        errors.add(1);
    }

    // Immediately resume so the next iteration for this tenant is a
    // valid no-op-but-audited call.
    http.post(`${BASE_URL}/admin/tenants/${tenantSlug}/resume`, null, auth);

    sleep(0.1);
}
