export const HOST_NAME = "net.thunderbird.closetobackground";
export const PROTOCOL_VERSION = 1;
export const DEFAULT_SETTINGS = Object.freeze({
  enabled: true,
  closeToTray: true,
  minimizeToTray: true,
  showUnread: true,
  notifications: true,
});

export function normalizeSettings(value = {}) {
  return Object.fromEntries(Object.entries(DEFAULT_SETTINGS).map(([key, fallback]) =>
    [key, typeof value?.[key] === "boolean" ? value[key] : fallback]));
}

const EXCLUDED_USES = new Set(["trash", "junk", "drafts", "sent", "templates", "outbox"]);

export function isCountableFolder(folder) {
  return !folder.isRoot && !folder.isVirtual && !folder.isUnified && !folder.isTag &&
    !(folder.specialUse ?? [folder.type]).some(use => EXCLUDED_USES.has(use));
}

// Ignore children of excluded folders, too; their own specialUse is usually empty.
export function countableFolders(folders) {
  const excluded = folders.filter(folder =>
    (folder.specialUse ?? [folder.type]).some(use => EXCLUDED_USES.has(use)));
  const seen = new Set();
  return folders.filter(folder => {
    if (!isCountableFolder(folder) || seen.has(folder.id)) return false;
    if (excluded.some(parent => parent.accountId === folder.accountId &&
      folder.path?.startsWith(`${parent.path}/`))) return false;
    seen.add(folder.id);
    return true;
  });
}

export async function readUnreadCount(api) {
  const folders = countableFolders(await api.folders.query({isRoot: false, isVirtual: false}));
  let next = 0;
  let count = 0;
  const failures = [];
  await Promise.all(Array.from({length: Math.min(8, folders.length)}, async () => {
    while (next < folders.length) {
      const folder = folders[next++];
      try {
        const info = await api.folders.getFolderInfo(folder.id);
        if (Number.isInteger(info.unreadMessageCount) && info.unreadMessageCount >= 0) {
          count += info.unreadMessageCount;
        } else {
          failures.push(folder.id);
        }
      } catch {
        failures.push(folder.id);
      }
    }
  }));
  return {count, incomplete: failures.length > 0};
}

export class RecentMessages {
  constructor(now = () => Date.now()) {
    this.now = now;
    this.seen = new Map();
  }

  add(message) {
    const now = this.now();
    for (const [key, time] of this.seen) {
      if (now - time > 300_000 || this.seen.size >= 1000) this.seen.delete(key);
      else break;
    }
    const key = message.id;
    if (this.seen.has(key)) return false;
    this.seen.set(key, now);
    return true;
  }
}

export async function countNewMessages(api, firstPage, recent, shouldNotify) {
  let page = firstPage;
  let count = 0;
  try {
    while (page) {
      if (!shouldNotify()) break;
      for (const message of page.messages) {
        if (!message.read && !message.junk && recent.add(message)) count++;
      }
      if (!page.id) return count;
      page = await api.messages.continueList(page.id);
    }
    return count;
  } finally {
    // Thunderbird retains paginated lists until consumed or explicitly aborted.
    if (page?.id) await api.messages.abortList(page.id).catch(() => {});
  }
}
