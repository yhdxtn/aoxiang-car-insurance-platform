/** A single bounded scheduler. No overlapping polls, no background-tab traffic. */
export function createVisiblePoller({
  run,
  isVisible = () => !document.hidden,
  now = () => Date.now(),
  setTimer = setTimeout,
  clearTimer = clearTimeout,
  interval = 5000,
  idleLimit = 900000,
  onPause = () => {},
}) {
  let timer = null,
    stopped = true,
    running = false,
    lastActivity = now(),
    errors = 0,
    generation = 0;
  function clear() {
    if (timer !== null) {
      clearTimer(timer);
      timer = null;
    }
  }
  async function tick(g) {
    if (stopped || g !== generation || !isVisible()) return;
    if (now() - lastActivity > idleLimit) {
      stopped = true;
      onPause();
      return;
    }
    if (running) return;
    running = true;
    try {
      await run();
      errors = 0;
    } catch {
      errors = Math.min(errors + 1, 4);
    } finally {
      running = false;
      if (!stopped && g === generation && isVisible())
        timer = setTimer(() => tick(g), Math.min(interval * 2 ** errors, 60000));
    }
  }
  return {
    start() {
      clear();
      stopped = false;
      const g = ++generation;
      if (isVisible()) timer = setTimer(() => tick(g), interval);
    },
    stop() {
      stopped = true;
      generation++;
      clear();
    },
    activity() {
      lastActivity = now();
    },
    get active() {
      return !stopped;
    },
  };
}
