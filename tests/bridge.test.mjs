import {test} from "node:test";
import assert from "node:assert/strict";
import {NativeBridge} from "../extension/lib/native-bridge.mjs";

function fixture() {
  const event = () => ({listeners: [], addListener(fn) { this.listeners.push(fn); }, emit(value) { this.listeners.forEach(fn => fn(value)); }});
  const statuses = [], actions = [], ports = [], timeouts = new Map(), intervals = new Map();
  let id = 0;
  const timers = {
    setTimeout(fn, delay) { const key = ++id; timeouts.set(key, {fn, delay}); return key; },
    clearTimeout(key) { timeouts.delete(key); },
    setInterval(fn) { const key = ++id; intervals.set(key, fn); return key; },
    clearInterval(key) { intervals.delete(key); },
  };
  const runtime = {connectNative() {
    const port = {onMessage: event(), onDisconnect: event(), sent: [], disconnected: false,
      postMessage(message) { this.sent.push(message); },
      disconnect() { this.disconnected = true; this.onDisconnect.emit(); }};
    ports.push(port); return port;
  }};
  const bridge = new NativeBridge(runtime, {onStatus: status => statuses.push(status), onAction: action => actions.push(action)}, timers);
  return {bridge, statuses, actions, ports, timeouts, intervals};
}

test("does not report a working tray until a compatible helper confirms it", () => {
  const f = fixture();
  f.bridge.update({enabled: true, unread: 4});
  f.bridge.start();
  assert.equal(f.statuses.at(-1).available, false);
  assert.equal(f.ports[0].sent[0].unread, 4);
  f.ports[0].onMessage.emit({protocol: 1, type: "status", available: true, message: "Ready"});
  assert.equal(f.statuses.at(-1).available, true);
  f.ports[0].onMessage.emit({protocol: 2, type: "status", available: true});
  assert.equal(f.statuses.at(-1).available, false);
  assert.equal(f.ports[0].disconnected, true);
  assert.equal(f.timeouts.size, 1);
});

test("disconnect restores fail-safe state and stale ports cannot re-enable hiding", () => {
  const f = fixture(); f.bridge.start();
  const old = f.ports[0];
  old.error = {message: "No such native application"};
  old.onDisconnect.emit();
  assert.equal(f.statuses.at(-1).available, false);
  assert.match(f.statuses.at(-1).message, /No such/);
  f.bridge.retry();
  old.onMessage.emit({protocol: 1, type: "status", available: true});
  assert.equal(f.statuses.at(-1).available, false);
  assert.equal(f.ports.length, 2);
});

test("validates actions and closes an unresponsive helper", () => {
  const f = fixture(); f.bridge.start();
  f.ports[0].onMessage.emit({protocol: 1, type: "action", action: "execute"});
  f.ports[0].onMessage.emit({protocol: 1, type: "action", action: "restore"});
  assert.deepEqual(f.actions, ["restore"]);
  f.bridge.lastSeen = Date.now() - 31_000;
  [...f.intervals.values()][0]();
  assert.equal(f.bridge.port, null);
  assert.match(f.statuses.at(-1).message, /stopped responding/);
  f.bridge.stop();
  assert.equal(f.timeouts.size, 0);
  assert.equal(f.intervals.size, 0);
});
