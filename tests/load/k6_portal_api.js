// Portal API load test — Fase 10.m.
//
// Scenario: a tenant admin logs in, creates + lists + revokes an
// API key, reads the current-period usage dashboard, logs out.
// Runs at 50 RPS for 2 minutes with ramp up/down around it.
//
// SLO thresholds mirror docs/SECURITY_AUDIT.md — a breach fails CI.

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const EMAIL = __ENV.EMAIL;
const PASSWORD = __ENV.PASSWORD;
const TENANT = __ENV.TENANT || 'default';

const loginLatency = new Trend('portal_login_latency_ms');
const readLatency = new Trend('portal_read_latency_ms');
const mutateLatency = new Trend('portal_mutate_latency_ms');
const errors = new Rate('portal_errors');

export const options = {
    scenarios: {
        steady: {
            executor: 'constant-arrival-rate',
            rate: 50,
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: 50,
            maxVUs: 200,
        },
    },
    thresholds: {
        'portal_read_latency_ms': ['p(95)<300', 'p(99)<500'],
        'portal_mutate_latency_ms': ['p(95)<500', 'p(99)<1000'],
        'portal_errors': ['rate<0.005'],
        'http_req_failed': ['rate<0.01'],
    },
};

function login() {
    const res = http.post(
        `${BASE_URL}/api/v1/auth/login`,
        JSON.stringify({ email: EMAIL, password: PASSWORD, tenant_id: TENANT }),
        { headers: { 'Content-Type': 'application/json' }, tags: { route: 'login' } },
    );
    loginLatency.add(res.timings.duration);
    const ok = check(res, {
        'login 200': (r) => r.status === 200,
        'access_token present': (r) => r.json('access_token') !== undefined,
    });
    if (!ok) {
        errors.add(1);
        return null;
    }
    return res.json('access_token');
}

export default function () {
    const token = login();
    if (!token) { sleep(1); return; }
    const auth = { headers: { Authorization: `Bearer ${token}` } };

    group('api-key CRUD', () => {
        const created = http.post(
            `${BASE_URL}/api/v1/tenant/api-keys/`,
            JSON.stringify({ name: `load-${__VU}-${__ITER}` }),
            { headers: { ...auth.headers, 'Content-Type': 'application/json' }, tags: { route: 'api_keys_create' } },
        );
        mutateLatency.add(created.timings.duration);
        if (!check(created, { 'created 201': (r) => r.status === 201 })) {
            errors.add(1);
            return;
        }
        const id = created.json('api_key_id');

        const list = http.get(
            `${BASE_URL}/api/v1/tenant/api-keys/`,
            { ...auth, tags: { route: 'api_keys_list' } },
        );
        readLatency.add(list.timings.duration);
        check(list, { 'list 200': (r) => r.status === 200 });

        const revoked = http.del(
            `${BASE_URL}/api/v1/tenant/api-keys/${id}`,
            null,
            { ...auth, tags: { route: 'api_keys_revoke' } },
        );
        mutateLatency.add(revoked.timings.duration);
        check(revoked, { 'revoked 200': (r) => r.status === 200 });
    });

    group('usage dashboard', () => {
        const usage = http.get(
            `${BASE_URL}/api/v1/tenant/usage/`,
            { ...auth, tags: { route: 'usage' } },
        );
        readLatency.add(usage.timings.duration);
        check(usage, { 'usage 200': (r) => r.status === 200 });
    });

    sleep(0.5);
}
