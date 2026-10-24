"""StatusNotifierItem and DBusMenu on the session bus (GNOME/Wayland or X11)."""

from pathlib import Path
import os
from gi.repository import Gio, GLib

from icons import argb_pixmaps
from protocol import ProtocolError, VERSION, tray_strings

SNI = "org.kde.StatusNotifierItem"
MENU = "com.canonical.dbusmenu"
WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_PATH = "/StatusNotifierWatcher"


class Tray:
    def __init__(self, send):
        self.send = send
        self.enabled = True
        self.show_unread = True
        self.unread = 0
        self.incomplete = False
        self.strings = {}
        self.available = False
        self.handshake = False
        self.watcher_owner = None
        self.registering = False
        self.name_ready = False
        self.service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.revision = 1
        self.icon_cache = argb_pixmaps(0)
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        node = Gio.DBusNodeInfo.new_for_xml(Path(__file__).with_name("interfaces.xml").read_text())
        self.objects = [
            self.bus.register_object(ITEM_PATH, node.interfaces[0], self.item_method, self.item_property, None),
            self.bus.register_object(MENU_PATH, node.interfaces[1], self.menu_method, self.menu_property, None),
        ]
        self.owner_id = Gio.bus_own_name_on_connection(self.bus, self.service_name, Gio.BusNameOwnerFlags.NONE,
                                                      self.name_acquired, self.name_lost)
        self.watch_id = Gio.bus_watch_name_on_connection(self.bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
                                                        self.watcher_appeared, self.watcher_vanished)
        self.subscription = self.bus.signal_subscribe(WATCHER, WATCHER, None, WATCHER_PATH, None,
                                                     Gio.DBusSignalFlags.NONE, self.watcher_signal)
        self.retry_timer = GLib.timeout_add_seconds(5, self.retry_registration)

    def status(self, available, message, message_key):
        changed = self.available != available
        self.available = available
        if changed:
            self.revision += 1
            self.bus.emit_signal(None, MENU_PATH, MENU, "LayoutUpdated",
                                 GLib.Variant("(ui)", (self.revision, 0)))
        if self.handshake:
            self.send({"type": "status", "available": available, "message": message, "messageKey": message_key})

    def watcher_appeared(self, _connection, _name, owner):
        self.watcher_owner = owner
        self.registering = False
        self.register()

    def name_acquired(self, _connection, _name):
        self.name_ready = True
        self.register()

    def name_lost(self, _connection, _name):
        self.name_ready = False
        self.status(False, "The tray helper lost its desktop connection.", "helperDesktopLost")

    def watcher_vanished(self, _connection, _name):
        self.watcher_owner = None
        self.registering = False
        self.status(False, "No system tray found. Enable GNOME AppIndicator support.", "helperTrayMissing")

    def watcher_signal(self, _connection, _sender, _path, _interface, signal, _parameters):
        if signal == "StatusNotifierHostUnregistered":
            self.status(False, "The desktop tray is unavailable. Windows have been restored.", "helperTrayLost")
        if signal in ("StatusNotifierHostRegistered", "StatusNotifierHostUnregistered"):
            self.register()

    def retry_registration(self):
        if not self.available:
            self.register()
        return GLib.SOURCE_CONTINUE

    def register(self):
        owner = self.watcher_owner
        if not owner or not self.name_ready or self.registering:
            return
        self.registering = True

        def checked(connection, result):
            if owner != self.watcher_owner:
                return
            try:
                if not connection.call_finish(result).unpack()[0]:
                    self.registering = False
                    self.status(False, "A tray watcher exists, but no desktop tray is active.", "helperTrayInactive")
                    return
                connection.call(owner, WATCHER_PATH, WATCHER, "RegisterStatusNotifierItem",
                                GLib.Variant("(s)", (self.service_name,)), None, Gio.DBusCallFlags.NONE,
                                3000, None, registered)
            except GLib.Error:
                self.registering = False
                self.status(False, "Could not contact the desktop tray. Retrying automatically.", "helperContactFailed")

        def registered(connection, result):
            if owner != self.watcher_owner:
                return
            self.registering = False
            try:
                connection.call_finish(result)
                self.status(True, "Connected to the desktop tray. Thunderbird can run in the background.", "helperReady")
            except GLib.Error:
                self.status(False, "Could not register the tray icon. Retrying automatically.", "helperRegistrationFailed")

        self.bus.call(owner, WATCHER_PATH, "org.freedesktop.DBus.Properties", "Get",
                      GLib.Variant("(ss)", (WATCHER, "IsStatusNotifierHostRegistered")),
                      GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 3000, None, checked)

    def receive(self, message):
        if type(message.get("protocol")) is not int or message["protocol"] != VERSION:
            raise ProtocolError("Incompatible protocol. Reinstall the tray helper and add-on together.")
        kind = message.get("type")
        if kind == "ping":
            self.send({"type": "pong"})
            return
        if kind not in ("hello", "state"):
            raise ProtocolError("Unknown native message type")
        for key in ("enabled", "showUnread", "incomplete"):
            if type(message.get(key)) is not bool:
                raise ProtocolError(f"Invalid {key} setting")
        count = message.get("unread")
        if type(count) is not int or not 0 <= count <= 2**53 - 1:
            raise ProtocolError("Invalid unread count")
        strings = tray_strings(message.get("strings", {}))
        new_state = (message["enabled"], message["showUnread"], count, message["incomplete"], strings)
        old_state = (self.enabled, self.show_unread, self.unread, self.incomplete, self.strings)
        self.enabled, self.show_unread, self.unread, self.incomplete, self.strings = new_state
        if new_state != old_state:
            self.icon_cache = argb_pixmaps(self.badge_count, self.enabled)
            self.revision += 1
            for signal in ("NewIcon", "NewTitle", "NewToolTip"):
                self.bus.emit_signal(None, ITEM_PATH, SNI, signal, None)
            changed = {name: self.item_property(None, None, None, None, name)
                       for name in ("Title", "IconName", "IconPixmap", "ToolTip")}
            self.bus.emit_signal(None, ITEM_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (SNI, changed, [])))
            self.bus.emit_signal(None, MENU_PATH, MENU, "LayoutUpdated",
                                 GLib.Variant("(ui)", (self.revision, 0)))
        if kind == "hello":
            self.handshake = True
            self.status(self.available, "Connected to the desktop tray." if self.available else
                        "Waiting for the desktop tray. Enable GNOME AppIndicator support.",
                        "helperConnected" if self.available else "helperWaiting")

    @property
    def badge_count(self):
        return self.unread if self.enabled and self.show_unread else 0

    @property
    def title(self):
        if "title" in self.strings:
            return self.strings["title"]
        if not self.enabled:
            return "Thunderbird — background mode off"
        if not self.show_unread:
            return "Thunderbird"
        suffix = " (partial count)" if self.incomplete else ""
        return f"Thunderbird — {self.unread} unread{suffix}"

    def action(self, action):
        if self.handshake:
            self.send({"type": "action", "action": action})

    def item_property(self, _connection, _sender, _path, _interface, name):
        properties = {
            "Category": ("s", "Communications"), "Id": ("s", "thunderbird-close-to-background"),
            "Title": ("s", self.title), "Status": ("s", "Active"), "WindowId": ("i", 0),
            "IconName": ("s", "" if self.icon_cache else "thunderbird"), "IconPixmap": ("a(iiay)", self.icon_cache),
            "OverlayIconName": ("s", ""), "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""), "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""), "ItemIsMenu": ("b", False), "Menu": ("o", MENU_PATH),
            "ToolTip": ("(sa(iiay)ss)", ("", [], self.title, self.strings.get("show", "Show Thunderbird"))),
        }
        signature, value = properties[name]
        return GLib.Variant(signature, value)

    def item_method(self, _connection, _sender, _path, _interface, method, _parameters, invocation):
        if method in ("Activate", "SecondaryActivate"):
            self.action("restore")
        # The shell renders ContextMenu through the Menu property; scrolling is a no-op.
        invocation.return_value(None)

    def menu_items(self):
        def props(**values):
            return {key.replace("_", "-"): GLib.Variant("b" if type(value) is bool else
                                                      "i" if type(value) is int else "s", value)
                    for key, value in values.items()}
        return {
            0: props(children_display="submenu"),
            1: props(label=self.strings.get("show", "Show Thunderbird"), enabled=True, visible=True),
            2: props(label=self.strings.get("hide", "Send to tray"), enabled=self.enabled and self.available, visible=True),
            3: props(type="separator"),
            4: props(label=self.strings.get("enable", "Enable Close to Background"), enabled=True, visible=True,
                     toggle_type="checkmark", toggle_state=int(self.enabled)),
            5: props(label=self.strings.get("settings", "Settings…"), enabled=True, visible=True),
            6: props(type="separator"),
            7: props(label=self.strings.get("quit", "Quit Thunderbird"), enabled=True, visible=True),
        }

    def menu_property(self, _connection, _sender, _path, _interface, name):
        signature, value = {"Version": ("u", 3), "TextDirection": ("s", "ltr"),
                            "Status": ("s", "normal"), "IconThemePath": ("as", [])}[name]
        return GLib.Variant(signature, value)

    def menu_event(self, item, event):
        actions = {1: "restore", 2: "hide", 4: "toggle", 5: "settings", 7: "quit"}
        if item not in self.menu_items():
            return False
        if event == "clicked" and item in actions:
            if item != 2 or (self.enabled and self.available):
                self.action(actions[item])
        return True

    def menu_method(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        args = parameters.unpack()
        items = self.menu_items()

        def filtered(item, names):
            return {key: value for key, value in items[item].items() if not names or key in names}

        try:
            if method == "GetLayout":
                parent, depth, names = args
                children = [GLib.Variant("(ia{sv}av)", (item, filtered(item, names), []))
                            for item in items if item != 0] if parent == 0 and depth != 0 else []
                result = GLib.Variant("(u(ia{sv}av))", (self.revision, (parent, filtered(parent, names), children)))
            elif method == "GetGroupProperties":
                ids, names = args
                result = GLib.Variant("(a(ia{sv}))", ([(item, filtered(item, names)) for item in ids if item in items],))
            elif method == "GetProperty":
                result = GLib.Variant("(v)", (items[args[0]][args[1]],))
            elif method == "Event":
                if not self.menu_event(args[0], args[1]):
                    raise KeyError(args[0])
                result = None
            elif method == "EventGroup":
                failed = [item for item, event, _data, _timestamp in args[0] if not self.menu_event(item, event)]
                result = GLib.Variant("(ai)", (failed,))
            elif method == "AboutToShow":
                if args[0] not in items:
                    raise KeyError(args[0])
                result = GLib.Variant("(b)", (False,))
            elif method == "AboutToShowGroup":
                result = GLib.Variant("(aiai)", ([], [item for item in args[0] if item not in items]))
            else:
                raise KeyError(method)
            invocation.return_value(result)
        except (KeyError, ValueError) as error:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", str(error))

    def close(self):
        GLib.source_remove(self.retry_timer)
        Gio.bus_unwatch_name(self.watch_id)
        Gio.bus_unown_name(self.owner_id)
        self.bus.signal_unsubscribe(self.subscription)
        for object_id in self.objects:
            self.bus.unregister_object(object_id)
