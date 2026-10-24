// Thunderbird selects the catalog; its locale also controls plurals and numbers
// when the requested language falls back to English.
export function createI18n(api) {
  const locale = api.getMessage("locale");
  const numbers = new Intl.NumberFormat(locale);
  const plurals = new Intl.PluralRules(locale);
  const message = (key, substitutions) => api.getMessage(key, substitutions);
  return {
    locale,
    message,
    number: count => numbers.format(count),
    plural: (key, count) => message(`${key}${plurals.select(count) === "one" ? "One" : "Other"}`, numbers.format(count)),
  };
}

export function localizeDocument(document, i18n) {
  document.documentElement.lang = i18n.locale;
  for (const element of document.querySelectorAll("[data-i18n]")) {
    element.textContent = i18n.message(element.dataset.i18n);
  }
  for (const attribute of ["title", "aria-label"]) {
    for (const element of document.querySelectorAll(`[data-i18n-${attribute}]`)) {
      element.setAttribute(attribute, i18n.message(element.getAttribute(`data-i18n-${attribute}`)));
    }
  }
}

export function trayStrings(i18n, settings, unread, incomplete) {
  return {
    title: !settings.enabled ? i18n.message("trayDisabled") : !settings.showUnread ? "Thunderbird" :
      i18n.plural(incomplete ? "trayUnreadPartial" : "trayUnread", unread),
    show: i18n.message("actionRestore"),
    hide: i18n.message("actionHide"),
    enable: i18n.message("settingEnabled"),
    settings: i18n.message("traySettings"),
    quit: i18n.message("actionQuit"),
  };
}

// Only the helper's documented status/error keys may select catalog messages.
export const HELPER_MESSAGE_KEYS = new Set([
  "helperDesktopLost", "helperTrayMissing", "helperTrayLost", "helperTrayInactive",
  "helperContactFailed", "helperReady", "helperRegistrationFailed", "helperConnected",
  "helperWaiting", "helperDependencies", "helperSessionBus", "helperProtocolError",
]);
