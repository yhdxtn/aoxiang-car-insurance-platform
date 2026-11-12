import test from 'node:test';
import assert from 'node:assert/strict';
import { createVisiblePoller } from '../src/polling.js';
function harness(run) {
  let now = 0,
    visible = true,
    timers = new Map(),
    id = 0,
    paused = 0;
  const poller = createVisiblePoller({
    run,
    isVisible: () => visible,
    now: () => now,
    setTimer: (fn, ms) => {
      timers.set(++id, { fn, ms });
      return id;
    },
    clearTimer: (id) => timers.delete(id),
    interval: 5000,
    idleLimit: 15000,
    onPause: () => paused++,
  });
  return {
    poller,
    timers,
    setNow: (v) => (now = v),
    hide: () => (visible = false),
    show: () => (visible = true),
    get paused() {
      return paused;
    },
    async tick() {
      const [key, t] = timers.entries().next().value || [];
      if (!t) return;
      timers.delete(key);
      await t.fn();
    },
  };
}
test('hidden surface and explicit stop do not run background requests', async () => {
  let count = 0;
  const h = harness(async () => count++);
  h.hide();
  h.poller.start();
  assert.equal(h.timers.size, 0);
  h.show();
  h.poller.start();
  h.poller.stop();
  await h.tick();
  assert.equal(count, 0);
});
test('polling pauses after inactivity rather than running forever', async () => {
  let count = 0;
  const h = harness(async () => count++);
  h.poller.start();
  h.setNow(16000);
  await h.tick();
  assert.equal(count, 0);
  assert.equal(h.paused, 1);
  assert.equal(h.timers.size, 0);
});
test('an in-flight response cannot resurrect a stopped poll loop', async () => {
  let resolve;
  const h = harness(() => new Promise((r) => (resolve = r)));
  h.poller.start();
  const pending = h.tick();
  h.poller.stop();
  resolve();
  await pending;
  assert.equal(h.timers.size, 0);
});
test('network failures back off before retrying and success resets delay', async () => {
  let fail = true;
  const h = harness(async () => {
    if (fail) throw Error('offline');
  });
  h.poller.start();
  await h.tick();
  assert.equal([...h.timers.values()][0].ms, 10000);
  fail = false;
  await h.tick();
  assert.equal([...h.timers.values()][0].ms, 5000);
});
