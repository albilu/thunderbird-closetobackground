import {readFileSync} from "node:fs";

export const catalogs = Object.fromEntries(["en", "fr"].map(locale => [locale,
  JSON.parse(readFileSync(new URL(`../extension/_locales/${locale}/messages.json`, import.meta.url), "utf8"))]));

// Supply the WebExtension catalog API to code running outside Thunderbird.
export function catalogAPI(locale = "en") {
  return {getMessage(key, substitutions = []) {
    const entry = catalogs[locale][key];
    if (!entry) return "";
    const values = Array.isArray(substitutions) ? substitutions : [substitutions];
    return entry.message.replace(/\$(\w+)\$/g, (_match, name) =>
      entry.placeholders[name.toLowerCase()].content.replace(/\$(\d+)/g, (_placeholder, index) => values[index - 1] ?? ""));
  }};
}
