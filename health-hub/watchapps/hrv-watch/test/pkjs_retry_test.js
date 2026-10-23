const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function harness(queue) {
  const values = { pebblefit_hrv_token: 'test-token', pebblefit_hrv_queue: JSON.stringify(queue) };
  const listeners = {};
  const timers = [];
  const sent = [];
  let current;
  const context = {
    localStorage: {
      getItem: key => values[key] || null,
      setItem: (key, value) => { values[key] = String(value); },
      removeItem: key => { delete values[key]; }
    },
    setTimeout: fn => { timers.push(fn); return timers.length; },
    clearTimeout: id => { timers[id - 1] = null; },
    Pebble: {
      addEventListener: (name, fn) => { listeners[name] = fn; },
      sendAppMessage: msg => { sent.push(msg); },
      openURL: () => {}
    },
    XMLHttpRequest: function () {
      current = this;
      this.open = () => {};
      this.setRequestHeader = () => {};
      this.send = () => {};
    },
    decodeURIComponent,
    JSON,
    Math
  };
  vm.runInNewContext(fs.readFileSync(__dirname + '/../src/pkjs/index.js', 'utf8'), context, { filename: 'index.js' });
  return { values, listeners, timers, sent, get request() { return current; } };
}

const sample = { ts: 123, ppi: [800], offsets_ms: [0] };
const sample2 = { ts: 124, ppi: [810], offsets_ms: [0] };
const h = harness([sample]);
h.listeners.ready();
assert(h.request, 'ready must start the queued upload');
h.request.onerror();
assert.deepStrictEqual(JSON.parse(h.values.pebblefit_hrv_queue), [sample], 'transient failure retains the queue');
assert.strictEqual(h.timers.filter(Boolean).length, 1, 'transient failure schedules one retry');
h.timers.find(Boolean)();
assert(h.request, 'retry timer starts another request');
h.request.status = 201;
h.request.onload();
assert.deepStrictEqual(JSON.parse(h.values.pebblefit_hrv_queue), [], 'acknowledged upload removes only the sent item');

const drain = harness([sample, sample2]);
drain.listeners.ready();
drain.request.status = 201;
drain.request.onload();
assert.deepStrictEqual(JSON.parse(drain.values.pebblefit_hrv_queue), [sample2], 'success removes only the acknowledged head');
drain.request.status = 201;
drain.request.onload();
assert.deepStrictEqual(JSON.parse(drain.values.pebblefit_hrv_queue), [], 'a queued second item drains after its own success');

const server = harness([sample]);
server.listeners.ready();
server.request.status = 500;
server.request.onload();
assert.strictEqual(server.timers.filter(Boolean).length, 1, 'server failure retries');

const timeout = harness([sample]);
timeout.listeners.ready();
timeout.request.ontimeout();
assert.strictEqual(timeout.timers.filter(Boolean).length, 1, 'timeout retries');

const permanent = harness([sample]);
permanent.listeners.ready();
permanent.request.status = 400;
permanent.request.onload();
assert.strictEqual(permanent.timers.filter(Boolean).length, 0, 'permanent client failure does not retry');

const auth = harness([sample]);
auth.listeners.ready();
auth.request.status = 401;
auth.request.onload();
assert.strictEqual(auth.timers.filter(Boolean).length, 0, 'authorization failure pauses instead of retrying blindly');

function bytes(width, value) { const a = []; for (let i = 0; i < 36; i++) for (let j = 0; j < width; j++) a.push((value >> (8 * j)) & 255); return a; }
const windowsPayload = {ts: 200, ppi: [32, 3], offsets: [0, 0, 0, 0], collector_version: 153, motion_window_version: 1, motion_window_ms: 5000,
  motion_window_totals: bytes(4, 7), motion_window_samples: bytes(2, 2), motion_window_transitions: bytes(2, 1), motion_window_peaks: bytes(4, 9)};
const windows = harness([]);
windows.listeners.appmessage({payload: windowsPayload});
let queued = JSON.parse(windows.values.pebblefit_hrv_queue);
assert.strictEqual(queued[0].motion_windows.windows.length, 36, 'valid window arrays decode into 36 windows');
assert.deepStrictEqual(queued[0].motion_windows.windows[0], {start_ms: 0, samples: 2, transitions: 1, total_delta: 7, max_delta: 9});

const malformed = harness([]);
malformed.listeners.appmessage({payload: Object.assign({}, windowsPayload, {motion_window_totals: bytes(4, 7).slice(0, 140)})});
queued = JSON.parse(malformed.values.pebblefit_hrv_queue);
assert(!queued[0].motion_windows, 'truncated window array is omitted');

const malformedByte = harness([]);
const corruptedTotals = bytes(4, 7); corruptedTotals[10] = '7';
malformedByte.listeners.appmessage({payload: Object.assign({}, windowsPayload, {motion_window_totals: corruptedTotals})});
queued = JSON.parse(malformedByte.values.pebblefit_hrv_queue);
assert(!queued[0].motion_windows, 'non-byte window data is omitted');

const legacy = harness([]);
legacy.listeners.appmessage({payload: Object.assign({}, windowsPayload, {collector_version: 152})});
queued = JSON.parse(legacy.values.pebblefit_hrv_queue);
assert(!queued[0].motion_windows, 'legacy collector payload remains without window data');

const badVersion = harness([]);
badVersion.listeners.appmessage({payload: Object.assign({}, windowsPayload, {motion_window_version: 2})});
queued = JSON.parse(badVersion.values.pebblefit_hrv_queue);
assert(!queued[0].motion_windows, 'unknown window layout remains without window data');

console.log('hrv pkjs retry tests passed');
