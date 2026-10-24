import {test} from "node:test";
import assert from "node:assert/strict";
import {normalizeSettings, countableFolders, readUnreadCount, RecentMessages, countNewMessages} from "../extension/lib/core.mjs";

const folder = (id, properties = {}) => ({id, accountId: "one", path: `/${id}`, specialUse: [], ...properties});

test("settings reject corrupted values and discard unknown fields", () => {
  assert.deepEqual(normalizeSettings({enabled: false, showUnread: "false", unknown: true}), {
    enabled: false, showUnread: true, minimizeToTray: true, closeToTray: true, notifications: true,
  });
  assert.equal(normalizeSettings(null).enabled, true);
});

test("counts physical mail once, excluding special folders and their descendants", () => {
  const folders = [folder("inbox"), folder("inbox"), folder("saved", {isVirtual: true}),
    folder("tags", {isTag: true}), folder("unified", {isUnified: true}), folder("root", {isRoot: true}),
    ...["junk", "trash", "drafts", "sent", "templates", "outbox"].flatMap(use => [
      folder(use, {specialUse: [use]}), folder(`${use}/child`),
    ]), folder("trash/legitimate", {accountId: "two"}), folder("archive")];
  assert.deepEqual(countableFolders(folders).map(f => f.id), ["inbox", "trash/legitimate", "archive"]);
});

test("unread counts have bounded concurrency and report unavailable folders", async () => {
  let running = 0;
  let maximum = 0;
  const api = {folders: {
    query: async () => Array.from({length: 30}, (_, i) => folder(String(i))),
    getFolderInfo: async id => {
      running++; maximum = Math.max(maximum, running);
      await new Promise(resolve => setImmediate(resolve));
      running--;
      if (id === "2") throw Error("Folder deleted while counting");
      return {unreadMessageCount: id === "3" ? -1 : 2};
    },
  }};
  assert.deepEqual(await readUnreadCount(api), {count: 56, incomplete: true});
  assert.equal(maximum, 8);
});

test("empty accounts give zero instead of an error", async () => {
  assert.deepEqual(await readUnreadCount({folders: {query: async () => []}}), {count: 0, incomplete: false});
});

test("new mail consumes pagination, skips read/junk mail, and deduplicates events", async () => {
  const recent = new RecentMessages();
  const api = {messages: {continueList: async () => ({messages: [{id: 3}, {id: 1}]}),
    abortList: async () => assert.fail("A consumed list must not be aborted")}};
  const page = {id: "next", messages: [{id: 1}, {id: 2, junk: true}, {id: 4, read: true}]};
  assert.equal(await countNewMessages(api, page, recent, () => true), 2);
  assert.equal(await countNewMessages(api, page, recent, () => true), 0);
});

test("switching notifications off during pagination frees the outstanding list", async () => {
  let enabled = true;
  const aborted = [];
  const api = {messages: {
    continueList: async () => { enabled = false; return {id: "second", messages: [{id: 2}]}; },
    abortList: async id => aborted.push(id),
  }};
  assert.equal(await countNewMessages(api, {id: "first", messages: [{id: 1}]}, new RecentMessages(), () => enabled), 1);
  assert.deepEqual(aborted, ["second"]);
});

test("notification deduplication is bounded and expires", () => {
  let now = 0;
  const recent = new RecentMessages(() => now);
  assert.equal(recent.add({id: 1}), true);
  assert.equal(recent.add({id: 1}), false);
  now = 300_001;
  assert.equal(recent.add({id: 1}), true);
  for (let id = 0; id < 1100; id++) recent.add({id});
  assert.ok(recent.seen.size <= 1000);
});
