#!/usr/bin/python3
"""Integration test against a real isolated session bus and the real helper process."""

import os
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native"))
from gi.repository import Gio, GLib
from protocol import Writer, read_message
from tray import SNI, MENU, WATCHER, ITEM_PATH, MENU_PATH, WATCHER_PATH
from icons import argb_pixmaps

WATCHER_XML = """<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
<signal name="StatusNotifierHostRegistered"/>
<signal name="StatusNotifierHostUnregistered"/>
</interface></node>"""


class TrayIntegration(unittest.TestCase):
    def setUp(self):
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, daemon=True)
        self.thread.start()
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.messages = queue.Queue()
        self.registrations = queue.Queue()
        self.owner_id = None
        self.node = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        self.object_id = self.bus.register_object(WATCHER_PATH, self.node.interfaces[0], self.register,
                                                  self.get_property, None)
        self.host = subprocess.Popen([sys.executable, str(ROOT / "native/host.py")],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.writer = Writer(self.host.stdin)

        def read():
            while (message := read_message(self.host.stdout)) is not None:
                self.messages.put(message)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def tearDown(self):
        self.host.stdin.close()
        try:
            self.host.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.host.kill()
            self.host.wait()
        errors = self.host.stderr.read().decode()
        self.host.stderr.close()
        self.host.stdout.close()
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
        self.bus.unregister_object(self.object_id)
        self.loop.quit()
        self.thread.join(timeout=2)
        self.assertEqual(errors, "", f"Helper wrote errors: {errors}")

    def register(self, _connection, sender, _path, _interface, _method, parameters, invocation):
        self.registrations.put((sender, parameters.unpack()[0]))
        invocation.return_value(None)

    def get_property(self, _connection, _sender, _path, _interface, name):
        return {"IsStatusNotifierHostRegistered": GLib.Variant("b", True),
                "RegisteredStatusNotifierItems": GLib.Variant("as", []),
                "ProtocolVersion": GLib.Variant("i", 0)}[name]

    def wait_message(self, kind, **matching):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if message.get("type") == kind and all(message.get(key) == value for key, value in matching.items()):
                return message
        self.fail(f"Did not receive {kind}: {matching}")

    def state(self, **patch):
        self.writer.send({"type": "state", "enabled": True, "showUnread": True, "unread": 0,
                          "incomplete": False, **patch})
        self.writer.send({"type": "ping"})
        self.wait_message("pong")  # acts as a barrier for state updates

    def call(self, interface, method, parameters=None, path=ITEM_PATH):
        return self.bus.call_sync(self.destination, path, interface, method, parameters, None,
                                  Gio.DBusCallFlags.NONE, 3000, None)

    def property(self, name):
        return self.call("org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (SNI, name))).unpack()[0]

    def own_watcher(self):
        self.owner_id = Gio.bus_own_name_on_connection(self.bus, WATCHER, Gio.BusNameOwnerFlags.NONE, None, None)
        self.destination, service = self.registrations.get(timeout=8)
        self.assertTrue(service.startswith('org.kde.StatusNotifierItem-'))
        self.wait_message("status", available=True)

    def test_tray_lifecycle_badge_actions_and_recovery(self):
        self.writer.send({"type": "hello", "enabled": True, "showUnread": True, "unread": 0, "incomplete": False})
        self.wait_message("status", available=False)
        self.own_watcher()
        self.assertEqual(self.property("Status"), "Active")
        before = self.property("IconPixmap")
        self.assertEqual(before, [(w, h, list(data)) for w, h, data in argb_pixmaps(0)])
        self.state(unread=123)
        self.assertIn("123 unread", self.property("Title"))
        self.assertNotEqual(before, self.property("IconPixmap"))
        self.call(SNI, "Activate", GLib.Variant("(ii)", (0, 0)))
        self.wait_message("action", action="restore")
        self.call(SNI, "SecondaryActivate", GLib.Variant("(ii)", (0, 0)))
        self.wait_message("action", action="restore")
        layout = self.call(MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), MENU_PATH).unpack()
        self.assertEqual(len(layout[1][2]), 7)
        for item, action in ((1, "restore"), (2, "hide"), (4, "toggle"), (5, "settings"), (7, "quit")):
            self.call(MENU, "Event", GLib.Variant("(isvu)", (item, "clicked", GLib.Variant("i", 0), 0)), MENU_PATH)
            self.wait_message("action", action=action)
        self.state(enabled=False, unread=5)
        self.assertIn("mode off", self.property("Title"))
        hidden = self.call(MENU, "GetProperty", GLib.Variant("(is)", (2, "enabled")), MENU_PATH).unpack()[0]
        self.assertFalse(hidden)
        Gio.bus_unown_name(self.owner_id)
        self.owner_id = None
        self.wait_message("status", available=False)
        self.own_watcher()

    def test_french_menu_tooltip_and_legacy_english_fallback(self):
        self.writer.send({"type": "hello", "enabled": True, "showUnread": True, "unread": 2, "incomplete": False})
        status = self.wait_message("status", available=False)
        self.assertIn(status["messageKey"], ("helperWaiting", "helperTrayMissing"))
        self.own_watcher()
        self.assertEqual(self.property("Title"), "Thunderbird — 2 unread")
        before = self.call(MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), MENU_PATH).unpack()[0]
        catalog = json.loads((ROOT / "extension/_locales/fr/messages.json").read_text())
        keys = {"show": "actionRestore", "hide": "actionHide", "enable": "settingEnabled",
                "settings": "traySettings", "quit": "actionQuit"}
        strings = {key: catalog[message]["message"] for key, message in keys.items()}
        strings["title"] = catalog["trayUnreadOther"]["message"].replace("$COUNT$", "2")
        # Changing only UI strings must refresh the tray title and menu layout.
        self.state(unread=2, strings=strings)
        self.assertEqual(self.property("Title"), "Thunderbird — 2 messages non lus")
        tooltip = self.property("ToolTip")
        self.assertEqual(tooltip[2:], (strings["title"], "Afficher Thunderbird"))
        layout = self.call(MENU, "GetLayout", GLib.Variant("(iias)", (0, -1, [])), MENU_PATH).unpack()
        self.assertGreater(layout[0], before)
        labels = {item: properties["label"] for item, properties, _children in layout[1][2] if "label" in properties}
        self.assertEqual(labels, {1: "Afficher Thunderbird", 2: "Masquer dans la zone de notification",
                                  4: "Activer Close to Background", 5: "Paramètres…", 7: "Quitter Thunderbird"})
        self.call(MENU, "Event", GLib.Variant("(isvu)", (1, "clicked", GLib.Variant("i", 0), 0)), MENU_PATH)
        self.wait_message("action", action="restore")
        self.state(unread=2)
        self.assertEqual(self.property("Title"), "Thunderbird — 2 unread")
        label = self.call(MENU, "GetProperty", GLib.Variant("(is)", (1, "label")), MENU_PATH).unpack()[0]
        self.assertEqual(label, "Show Thunderbird")


if __name__ == "__main__":
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise SystemExit("Run with: dbus-run-session -- python3 tests/dbus_integration.py")
    unittest.main()
