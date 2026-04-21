// Admin API load test — tenant CRUD under a valid operator JWT.

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const ADMIN_JWT = __ENV.ADMIN_JWT;
const PLAN_ID = __ENV.PLAN_ID || 'starter';

const adminReadLatency = new Trend('admin_read_latency_ms');
const adminMutateLatency = new Trend('admin_mutate_latency_ms');
const errors = new Rate('admin_errors');

export const options = {
    scenarios: {
        steady: {
            executor: 'constant-arrival-rate',
            rate: 20,
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: 20,
            maxVUs: 100,
        },
    },
    thresholds: {
        'admin_read_latency_ms': ['p(95)<300', 'p(99)<500'],
        'admin_mutate_latency_ms': ['p(95)<500', 'p(99)<1000'],
        'admin_errors': ['rate<0.005'],
        'http_req_failed': ['rate<0.01'],
    },
};

export default function () {
    const auth = { headers: { Authorization: `Bearer ${ADMIN_JWT}`, 'Content-Type': 'application/json' } };
    const slug = `load-${__VU}-${__ITER}`;

    group('tenant CRUD', () => {
        const created = http.post(
            `${BASE_URL}/admin/tenants/`,
            JSON.stringify({ slug, name: `Load ${slug}`, plan_id: PLAN_ID }),
            { ...auth, tags: { route: 'tenants_create' } },
        );
        adminMutateLatency.add(created.timings.duration);
        if (!check(created, { 'created 201': (r) => r.status === 201 })) {
            errors.add(1);
            return;
        }
        const getResp = http.get(`${BASE_URL}/admin/tenants/${slug}`, { ...auth, tags: { route: 'tenants_get' } });
        adminReadLatency.add(getResp.timings.duration);
        check(getResp, { 'get 200': (r) => r.status === 200 });

        const suspend = http.post(
            `${BASE_URL}/admin/tenants/${slug}/suspend`,
            JSON.stringify({ reason: 'load-test' }),
            { ...auth, tags: { route: 'tenants_suspend' } },
        );
        adminMutateLatency.add(suspend.timings.duration);
        check(suspend, { 'suspended 200': (r) => r.status === 200 });
    });

    sleep(0.5);
}
