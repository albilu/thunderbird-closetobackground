import {test} from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import {readFileSync} from "node:fs";

function fixture() {
  const observers = new Map(), queued = [];
  let hooks;
  const support = {registerWindowListener(_id, value) { hooks = value; }, unregisterWindowListener() { hooks = null; }};
  const Services = {appinfo: {OS: "Linux"}, obs: {
    addObserver(observer, topic) { observers.set(topic, observer); },
    removeObserver(_observer, topic) { observers.delete(topic); }, notifyObservers() {},
  }, tm: {dispatchToMainThread(fn) { queued.push(fn); }}, wm: {getMostRecentWindow() { return win; }}};
  const context = vm.createContext({Services, Ci: {nsIBaseWindow: 1}, console: {error() {}}, ChromeUtils: {
    importESModule(path) { return path.includes("ExtensionCommon") ? {ExtensionCommon: {ExtensionAPI: class {}}} : {ExtensionSupport: support}; },
  }});
  vm.runInContext(readFileSync(new URL("../extension/experiments/backgroundWindows/api.js", import.meta.url), "utf8"), context);
  const instance = new context.backgroundWindows(); instance.extension = {id: "test"};
  const api = instance.getAPI({callOnClose() {}}).backgroundWindows;
  const makeWindow = (type = "mail:3pane") => {
    const base = {visibility: true};
    const handlers = new Map();
    return {base, handlers, windowState: 1, STATE_NORMAL: 1, STATE_MINIMIZED: 2, STATE_MAXIMIZED: 3, STATE_FULLSCREEN: 4,
      closed: false, focused: false, document: {documentElement: {getAttribute: () => type}},
      setTimeout() { return 1; }, clearTimeout() {},
      docShell: {treeOwner: {QueryInterface: () => base}},
      addEventListener(name, fn) { handlers.set(name, fn); }, removeEventListener(name) { handlers.delete(name); },
      restore() { this.windowState = 1; }, maximize() { this.windowState = 3; }, focus() { this.focused = true; },
      minimize() { this.windowState = 2; },
      close() { this.closed = true; },
      goQuitApplication() {},
    };
  };
  const win = makeWindow(); hooks.onLoadWindow(win);
  const close = (target = win) => {
    const event = {target, prevented: false, preventDefault() { this.prevented = true; }, stopImmediatePropagation() {}};
    win.handlers.get("close")(event); return event;
  };
  return {api, instance, win, close, hooks, makeWindow, observers, queued};
}

test("only intercepts main-window close when explicitly enabled and restores on disable", async () => {
  const f = fixture();
  assert.equal(f.close().prevented, false);
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  assert.equal(f.close({}).prevented, false);
  assert.equal(f.close().prevented, true);
  assert.equal(f.win.base.visibility, false);
  await f.api.configure({enabled: false, closeToTray: true, minimizeToTray: true});
  assert.equal(f.win.base.visibility, true);
  const compose = f.makeWindow("msgcompose"); f.hooks.onLoadWindow(compose);
  assert.equal(compose.handlers.size, 0);
});

test("restores maximized windows and all independently hidden main windows", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  const second = f.makeWindow(); f.hooks.onLoadWindow(second);
  f.win.windowState = 3;
  await f.api.hideAll();
  assert.equal(second.base.visibility, false);
  await f.api.restoreAll();
  assert.equal(f.win.windowState, 3);
  assert.equal(f.win.base.visibility, true);
  assert.equal(second.base.visibility, true);
});

test("minimize is optional and failed hide leaves close behavior untouched", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: false});
  f.win.windowState = 2; f.win.handlers.get("sizemodechange")();
  assert.equal(f.win.base.visibility, true);
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.win.handlers.get("sizemodechange")();
  assert.equal(f.win.base.visibility, false);
  await f.api.restoreAll();
  Object.defineProperty(f.win.base, "visibility", {get() { return true; }, set() { throw Error("Unavailable"); }});
  assert.equal(f.close().prevented, false);
});

test("normal Quit bypasses interception, and canceled Quit re-enables it", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.observers.get("quit-application-requested").observe(null, "quit-application-requested");
  assert.equal(f.close().prevented, false);
  f.queued.forEach(fn => fn());
  assert.equal(f.close().prevented, true);
});

test("Thunderbird titlebar close hides the window without a native close event", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.win.close();
  assert.equal(f.win.closed, false);
  assert.equal(f.win.base.visibility, false);
  await f.api.restoreAll();
  assert.equal(f.win.base.visibility, true);
  await f.api.configure({enabled: true, closeToTray: false, minimizeToTray: true});
  f.win.close();
  assert.equal(f.win.closed, true);
});

test("direct close falls through on hide failure, normal Quit, and add-on teardown", async () => {
  for (const scenario of ["failure", "quit", "unload", "disabled"]) {
    const f = fixture();
    await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
    if (scenario === "failure") {
      Object.defineProperty(f.win.base, "visibility", {set() { throw Error("Widget unavailable"); }});
    } else if (scenario === "quit") {
      f.observers.get("quit-application-requested").observe(null, "quit-application-requested");
    } else if (scenario === "unload") {
      const original = f.instance.windows.get(f.win).originalClose;
      f.instance.onShutdown(false);
      assert.equal(f.win.close, original);
    } else {
      await f.api.configure({enabled: false, closeToTray: true, minimizeToTray: true});
    }
    f.win.close();
    assert.equal(f.win.closed, true, scenario);
  }
});

test("cancelled Quit resumes titlebar close-to-tray without affecting compose windows", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.observers.get("quit-application-requested").observe(null, "quit-application-requested");
  f.queued.forEach(fn => fn());
  f.win.close();
  assert.equal(f.win.closed, false);
  assert.equal(f.win.base.visibility, false);
  const compose = f.makeWindow("msgcompose");
  const original = compose.close;
  f.hooks.onLoadWindow(compose);
  assert.equal(compose.close, original);
  compose.close();
  assert.equal(compose.closed, true);
});

test("unloading restores windows and removes every listener", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  await f.api.hideAll();
  f.instance.onShutdown(false);
  assert.equal(f.win.base.visibility, true);
  assert.equal(f.win.handlers.size, 0);
  assert.equal(f.observers.size, 0);
});

test("stale minimized events during native restore do not hide the window again", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.win.windowState = 2;
  f.win.handlers.get("sizemodechange")();
  await f.api.restoreAll();
  f.win.windowState = 2;
  f.win.handlers.get("sizemodechange")();
  assert.equal(f.win.base.visibility, true);
  f.win.windowState = 1;
  f.win.handlers.get("sizemodechange")();
  f.win.windowState = 2;
  f.win.handlers.get("sizemodechange")();
  assert.equal(f.win.base.visibility, false);
});

test("Thunderbird minimize works on Wayland without a compositor size event", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.win.minimize();
  assert.equal(f.win.base.visibility, false);
  assert.equal(f.win.windowState, 1);
  await f.api.configure({enabled: false, closeToTray: true, minimizeToTray: true});
  f.win.minimize();
  assert.equal(f.win.base.visibility, true);
  assert.equal(f.win.windowState, 2);
  f.instance.onShutdown(false);
  f.win.windowState = 1;
  f.win.minimize();
  assert.equal(f.win.windowState, 2);
});

test("does not trust AppWindow's always-true visibility getter", async () => {
  const f = fixture();
  let nativeVisible = true;
  Object.defineProperty(f.win.base, "visibility", {get() { return true; }, set(value) { nativeVisible = value; }});
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  assert.equal(f.close().prevented, true);
  assert.equal(nativeVisible, false);
  await f.api.restoreAll();
  assert.equal(nativeVisible, true);
});

test("a failed multi-window hide restores windows already hidden", async () => {
  const f = fixture();
  const second = f.makeWindow();
  f.hooks.onLoadWindow(second);
  Object.defineProperty(second.base, "visibility", {set() { throw Error("Widget unavailable"); }});
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  await assert.rejects(f.api.hideAll(), /Widget unavailable/);
  assert.equal(f.win.base.visibility, true);
});

test("launcher focus restores hidden mail windows and preserves maximized state", async () => {
  const f = fixture();
  const second = f.makeWindow();
  f.hooks.onLoadWindow(second);
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  f.win.windowState = f.win.STATE_MAXIMIZED;
  await f.api.hideAll();
  f.win.focus();
  assert.equal(f.win.base.visibility, true);
  assert.equal(second.base.visibility, true);
  assert.equal(f.win.windowState, f.win.STATE_MAXIMIZED);
  assert.equal(f.win.focused, true);
  assert.equal(f.instance.windows.get(f.win).hidden, false);
  f.win.focus();
  assert.equal(f.win.base.visibility, true, "A repeated focus must not hide a visible window");
});

test("focus keeps its normal receiver/arguments/result and is restored on unload", async () => {
  const f = fixture();
  const win = f.makeWindow();
  const calls = [];
  const original = win.focus = function (...args) { calls.push({receiver: this, args}); return "focused"; };
  f.hooks.onLoadWindow(win);
  assert.equal(win.focus({preventScroll: true}), "focused");
  assert.equal(calls[0].receiver, win);
  assert.deepEqual(calls[0].args, [{preventScroll: true}]);
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  await f.api.hideAll();
  assert.equal(win.focus(), "focused");
  f.instance.onShutdown(false);
  assert.equal(win.focus, original);
  assert.equal(win.base.visibility, true);
});

test("focus does not interrupt quitting or change compose-window behavior", async () => {
  const f = fixture();
  await f.api.configure({enabled: true, closeToTray: true, minimizeToTray: true});
  await f.api.hideAll();
  f.observers.get("quit-application-requested").observe(null, "quit-application-requested");
  f.win.focus();
  assert.equal(f.win.base.visibility, false);
  f.queued.forEach(fn => fn());
  f.win.focus();
  assert.equal(f.win.base.visibility, true);
  const compose = f.makeWindow("msgcompose");
  const original = compose.focus;
  f.hooks.onLoadWindow(compose);
  assert.equal(compose.focus, original);
});
