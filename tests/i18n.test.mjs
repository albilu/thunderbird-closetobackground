import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {createI18n, localizeDocument, trayStrings, HELPER_MESSAGE_KEYS} from "../extension/lib/i18n.mjs";
import {catalogs, catalogAPI} from "./i18n-support.mjs";

test("French covers the default catalog, placeholders, manifest and options", () => {
  assert.deepEqual(Object.keys(catalogs.fr).sort(), Object.keys(catalogs.en).sort());
  for (const [key, entry] of Object.entries(catalogs.en)) {
    const translated = catalogs.fr[key];
    assert.ok(entry.message.trim() && translated.message.trim(), key);
    const placeholders = value => Object.fromEntries(Object.entries(value.placeholders ?? {})
      .map(([name, definition]) => [name, definition.content]));
    assert.deepEqual(placeholders(translated), placeholders(entry), key);
    for (const value of [entry, translated]) {
      const names = [...value.message.matchAll(/\$(\w+)\$/g)].map(match => match[1].toLowerCase()).sort();
      assert.deepEqual(names, Object.keys(value.placeholders ?? {}).sort(), key);
    }
  }
  const manifest = JSON.parse(readFileSync(new URL("../extension/manifest.json", import.meta.url)));
  assert.equal(manifest.default_locale, "en");
  for (const value of [manifest.name, manifest.description]) {
    const key = /^__MSG_(\w+)__$/.exec(value)?.[1];
    assert.ok(catalogs.en[key], value);
  }
  const html = readFileSync(new URL("../extension/options/options.html", import.meta.url), "utf8");
  for (const [, key] of html.matchAll(/data-i18n(?:-title|-aria-label)?="(\w+)"/g)) {
    assert.ok(catalogs.en[key], key);
  }
  for (const key of HELPER_MESSAGE_KEYS) assert.ok(catalogs.en[key], key);
});

test("notifications and tray titles use French plurals and localized numbers", () => {
  const fr = createI18n(catalogAPI("fr")), en = createI18n(catalogAPI("en"));
  assert.equal(fr.plural("notificationNewMessage", 1), "1 nouveau message. Cliquez pour afficher Thunderbird.");
  assert.equal(fr.plural("notificationNewMessage", 2), "2 nouveaux messages. Cliquez pour afficher Thunderbird.");
  assert.equal(fr.plural("trayUnread", 0), "Thunderbird — 0 message non lu");
  assert.equal(fr.plural("trayUnreadPartial", 2), "Thunderbird — 2 messages non lus (décompte partiel)");
  assert.equal(fr.plural("trayUnread", 1234), "Thunderbird — 1\u202f234 messages non lus");
  assert.equal(en.plural("notificationNewMessage", 0), "0 new messages. Click to show Thunderbird.");
  assert.equal(en.plural("notificationNewMessage", 1), "1 new message. Click to show Thunderbird.");
  assert.equal(en.plural("notificationNewMessage", 2), "2 new messages. Click to show Thunderbird.");
  const settings = {enabled: true, showUnread: true};
  const strings = trayStrings(fr, settings, 2, true);
  assert.equal(strings.title, "Thunderbird — 2 messages non lus (décompte partiel)");
  assert.equal(strings.show, "Afficher Thunderbird");
  assert.equal(strings.quit, "Quitter Thunderbird");
  assert.equal(trayStrings(fr, {...settings, enabled: false}, 2, true).title, "Thunderbird — mode arrière-plan désactivé");
  assert.equal(trayStrings(fr, {...settings, showUnread: false}, 2, true).title, "Thunderbird");
});

test("document localization sets its language, visible text and accessible labels as text", () => {
  const element = attributes => ({
    dataset: {i18n: attributes["data-i18n"]},
    attributes,
    getAttribute(name) { return this.attributes[name]; },
    setAttribute(name, value) { this.attributes[name] = value; },
    set innerHTML(_value) { assert.fail("Translations must not be parsed as HTML"); },
  });
  const title = element({"data-i18n": "optionsTitle"});
  const form = element({"data-i18n-aria-label": "settingsLabel"});
  const unread = element({"data-i18n-title": "unreadMessages"});
  const document = {
    documentElement: {},
    querySelectorAll(selector) {
      return [title, form, unread].filter(item => Object.hasOwn(item.attributes, selector.slice(1, -1)));
    },
  };
  localizeDocument(document, createI18n(catalogAPI("fr")));
  assert.equal(document.documentElement.lang, "fr");
  assert.equal(title.textContent, "Close to Background · Paramètres");
  assert.equal(form.attributes["aria-label"], "Paramètres du mode arrière-plan");
  assert.equal(unread.attributes.title, "Messages non lus");
});
