#!/usr/bin/python3
"""End-to-end test on real headless GNOME Wayland and its AppIndicator extension.

Run: dbus-run-session -- python3 tests/gnome_integration.py
Requires GNOME Shell 45+, Thunderbird, PyGObject, and system AppIndicator and
Dash to Dock extensions.
The compositor, preferences, helper, and Thunderbird profile are all disposable.
"""

import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from thunderbird_integration import Marionette, ROOT, install
from mail_fixture import CREATE_MAIL, MARK_READ
from package_support import prepare_package, prepare_policy, policy_test_command
from gi.repository import Gio, GLib

TITLE = 'Close to Background Wayland test'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, help='Release .deb or -linux.tar.gz (default: build a temporary .deb)')
    args = parser.parse_args()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    candidates = ['ubuntu-appindicators@ubuntu.com', 'appindicatorsupport@rgcjonas.gmail.com']
    indicator = next((name for name in candidates if (Path('/usr/share/gnome-shell/extensions') / name).is_dir()), None)
    if not indicator:
        raise SystemExit('Install the system GNOME AppIndicator extension before this test.')
    dock = 'dash-to-dock@micxgx.gmail.com'
    if not (Path('/usr/share/gnome-shell/extensions') / dock).is_dir():
        raise SystemExit('Install the system Dash to Dock extension before this test.')
    process = shell = None
    with tempfile.TemporaryDirectory(prefix='thunderbird-gnome-smoke-', ignore_cleanup_errors=True) as directory:
        work = Path(directory)
        environment = {**os.environ, 'MOZ_ENABLE_WAYLAND': '1', 'MOZ_MARIONETTE': '1',
                       'XDG_CONFIG_HOME': str(work / 'config'), 'XDG_CACHE_HOME': str(work / 'cache'),
                       'XDG_DATA_HOME': str(work / 'data'), 'XDG_RUNTIME_DIR': str(work / 'runtime'),
                       'XDG_CURRENT_DESKTOP': 'GNOME', 'XDG_SESSION_TYPE': 'wayland',
                       'WAYLAND_DISPLAY': 'tray-smoke-wayland', 'GSETTINGS_BACKEND': 'keyfile',
                       'LIBGL_ALWAYS_SOFTWARE': '1', 'GIO_USE_VFS': 'local', 'NO_AT_BRIDGE': '1'}
        environment.pop('DISPLAY', None)
        (work / 'runtime').mkdir(mode=0o700)
        bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                      'UpdateActivationEnvironment', GLib.Variant('(a{ss})', ({key: value for key, value in environment.items()
                        if key.startswith('XDG_') or key in ('WAYLAND_DISPLAY', 'GSETTINGS_BACKEND', 'GIO_USE_VFS', 'NO_AT_BRIDGE')},)),
                      None, Gio.DBusCallFlags.NONE, 3000, None)
        extensions = work / 'data/gnome-shell/extensions'
        shutil.copytree(ROOT / 'tests/fixtures/gnome-inspector', extensions / 'tray-smoke@local')
        # The same application ID/activation API as the Dash, but its launcher
        # and target profile exist only inside this disposable desktop session.
        launcher = work / 'launch-thunderbird'
        # Gio validates Exec while scanning desktop files at Shell startup.
        # Replace this inert placeholder before any test activation can occur.
        launcher.write_text('#!/bin/sh\nexit 1\n')
        launcher.chmod(0o755)
        applications = work / 'data/applications'
        applications.mkdir(parents=True)
        (applications / 'thunderbird.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Thunderbird launcher test\n'
            f'Exec="{launcher}"\nIcon=thunderbird\nStartupWMClass=thunderbird-default\n'
            'StartupNotify=true\nTerminal=false\n')
        for schema, key, value in [('org.gnome.shell', 'enabled-extensions', str([indicator, dock, 'tray-smoke@local'])),
                                   ('org.gnome.shell', 'disable-user-extensions', 'false'),
                                   ('org.gnome.shell', 'favorite-apps', "['thunderbird.desktop']"),
                                   ('org.gnome.shell.extensions.dash-to-dock', 'click-action', 'minimize'),
                                   ('org.gnome.shell.extensions.dash-to-dock', 'show-trash', 'false'),
                                   ('org.gnome.shell.extensions.dash-to-dock', 'show-mounts', 'false'),
                                   ('org.gnome.desktop.interface', 'enable-animations', 'false')]:
            subprocess.run(['gsettings', 'set', schema, key, value], env=environment, check=True)

        def call(destination, path, interface, method, parameters=None):
            return bus.call_sync(destination, path, interface, method, parameters, None,
                                 Gio.DBusCallFlags.NONE, 3000, None)

        def windows():
            value = call('org.gnome.Shell', '/net/thunderbird/TrayTest', 'net.thunderbird.TrayTest', 'Windows')
            return json.loads(value.unpack()[0])

        def visible():
            return any(window['title'] == TITLE and window['visible'] for window in windows())

        def wait(predicate, label, seconds=15):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    value = predicate()
                    if value:
                        return value
                except GLib.Error:
                    pass
                time.sleep(.2)
            raise AssertionError(f'Timed out waiting for {label}')

        def helper_destination():
            values = call('org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher',
                          'org.freedesktop.DBus.Properties', 'Get',
                          GLib.Variant('(ss)', ('org.kde.StatusNotifierWatcher', 'RegisteredStatusNotifierItems'))).unpack()[0]
            return next((item.split('/')[0] for item in values if item.startswith('org.kde.StatusNotifierItem-')), None)

        shell_log = work / 'gnome.log'
        thunderbird_log = work / 'thunderbird.log'
        try:
            with shell_log.open('w') as output:
                shell = subprocess.Popen(['gnome-shell', '--headless', '--wayland', '--no-x11',
                                          '--wayland-display=tray-smoke-wayland', '--virtual-monitor=1280x900'],
                                         env=environment, stdout=output, stderr=output)
            wait(lambda: windows() is not None, 'GNOME test extension', 25)
            print('GNOME Wayland compositor and AppIndicator extension started', flush=True)
            profile = work / 'profile'
            profile.mkdir()
            manifest_path, xpi_path, package_path = prepare_package(work, args.package)
            print(f'Testing release package: {package_path.name}', flush=True)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            prefs = {'marionette.port': port, 'mail.provider.suppress_dialog_on_startup': True,
                     'mail.shell.checkDefaultClient': False, 'mailnews.start_page.enabled': False,
                     'mailnews.start_page.override_url': '', 'app.update.auto': False,
                     'extensions.update.enabled': False, 'datareporting.policy.dataSubmissionEnabled': False,
                     'toolkit.telemetry.enabled': False}
            automatic = package_path.suffix == '.deb'
            if automatic:
                policy_path = prepare_policy(work, xpi_path)
            else:
                policy_path = work / 'test-policies.json'
                policy_path.write_text('{"policies":{}}')
            command = policy_test_command(work, policy_path, manifest_path)
            launcher.write_text('#!/usr/bin/python3\nimport os\n' +
                                f'command = {[*command, "--profile", str(profile)]!r}\n' +
                                'os.execvp(command[0], command)\n')
            launcher.chmod(0o755)
            (profile / 'user.js').write_text('\n'.join(f'user_pref({json.dumps(key)}, {json.dumps(value)});' for key, value in prefs.items()))
            with thunderbird_log.open('w') as output:
                # The private bus/profile isolate remoting from the real desktop.
                # Keep remoting enabled so an actual second launch can be tested.
                process = subprocess.Popen([*command, '--profile', str(profile),
                                            '--marionette', '--remote-allow-system-access'],
                                           env=environment, stdout=output, stderr=output)
            client = Marionette(port, process)
            version = client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const {FileUtils} = ChromeUtils.importESModule('resource://gre/modules/FileUtils.sys.mjs');
              if (Services.dirsvc.has('XREUserNativeManifests')) Services.dirsvc.undefine('XREUserNativeManifests');
              Services.dirsvc.set('XREUserNativeManifests', new FileUtils.File(arguments[0]));
              if (!arguments[2]) {
                await AddonManager.installTemporaryAddon(new FileUtils.File(arguments[1]));
              }
              return Services.appinfo.version;
            """, [str(manifest_path.parent.parent), str(xpi_path), automatic])
            if automatic:
                installed = wait(lambda: client.script("""
                  const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
                  const addon = await AddonManager.getAddonByID('closetobackground@thunderbird-background.local');
                  if (!addon?.isActive) return null;
                  return {temporary: addon.temporarilyInstalled, source: addon.sourceURI.spec,
                          canDisable: !!(addon.permissions & AddonManager.PERM_CAN_DISABLE),
                          canRemove: !!(addon.permissions & AddonManager.PERM_CAN_UNINSTALL)};
                """), 'automatic package add-on installation')
                assert installed == {'temporary': False, 'source': xpi_path.as_uri(), 'canDisable': True, 'canRemove': False}, installed
                print('PASS automatic XPI installation on startup, with user disable allowed', flush=True)
            destination = wait(helper_destination, 'actual GNOME tray registration')
            print(f'Thunderbird {version}: helper registered with actual GNOME AppIndicator', flush=True)
            prelude = """
              const {ExtensionParent} = ChromeUtils.importESModule('resource://gre/modules/ExtensionParent.sys.mjs');
              const extension = ExtensionParent.GlobalManager.getExtension('closetobackground@thunderbird-background.local');
              const view = [...extension.views].find(view => view.viewType === 'background');
              const controller = extension.apiManager.getAPI('backgroundWindows', extension, 'addon_parent');
              const api = controller.getAPI(view).backgroundWindows;
              const runtime = extension.apiManager.getAPI('runtime', extension, 'addon_parent').getAPI(view).runtime;
              const win = Services.wm.getMostRecentWindow('mail:3pane');
            """
            client.script(prelude + 'win.document.title = arguments[0]; return true;', [TITLE])
            wait(visible, 'visible main window')
            main_window = next(window for window in windows() if window['title'] == TITLE)
            assert main_window['clientType'] == 'wayland', main_window
            assert 'DISPLAY' not in environment
            print('PASS native Wayland client confirmed by GNOME (no XWayland)', flush=True)
            time.sleep(.5)
            client.script(prelude + 'await api.hideAll(); return true;')
            wait(lambda: not visible(), 'Wayland window hidden')
            call(destination, '/StatusNotifierItem', 'org.kde.StatusNotifierItem', 'Activate', GLib.Variant('(ii)', (0, 0)))
            wait(visible, 'Wayland tray restore')
            print('PASS Wayland hide and tray activation restore', flush=True)
            original_window = client.script(prelude + 'return win.browsingContext.id;')
            client.script(prelude + 'await api.hideAll(); return true;')
            wait(lambda: not visible(), 'hidden before a second Thunderbird launch')
            launched = subprocess.run([*command, '--profile', str(profile)], env=environment,
                                      capture_output=True, text=True, timeout=10)
            assert launched.returncode == 0, launched.stderr
            wait(visible, 'window restored by a real second Thunderbird launch')
            assert client.script(prelude + 'return win.browsingContext.id;') == original_window
            assert client.script('return [...Services.wm.getEnumerator("mail:3pane")].length;') == 1
            print('PASS second Thunderbird launch restores the existing hidden window', flush=True)
            client.script(prelude + 'await api.hideAll(); return true;')
            wait(lambda: not visible(), 'hidden before GNOME Dash application activation')
            call('org.gnome.Shell', '/net/thunderbird/TrayTest', 'net.thunderbird.TrayTest', 'ActivateApplication')
            wait(visible, 'window restored through GNOME application activation')
            assert client.script(prelude + 'return win.browsingContext.id;') == original_window
            assert client.script('return [...Services.wm.getEnumerator("mail:3pane")].length;') == 1

            def application_ready():
                state = json.loads(call('org.gnome.Shell', '/net/thunderbird/TrayTest',
                                        'net.thunderbird.TrayTest', 'ApplicationState').unpack()[0])
                return state['running'] and not state['starting'] and state['windows'] == 1

            wait(application_ready, 'GNOME launcher leaves its starting state')
            call('org.gnome.Shell', '/net/thunderbird/TrayTest', 'net.thunderbird.TrayTest', 'ActivateApplication')
            time.sleep(.5)
            assert visible(), 'Activating a visible window must not send it to the tray'
            print('PASS GNOME Dash activation restores the hidden window and completes startup', flush=True)
            print('PASS visible application activation keeps the window visible', flush=True)

            def dock_state():
                return json.loads(call('org.gnome.Shell', '/net/thunderbird/TrayTest',
                                       'net.thunderbird.TrayTest', 'DockState').unpack()[0])

            def click_dash():
                call('org.gnome.Shell', '/net/thunderbird/TrayTest', 'net.thunderbird.TrayTest', 'ClickDash')

            def dock_minimized():
                return any(window['title'] == TITLE and window['minimized'] and not window['visible']
                           for window in windows())

            wait(dock_state, 'Thunderbird icon in the actual Dash to Dock extension')
            # "Minimize" first focuses an unfocused window, then toggles it.
            if not dock_state()['focused']:
                click_dash()
                wait(lambda: dock_state()['focused'], 'Dash to Dock focuses the visible window')
                assert visible(), 'The first click should focus an unfocused window'
            click_dash()
            wait(dock_minimized, 'Dash to Dock minimizes the focused window')
            # A compositor minimize retains the window in the dock; it is not
            # converted into a tray hide on Wayland.
            assert dock_state()['running'] and dock_state()['windows'] == 1
            assert not client.script(prelude + 'return controller.windows.get(win).hidden;')
            click_dash()
            wait(lambda: visible() and dock_state()['focused'], 'Dash to Dock restores its minimized window')
            print('PASS Dash to Dock minimize/restore clicks', flush=True)
            client.script(prelude + 'await api.hideAll(); return true;')
            wait(lambda: not visible() and not dock_state()['running'], 'hidden before a real dock launch')
            click_dash()
            wait(lambda: visible() and dock_state()['focused'], 'Dash to Dock restores and focuses a tray-hidden window')
            wait(application_ready, 'Dock launch finishes startup')
            assert client.script(prelude + 'return win.browsingContext.id;') == original_window
            assert client.script('return [...Services.wm.getEnumerator("mail:3pane")].length;') == 1
            click_dash()
            wait(dock_minimized, 'Dash to Dock minimizes a window restored from the tray')
            click_dash()
            wait(lambda: visible() and dock_state()['focused'], 'Dash to Dock restores after repeated clicks')
            print('PASS Dash to Dock tray restore followed by minimize/restore clicks', flush=True)

            # Honor a different dock preference as well. These settings belong
            # only to this temporary GNOME session, never the user's desktop.
            subprocess.run(['gsettings', 'set', 'org.gnome.shell.extensions.dash-to-dock',
                            'click-action', 'focus-or-previews'], env=environment, check=True)
            wait(lambda: dock_state()['clickAction'] == 'focus-or-previews', 'Dock focus action applied')
            click_dash()
            time.sleep(.5)
            assert visible() and dock_state()['focused'], 'A focus action must not force a minimize toggle'
            print('PASS Dash to Dock respects its configured focus action', flush=True)
            client.script(prelude + """
              const button = win.document.querySelector('.titlebar-close');
              if (!button) throw new Error('Thunderbird close button is missing');
              button.dispatchEvent(new win.Event('command', {bubbles: true}));
              return true;
            """)
            wait(lambda: not visible(), 'hidden after Thunderbird titlebar close button')
            assert process.poll() is None, 'Titlebar close exited Thunderbird'
            assert client.script(prelude + 'return !win.closed;') is True
            call(destination, '/StatusNotifierItem', 'org.kde.StatusNotifierItem', 'Activate', GLib.Variant('(ii)', (0, 0)))
            wait(visible, 'restoration after Thunderbird titlebar close')
            print('PASS Thunderbird titlebar close hides without exiting', flush=True)
            call('org.gnome.Shell', '/net/thunderbird/TrayTest', 'net.thunderbird.TrayTest', 'Close', GLib.Variant('(s)', (TITLE,)))
            wait(lambda: not visible(), 'GNOME compositor close intercepted')
            assert client.script(prelude + 'return !win.closed;') is True
            client.script(prelude + 'await api.restoreAll(); return true;')
            wait(visible, 'window restore after close')
            print('PASS GNOME native close intercepted without exiting Thunderbird', flush=True)
            # Thunderbird's CSD minimize button invokes this command. Wayland
            # compositor-only minimization has no client event (documented limitation).
            client.script(prelude + """
              const button = win.document.querySelector('.titlebar-min');
              if (!button) throw new Error('Thunderbird minimize button not found');
              button.dispatchEvent(new win.Event('command', {bubbles: true}));
              return true;
            """)
            wait(lambda: client.script(prelude + 'return controller.windows.get(win).hidden;'), 'Wayland minimize-to-tray')
            client.script(prelude + 'await api.restoreAll(); return true;')
            wait(visible, 'restore after minimizing')
            print('PASS GNOME native minimize-to-tray', flush=True)
            fixture = client.script(CREATE_MAIL)
            assert fixture == {'inbox': 3, 'trash': 1}, fixture

            def tray_title():
                return call(destination, '/StatusNotifierItem', 'org.freedesktop.DBus.Properties', 'Get',
                            GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Title'))).unpack()[0]

            wait(lambda: '3 unread' in tray_title(), 'real folder unread count excluding Trash')
            notification_script = prelude + """
              return extension.apiManager.getAPI('notifications', extension, 'addon_parent')
                .notificationsMap.get('close-to-background-mail')?.options ?? null;
            """
            notification = wait(lambda: client.script(notification_script), 'new-mail notification')
            assert notification['message'] == '3 new messages. Click to show Thunderbird.', notification
            print('PASS real folder counts and grouped private new-mail notification', flush=True)
            assert client.script(MARK_READ) == 0
            wait(lambda: '0 unread' in tray_title(), 'badge reset after marking mail read')
            print('PASS marking mail read updates badge to zero', flush=True)

            def menu_action(item):
                call(destination, '/MenuBar', 'com.canonical.dbusmenu', 'Event',
                     GLib.Variant('(isvu)', (item, 'clicked', GLib.Variant('i', 0), 0)))

            client.script(prelude + 'win.document.title = arguments[0]; await api.hideAll(); return true;', [TITLE])
            menu_action(4)
            wait(lambda: 'mode off' in tray_title(), 'disabled preference propagated to native helper')
            wait(visible, 'restoration when disabled from tray')
            menu_action(4)
            wait(lambda: '0 unread' in tray_title(), 're-enabled preference propagated to native helper')
            print('PASS tray Enable setting updates preferences and restores windows', flush=True)
            menu_action(5)
            wait(lambda: client.script(prelude + "return [...extension.views].some(view => view.uri?.spec.endsWith('/options/options.html'));"),
                 'settings opened from the tray menu')
            assert not client.script(prelude + "return !!win.document.querySelector('[item-id=\"ext-' + extension.id + '\"]');")
            print('PASS tray settings remain available without a settings toolbar button', flush=True)
            time.sleep(1)
            screenshot = client.command('WebDriver:TakeScreenshot', {'id': None, 'full': False, 'scroll': False})['value']
            artifacts = ROOT / '.test-artifacts'
            artifacts.mkdir(exist_ok=True)
            (artifacts / f'gnome-options-{package_path.suffix.lstrip(".")}.png').write_bytes(base64.b64decode(screenshot))
            client.script(prelude + 'win.document.title = arguments[0]; await api.hideAll(); return true;', [TITLE])
            wait(lambda: not visible(), 'hidden before GNOME tray loss')
            call('org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions', 'org.gnome.Shell.Extensions',
                 'DisableExtension', GLib.Variant('(s)', (indicator,)))
            wait(visible, 'automatic restore after GNOME tray extension disabled')
            print('PASS disabling real GNOME tray restores Thunderbird', flush=True)
            call('org.gnome.Shell.Extensions', '/org/gnome/Shell/Extensions', 'org.gnome.Shell.Extensions',
                 'EnableExtension', GLib.Variant('(s)', (indicator,)))
            wait(helper_destination, 'GNOME tray recovery')
            time.sleep(.5)
            client.script(prelude + 'await api.hideAll(); return true;')
            wait(lambda: not visible(), 'hidden before add-on disable')
            client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const addon = await AddonManager.getAddonByID('closetobackground@thunderbird-background.local');
              await addon.disable(); return true;
            """)
            wait(visible, 'restore after disabling add-on')
            print('PASS add-on disable restores hidden Thunderbird', flush=True)
            wait(lambda: not helper_destination(), 'helper cleanup after add-on disable')
            client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const addon = await AddonManager.getAddonByID('closetobackground@thunderbird-background.local');
              await addon.enable(); return true;
            """)
            destination = wait(helper_destination, 'helper restarted after re-enabling add-on')
            wait(lambda: '0 unread' in tray_title(), 'persisted enabled setting after reload')
            menu_action(7)
            process.wait(timeout=10)
            assert process.returncode == 0, process.returncode
            wait(lambda: not helper_destination(), 'helper cleanup after quitting Thunderbird')
            print('PASS normal Quit and helper cleanup', flush=True)
            print('PASS GNOME Wayland integration', flush=True)
        except Exception:
            for log in (shell_log, thunderbird_log):
                if log.exists():
                    print(log.read_text()[-12000:], file=sys.stderr)
            raise
        finally:
            for child in (process, shell):
                if child and child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            if shutil.which('fusermount3'):
                subprocess.run(['fusermount3', '-u', str(work / 'runtime/doc')],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    main()
