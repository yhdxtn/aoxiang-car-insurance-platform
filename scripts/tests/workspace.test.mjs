import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = (path) => readFileSync(join(root, path), 'utf8');

test('mini-program is at the selected path and has a valid AppID', () => {
  const config = JSON.parse(read('miniprogram/project.config.json'));
  assert.match(config.appid, /^wx[0-9a-f]{16}$/);
  assert.ok(existsSync(join(root, 'miniprogram/app.js')));
  assert.equal(existsSync(join(root, 'apps/mini-program')), false);
});

test('deployment exposes LAN web ports but keeps API, MySQL and gateway private', () => {
  const compose = read('deploy/compose.yaml');
  assert.ok(compose.includes('127.0.0.1:18080:18080'));
  assert.ok(compose.includes('${WEB_BIND_IP:-127.0.0.1}:${ADMIN_WEB_PORT:-8088}:80'));
  assert.ok(compose.includes('${WEB_BIND_IP:-127.0.0.1}:${SERVICE_WEB_PORT:-8089}:81'));
  assert.doesNotMatch(compose, /["']\d[^\n]*:(3306|18081)["']/);
});

test('both web cross-links are passed to the Docker build', () => {
  for (const name of ['VITE_ADMIN_URL', 'VITE_SERVICE_URL']) {
    assert.ok(read('deploy/compose.yaml').includes(`${name}:`));
    assert.ok(read('deploy/web.Dockerfile').includes(`ARG ${name}=`));
    assert.ok(read('deploy/web.Dockerfile').includes(`ENV ${name}=`));
  }
});
