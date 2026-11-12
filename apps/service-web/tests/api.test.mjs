import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = (await readFile(new URL('../src/api.js', import.meta.url), 'utf8')).replaceAll(
  'import.meta.env.VITE_API_BASE',
  '"/api/v1"',
);
const api = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
let store, calls;
function reset() {
  store = new Map();
  calls = [];
  globalThis.sessionStorage = {
    getItem: (k) => store.get(k) || null,
    setItem: (k, v) => store.set(k, v),
    removeItem: (k) => store.delete(k),
  };
  globalThis.window = new EventTarget();
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return new Response(JSON.stringify({ items: [], total: 0, page: 1, size: 20 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
}
test('raw JSON page objects are returned without assuming a data envelope', async () => {
  reset();
  const page = await api.get('/orders?page=1&size=20');
  assert.equal(page.page, 1);
  assert.deepEqual(page.items, []);
  assert.equal(calls[0][0], '/api/v1/orders?page=1&size=20');
});
test('Bearer authentication is sent only from the locally verified session', async () => {
  reset();
  api.saveSession({ token: 'test-token', user: { id: 'u' } });
  await api.get('/auth/me');
  assert.equal(calls[0][1].headers.Authorization, 'Bearer test-token');
  assert.equal(calls[0][1].cache, 'no-store');
});
test('401 clears local login and notifies the application', async () => {
  reset();
  api.saveSession({ token: 'expired' });
  let expired = false;
  window.addEventListener('tk:unauthorized', () => (expired = true));
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: 'UNAUTHORIZED', message: '登录已过期' }), { status: 401 });
  await assert.rejects(api.get('/auth/me'), (e) => e.status === 401 && e.message === '登录已过期');
  assert.equal(api.session(), null);
  assert.ok(expired);
});
test('multipart uploads let the browser supply the boundary', async () => {
  reset();
  const body = new FormData();
  body.append('source', 'WEB');
  await api.post('/sessions/s/files', body);
  assert.equal(calls[0][1].body, body);
  assert.equal(calls[0][1].headers['Content-Type'], undefined);
});
test('a timed-out mutation is not automatically retried', async () => {
  reset();
  globalThis.fetch = async (_url, options) => {
    calls.push(options);
    return new Promise((resolve, reject) =>
      options.signal.addEventListener(
        'abort',
        () => reject(new DOMException('Aborted', 'AbortError')),
        { once: true },
      ),
    );
  };
  await assert.rejects(
    api.post('/sessions/s/quotes', { idempotencyKey: 'fixed-request' }, { timeout: 2 }),
    (e) => e.code === 'TIMEOUT',
  );
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(calls[0].body).idempotencyKey, 'fixed-request');
});
test('authorization failures preserve the server business error without pretending success', async () => {
  reset();
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: 'FORBIDDEN', message: '无权查看此组织' }), { status: 403 });
  await assert.rejects(api.get('/orders/o'), (e) => e.status === 403 && e.code === 'FORBIDDEN');
});
test('query parameters are encoded rather than concatenated from search text', () => {
  assert.equal(
    api.query({ search: '云A&status=CANCELLED', page: 1, status: '' }),
    'search=%E4%BA%91A%26status%3DCANCELLED&page=1',
  );
});
