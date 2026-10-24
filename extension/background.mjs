import {DEFAULT_SETTINGS, normalizeSettings, readUnreadCount, countableFolders,
  RecentMessages, countNewMessages} from "./lib/core.mjs";
import {NativeBridge} from "./lib/native-bridge.mjs";
import {createI18n, trayStrings} from "./lib/i18n.mjs";

const api = messenger;
const i18n = createI18n(api.i18n);
const t = i18n.message;
let settings = {...DEFAULT_SETTINGS, enabled: false};
let tray = {available: false, message: t("statusStarting")};
let unread = 0;
let unreadIncomplete = false;
let mailError = "";
let windowError = "";
let notificationError = "";
let refreshTimer;
let refreshRunning = false;
let refreshAgain = false;
let notificationTimer;
let pendingMessages = 0;
let writeQueue = Promise.resolve();
const recent = new RecentMessages();

function state() {
  return {settings, tray, unread, unreadIncomplete, mailError, windowError, notificationError};
}

function report(error) {
  console.error("Close to Background:", error);
}

function syncTray() {
  bridge.update({enabled: settings.enabled, unread: settings.showUnread && settings.enabled ? unread : 0,
    showUnread: settings.showUnread, incomplete: unreadIncomplete,
    strings: trayStrings(i18n, settings, unread, unreadIncomplete)});
}

async function applyPolicy() {
  try {
    await api.backgroundWindows.configure({enabled: settings.enabled && tray.available,
      closeToTray: settings.closeToTray, minimizeToTray: settings.minimizeToTray});
    windowError = "";
  } catch (error) {
    windowError = t("windowOperationError", error.message);
    report(error);
    await api.backgroundWindows.configure({enabled: false, closeToTray: false, minimizeToTray: false}).catch(report);
  }
  syncTray();
}

const bridge = new NativeBridge(api.runtime, {
  translate: t,
  onStatus: status => { tray = status; void applyPolicy(); },
  onAction: action => { void handleAction(action).catch(report); },
});

async function handleAction(action) {
  switch (action) {
    case "hide":
      if (!settings.enabled || !tray.available || windowError) throw new Error(t("trayRequired"));
      await api.backgroundWindows.hideAll();
      break;
    case "restore": await api.backgroundWindows.restoreAll(); break;
    case "settings":
      await api.backgroundWindows.restoreAll();
      await api.runtime.openOptionsPage();
      break;
    case "toggle": await saveSettings({enabled: !settings.enabled}); break;
    case "quit": await api.backgroundWindows.quit(); break;
  }
}

function saveSettings(patch) {
  const operation = writeQueue.then(async () => {
    for (const [key, value] of Object.entries(patch ?? {})) {
      if (!Object.hasOwn(DEFAULT_SETTINGS, key) || typeof value !== "boolean") throw new Error(t("invalidSetting"));
    }
    const updated = normalizeSettings({...settings, ...patch});
    await api.storage.local.set({settings: updated});
    settings = updated;
    if (!settings.enabled || !settings.notifications) {
      clearTimeout(notificationTimer);
      pendingMessages = 0;
    }
    await applyPolicy();
    return state();
  });
  writeQueue = operation.catch(() => {});
  return operation;
}

function scheduleUnread() {
  refreshAgain = true;
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => void refreshUnread(), 400);
}

async function refreshUnread() {
  if (refreshRunning) { refreshAgain = true; return; }
  refreshRunning = true;
  do {
    refreshAgain = false;
    try {
      const result = await readUnreadCount(api);
      unread = result.count;
      unreadIncomplete = result.incomplete;
      mailError = result.incomplete ? t("unreadPartial") : "";
    } catch (error) {
      unreadIncomplete = true;
      mailError = t("unreadUnavailable");
      report(error);
    }
    syncTray();
  } while (refreshAgain);
  refreshRunning = false;
}

async function notify(count, test = false) {
  if (!settings.enabled || !settings.notifications) return;
  try {
    const iconUrl = await api.backgroundWindows.getApplicationIcon();
    // Loading the installed artwork is asynchronous; respect a disable while it loads.
    if (!settings.enabled || !settings.notifications) return;
    await api.notifications.create("close-to-background-mail", {type: "basic",
      iconUrl,
      title: t(test ? "extensionName" : "notificationTitle"),
      message: test ? t("notificationTest") : i18n.plural("notificationNewMessage", count)});
    notificationError = "";
  } catch (error) {
    notificationError = t("notificationFailed");
    report(error);
    if (test) throw new Error(notificationError);
  }
}

async function newMail(folder, messages) {
  scheduleUnread();
  let handedOff = false;
  try {
    if (!settings.enabled || !settings.notifications) return;
    const allFolders = await api.folders.query({isRoot: false, isVirtual: false});
    if (!countableFolders(allFolders).some(candidate => candidate.id === folder.id)) return;
    handedOff = true;
    const count = await countNewMessages(api, messages, recent,
      () => settings.enabled && settings.notifications);
    if (!count || !settings.enabled || !settings.notifications) return;
    pendingMessages += count;
    clearTimeout(notificationTimer);
    notificationTimer = setTimeout(() => {
      const total = pendingMessages;
      pendingMessages = 0;
      void notify(total);
    }, 800);
  } finally {
    if (!handedOff && messages.id) await api.messages.abortList(messages.id).catch(() => {});
  }
}

const ready = (async () => {
  const stored = await api.storage.local.get("settings");
  settings = normalizeSettings(stored.settings);
  await applyPolicy();
  bridge.start();
  await refreshUnread();
})();
ready.catch(report);

api.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== api.runtime.id || !message || typeof message !== "object") return undefined;
  const actions = {
    getState: () => state(),
    saveSettings: () => saveSettings(message.settings),
    retry: () => { bridge.retry(); return state(); },
    hide: () => handleAction("hide"),
    restore: () => handleAction("restore"),
    testNotification: () => notify(1, true),
  };
  if (!Object.hasOwn(actions, message.type)) return undefined;
  return ready.then(() => actions[message.type]()).then(result => ({ok: true, state: result ?? state()}))
    .catch(error => ({ok: false, error: error.message}));
});
api.notifications.onClicked.addListener(id => {
  if (id === "close-to-background-mail") void handleAction("restore").catch(report);
});
api.messages.onNewMailReceived.addListener((folder, messages) => {
  void ready.then(() => newMail(folder, messages)).catch(report);
}, true);
for (const event of [api.folders.onFolderInfoChanged, api.folders.onCreated, api.folders.onDeleted,
  api.folders.onMoved, api.folders.onCopied, api.folders.onRenamed, api.folders.onUpdated,
  api.accounts.onCreated, api.accounts.onDeleted, api.accounts.onUpdated]) {
  event?.addListener(scheduleUnread);
}
api.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.settings) {
    settings = normalizeSettings(changes.settings.newValue);
    if (!settings.enabled || !settings.notifications) {
      clearTimeout(notificationTimer);
      pendingMessages = 0;
    }
    void applyPolicy();
  }
});
// Covers missed events and folders which only update their counts after syncing.
setInterval(scheduleUnread, 60_000);
