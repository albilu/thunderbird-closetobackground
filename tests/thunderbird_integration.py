#!/usr/bin/python3
"""Smoke test real Thunderbird in a disposable profile and private X11/D-Bus session.

Run: dbus-run-session -- xvfb-run -a python3 tests/thunderbird_integration.py
Requires Thunderbird, Xvfb, xfwm4, and PyGObject. Never uses a personal profile.
"""

import argparse
import json
import base64
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from install import install, EXTENSION_ID
from dbus_integration import WATCHER_XML
from gi.repository import Gio, GLib


class Marionette:
    def __init__(self, port, process):
        end = time.monotonic() + 30
        while True:
            try:
                self.socket = socket.create_connection(("127.0.0.1", port), timeout=1)
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > end:
                    raise RuntimeError("Thunderbird did not start Marionette")
                time.sleep(.2)
        self.socket.settimeout(30)
        self.read()
        self.serial = 0
        self.command("WebDriver:NewSession", {"capabilities": {"alwaysMatch": {"acceptInsecureCerts": True}}})
        self.command("Marionette:SetContext", {"value": "chrome"})
        self.command("WebDriver:SetTimeouts", {"script": 20000})

    def read(self):
        length = bytearray()
        while True:
            byte = self.socket.recv(1)
            if not byte:
                raise EOFError("Marionette closed")
            if byte == b":":
                break
            length.extend(byte)
        payload = bytearray()
        size = int(length)
        while len(payload) < size:
            chunk = self.socket.recv(size - len(payload))
            if not chunk:
                raise EOFError("Truncated Marionette packet")
            payload.extend(chunk)
        return json.loads(payload)

    def command(self, name, parameters):
        self.serial += 1
        data = json.dumps([0, self.serial, name, parameters]).encode()
        self.socket.sendall(str(len(data)).encode() + b":" + data)
        reply = self.read()
        if reply[2]:
            raise RuntimeError(f"{name}: {reply[2]}")
        return reply[3]

    def script(self, source, args=()):
        body = "const done = arguments[arguments.length - 1]; (async () => {" + source + "})().then(done, error => done({testError: String(error), stack: error.stack}));"
        reply = self.command("WebDriver:ExecuteAsyncScript", {"script": body, "args": list(args),
                               "newSandbox": True, "sandbox": "system", "line": 1,
                               "filename": "close-to-background-smoke"})
        value = reply.get("value")
        if isinstance(value, dict) and "testError" in value:
            raise RuntimeError(value)
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--locale', choices=('en-US', 'fr', 'fr-CA', 'de'), default='en-US',
                        help='UI locale to simulate in this disposable process (default: en-US)')
    args = parser.parse_args()
    expected_locale = 'fr' if args.locale.startswith('fr') else 'en'
    catalog = json.loads((ROOT / f'extension/_locales/{expected_locale}/messages.json').read_text())
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise SystemExit("Run inside dbus-run-session and xvfb-run (see script docstring).")
    loop = GLib.MainLoop()
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    registrations = queue.Queue()

    def registered(_connection, sender, _path, _interface, _method, _parameters, invocation):
        registrations.put(sender)
        invocation.return_value(None)

    def get_property(_connection, _sender, _path, _interface, name):
        return {"IsStatusNotifierHostRegistered": GLib.Variant("b", True),
                "RegisteredStatusNotifierItems": GLib.Variant("as", []),
                "ProtocolVersion": GLib.Variant("i", 0)}[name]

    node = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
    object_id = bus.register_object("/StatusNotifierWatcher", node.interfaces[0], registered, get_property, None)
    owner_id = Gio.bus_own_name_on_connection(bus, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE, None, None)
    process = None
    wm = None
    with tempfile.TemporaryDirectory(prefix="thunderbird-tray-smoke-", ignore_cleanup_errors=True) as directory:
        work = Path(directory)
        profile = work / "profile"
        profile.mkdir()
        _, manifest_path = install(work)
        from package_support import policy_test_command
        policy_path = work / 'test-policies.json'
        policy_path.write_text('{"policies":{}}')
        command = policy_test_command(work, policy_path, manifest_path)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        prefs = {
            "marionette.port": port,
            "mail.provider.suppress_dialog_on_startup": True,
            "mail.shell.checkDefaultClient": False,
            "mailnews.start_page.enabled": False,
            "mailnews.start_page.override_url": "",
            "datareporting.policy.dataSubmissionEnabled": False,
            "toolkit.telemetry.enabled": False,
            "app.update.auto": False,
            "extensions.update.enabled": False,
            "extensions.getAddons.cache.enabled": False,
            "browser.aboutwelcome.enabled": False,
        }
        (profile / "user.js").write_text("\n".join(f"user_pref({json.dumps(key)}, {json.dumps(value)});" for key, value in prefs.items()))
        environment = {**os.environ, "MOZ_ENABLE_WAYLAND": "0", "MOZ_MARIONETTE": "1",
                       "XDG_CONFIG_HOME": str(work / "config"), "XDG_CACHE_HOME": str(work / "cache"),
                       "XDG_DATA_HOME": str(work / "data"), "XDG_RUNTIME_DIR": str(work / "runtime"),
                       "GTK_USE_PORTAL": "0", "GIO_USE_VFS": "local", "NO_AT_BRIDGE": "1"}
        (work / "runtime").mkdir(mode=0o700)
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                      'UpdateActivationEnvironment', GLib.Variant('(a{ss})', ({key: value for key, value in environment.items()
                        if key.startswith('XDG_') or key in ('DISPLAY', 'XAUTHORITY', 'GIO_USE_VFS', 'GTK_USE_PORTAL', 'NO_AT_BRIDGE')},)),
                      None, Gio.DBusCallFlags.NONE, 3000, None)
        logs = work / "thunderbird.log"
        try:
            with logs.open("w") as log:
                wm = subprocess.Popen(["xfwm4", "--compositor=off"], env=environment, stdout=log, stderr=log)
                process = subprocess.Popen([*command, "--profile", str(profile),
                                            "--marionette", "--remote-allow-system-access"],
                                           env=environment, stdout=log, stderr=log)
            client = Marionette(port, process)
            result = client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const {FileUtils} = ChromeUtils.importESModule('resource://gre/modules/FileUtils.sys.mjs');
              // Exercise actual locale negotiation without downloading language packs.
              // Only this disposable process sees the additional available UI locale.
              Services.locale.availableLocales = [...new Set([...Services.locale.availableLocales, arguments[2]])];
              Services.locale.requestedLocales = [arguments[2]];
              // Override the native manifest directory in THIS disposable process only.
              Services.dirsvc.set('XREUserNativeManifests', new FileUtils.File(arguments[0]));
              await AddonManager.installTemporaryAddon(new FileUtils.File(arguments[1]));
              return {version: Services.appinfo.version, locale: Services.locale.appLocaleAsBCP47};
            """, [str(manifest_path.parent.parent), str(ROOT / "extension"), args.locale])
            assert result['locale'] == args.locale, result
            print("Loaded extension in Thunderbird", result, flush=True)
            destination = registrations.get(timeout=15)
            print("Native helper registered with test tray", flush=True)
            time.sleep(1)
            prelude = """
              const {ExtensionParent} = ChromeUtils.importESModule('resource://gre/modules/ExtensionParent.sys.mjs');
              const extension = ExtensionParent.GlobalManager.getExtension('closetobackground@thunderbird-background.local');
              const view = [...extension.views].find(view => view.viewType === 'background');
              const bg = {messenger: {
                backgroundWindows: extension.apiManager.getAPI('backgroundWindows', extension, 'addon_parent').getAPI(view).backgroundWindows,
                runtime: extension.apiManager.getAPI('runtime', extension, 'addon_parent').getAPI(view).runtime,
              }};
              const win = Services.wm.getMostRecentWindow('mail:3pane');
              const base = win.docShell.treeOwner.QueryInterface(Ci.nsIBaseWindow);
            """
            localization = client.script(prelude + """
              return {locale: extension.localeData.selectedLocale, description: extension.manifest.description};
            """)
            assert localization == {'locale': expected_locale, 'description': catalog['extensionDescription']['message']}, localization
            tray_title = bus.call_sync(destination, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties', 'Get',
                                      GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Title')), None,
                                      Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
            title_key = 'trayUnreadOne' if expected_locale == 'fr' else 'trayUnreadOther'
            assert tray_title == catalog[title_key]['message'].replace('$COUNT$', '0'), tray_title
            print(f'PASS {args.locale} selects {expected_locale} for the manifest and native tray', flush=True)
            client.script(prelude + "win.document.title = 'Close to Background smoke main'; return true;")

            def visible():
                time.sleep(.25)
                return subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Close to Background smoke main$'],
                                      env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

            assert visible(), 'Cannot find visible test window'
            client.script(prelude + "await bg.messenger.backgroundWindows.hideAll(); return true;")
            assert not visible(), 'Window is still mapped after hiding'
            bus.call_sync(destination, "/StatusNotifierItem", "org.kde.StatusNotifierItem", "Activate",
                          GLib.Variant("(ii)", (0, 0)), None, Gio.DBusCallFlags.NONE, 3000, None)
            time.sleep(.5)
            assert visible(), 'Tray activation did not map the window'
            print("PASS native hide and tray-click restore", flush=True)
            original_window = client.script(prelude + 'return win.browsingContext.id;')
            client.script(prelude + 'await bg.messenger.backgroundWindows.hideAll(); return true;')
            assert not visible()
            launched = subprocess.run([*command, '--profile', str(profile)], env=environment,
                                      capture_output=True, text=True, timeout=10)
            assert launched.returncode == 0, launched.stderr
            deadline = time.monotonic() + 10
            while not visible() and time.monotonic() < deadline:
                time.sleep(.1)
            assert visible(), 'A second Thunderbird launch did not restore the hidden window'
            assert client.script(prelude + 'return win.browsingContext.id;') == original_window
            assert client.script('return [...Services.wm.getEnumerator("mail:3pane")].length;') == 1
            launched = subprocess.run([*command, '--profile', str(profile)], env=environment,
                                      capture_output=True, text=True, timeout=10)
            assert launched.returncode == 0, launched.stderr
            assert visible(), 'A second launch must not hide an already visible window'
            print('PASS second launch restores the existing X11 window and preserves visible-window behavior', flush=True)
            client.script(prelude + """
              const button = win.document.querySelector('.titlebar-close');
              if (!button) throw new Error('Thunderbird close button is missing');
              button.dispatchEvent(new win.Event('command', {bubbles: true}));
              return true;
            """)
            assert not visible(), 'Titlebar close did not hide the window'
            assert process.poll() is None
            assert client.script(prelude + 'return !win.closed;') is True
            client.script(prelude + 'await bg.messenger.backgroundWindows.restoreAll(); return true;')
            assert visible()
            print('PASS Thunderbird titlebar close hides without exiting on X11', flush=True)
            window_id = subprocess.check_output(['xdotool', 'search', '--onlyvisible', '--name',
                                                 '^Close to Background smoke main$'], env=environment).decode().splitlines()[0]
            subprocess.run(['xdotool', 'windowactivate', '--sync', window_id, 'key', '--clearmodifiers', 'alt+F4'],
                           env=environment, check=True)
            time.sleep(.3)
            assert not visible()
            assert client.script(prelude + "return !win.closed;") is True
            print("PASS native window-manager close interception", flush=True)
            client.script(prelude + """
              await bg.messenger.backgroundWindows.configure({enabled: false, closeToTray: true, minimizeToTray: true});
              return true;
            """)
            assert visible()
            print("PASS disabling restores hidden window", flush=True)
            client.script(prelude + """
              await bg.messenger.backgroundWindows.configure({enabled: true, closeToTray: true, minimizeToTray: true});
              win.minimize(); return true;
            """)
            time.sleep(.5)
            assert client.script(prelude + "return extension.apiManager.getAPI('backgroundWindows', extension).windows.get(win).hidden;") is True
            client.script(prelude + "await bg.messenger.backgroundWindows.restoreAll(); return true;")
            assert visible()
            print("PASS native minimize-to-tray", flush=True)
            client.script(prelude + "await bg.messenger.runtime.openOptionsPage(); return true;")
            time.sleep(1)
            print("Options:", client.script(prelude + """
              return [...extension.views].map(view => ({type: view.viewType, url: view.uri?.spec}));
            """), flush=True)

            def options_script(source):
                return client.script(prelude + """
                  const browser = win.document.getElementById('tabmail').currentTabInfo.browser;
                  const actor = browser.browsingContext.currentWindowGlobal.getActor('MarionetteCommands');
                  return await actor.executeScript(arguments[0], [], {sandboxName: 'system', newSandbox: true});
                """, [source])

            options = options_script("""
              return {lang: document.documentElement.lang, title: document.title,
                restore: document.querySelector('#restore').textContent,
                label: document.querySelector('#settings').getAttribute('aria-label'),
                tooltip: document.querySelector('#unread').title,
                status: document.querySelector('#status-title').textContent};
            """)
            assert options == {'lang': expected_locale, 'title': catalog['optionsTitle']['message'],
                               'restore': catalog['actionRestore']['message'], 'label': catalog['settingsLabel']['message'],
                               'tooltip': catalog['unreadMessages']['message'], 'status': catalog['statusReady']['message']}, options
            options_script('document.querySelector(\'input[name="notifications"]\').click(); return true;')
            deadline = time.monotonic() + 5
            while options_script("return document.querySelector('#testNotification').disabled;"):
                assert time.monotonic() < deadline, 'Notification test button did not enable'
                time.sleep(.1)
            options_script("document.querySelector('#testNotification').click(); return true;")
            notification = None
            deadline = time.monotonic() + 5
            while not notification and time.monotonic() < deadline:
                notification = client.script(prelude + """
                  return extension.apiManager.getAPI('notifications', extension, 'addon_parent')
                    .notificationsMap.get('close-to-background-mail')?.options ?? null;
                """)
                time.sleep(.1)
            assert notification and notification['message'] == catalog['notificationTest']['message'], notification
            print(f'PASS {args.locale} options, accessible labels and test notification', flush=True)
            screenshot = client.command('WebDriver:TakeScreenshot', {'id': None, 'full': False, 'scroll': False})['value']
            artifacts = ROOT / '.test-artifacts'
            artifacts.mkdir(exist_ok=True)
            (artifacts / f'thunderbird-options-{args.locale}.png').write_bytes(base64.b64decode(screenshot))
            client.script(prelude + """
              await bg.messenger.backgroundWindows.configure({enabled: true, closeToTray: true, minimizeToTray: true});
              await bg.messenger.backgroundWindows.hideAll();
              return true;
            """)
            Gio.bus_unown_name(owner_id)
            owner_id = None
            time.sleep(.7)
            client.script(prelude + "win.document.title = 'Close to Background smoke main'; return true;")
            assert visible()
            print("PASS losing tray restores Thunderbird", flush=True)
            print("PASS Thunderbird integration", flush=True)
        except Exception:
            print(logs.read_text()[-14000:], file=sys.stderr)
            raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if wm:
                wm.terminate()
                wm.wait(timeout=5)
            # A portal may have mounted a FUSE document directory on this private bus.
            # Unmount only the test directory before TemporaryDirectory cleanup.
            if shutil.which('fusermount3'):
                subprocess.run(['fusermount3', '-u', str(work / 'runtime/doc')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            if owner_id:
                Gio.bus_unown_name(owner_id)
            bus.unregister_object(object_id)
            loop.quit()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()
