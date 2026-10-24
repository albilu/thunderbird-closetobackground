#!/usr/bin/python3
"""Test automatic XPI upgrades and removal in a disposable Thunderbird profile.

Run with dbus-run-session -- xvfb-run -a python3 tests/policy_integration.py.
No personal profile, system package database, or system policy is changed.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import zipfile

from thunderbird_integration import Marionette
from package_support import prepare_package, prepare_policy, policy_test_command
from integration import EXTENSION_ID


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path)
    args = parser.parse_args()
    if not os.environ.get('DISPLAY') or not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
        parser.error('Run inside dbus-run-session and xvfb-run')
    process = None
    with tempfile.TemporaryDirectory(prefix='thunderbird-policy-test-') as directory:
        work = Path(directory)
        manifest, xpi, artifact = prepare_package(work, args.package)
        assert artifact.suffix == '.deb', 'Automatic installation is provided by the Debian package'
        print(f'Testing automatic installation: {artifact.name}', flush=True)
        profile = work / 'profile'
        profile.mkdir()
        policy_path = work / 'test-policies.json'
        policy_path.write_text('{"policies":{}}')
        command = policy_test_command(work, policy_path, manifest)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        preferences = {'marionette.port': port, 'mail.provider.suppress_dialog_on_startup': True,
                       'mail.shell.checkDefaultClient': False, 'mailnews.start_page.enabled': False,
                       'mailnews.start_page.override_url': '', 'app.update.auto': False,
                       'extensions.update.enabled': False, 'datareporting.policy.dataSubmissionEnabled': False,
                       'toolkit.telemetry.enabled': False, 'browser.policies.loglevel': 'debug'}
        (profile / 'user.js').write_text('\n'.join(
            f'user_pref({json.dumps(key)}, {json.dumps(value)});' for key, value in preferences.items()))
        (work / 'runtime').mkdir(mode=0o700)
        environment = {**os.environ, 'MOZ_ENABLE_WAYLAND': '0',
                       'MOZ_MARIONETTE': '1', 'XDG_CONFIG_HOME': str(work / 'config'),
                       'XDG_CACHE_HOME': str(work / 'cache'), 'XDG_DATA_HOME': str(work / 'data'),
                       'XDG_RUNTIME_DIR': str(work / 'runtime'), 'GIO_USE_VFS': 'local',
                       'NO_AT_BRIDGE': '1', 'GTK_USE_PORTAL': '0'}
        log = work / 'thunderbird.log'

        def launch():
            nonlocal process
            with log.open('a') as output:
                process = subprocess.Popen([*command, '--no-remote', '--profile', str(profile),
                                            '--marionette', '--remote-allow-system-access'],
                                           env=environment, stdout=output, stderr=output)
            client = Marionette(port, process)
            client.script("""
              const {FileUtils} = ChromeUtils.importESModule('resource://gre/modules/FileUtils.sys.mjs');
              if (Services.dirsvc.has('XREUserNativeManifests')) Services.dirsvc.undefine('XREUserNativeManifests');
              Services.dirsvc.set('XREUserNativeManifests', new FileUtils.File(arguments[0]));
              return true;
            """, [str(manifest.parent.parent)])
            return client

        def stop(client):
            try:
                client.script('Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit); return true;')
            except (EOFError, OSError):
                pass
            process.wait(timeout=15)
            client.socket.close()
            assert process.returncode == 0, process.returncode

        def addon_state(client):
            return client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const addon = await AddonManager.getAddonByID(arguments[0]);
              if (!addon) return null;
              return {version: addon.version, disabled: addon.userDisabled, temporary: addon.temporarilyInstalled,
                      source: addon.sourceURI?.spec,
                      canEnable: !!(addon.permissions & AddonManager.PERM_CAN_ENABLE),
                      canRemove: !!(addon.permissions & AddonManager.PERM_CAN_UNINSTALL)};
            """, [EXTENSION_ID])

        def wait_for_version(client, version):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = addon_state(client)
                if state and state['version'] == version:
                    return state
                time.sleep(.2)
            raise AssertionError(f'Automatic version {version} was not installed; last state: {state}')

        try:
            # Simulate a previous manually installed release in an existing
            # profile. Subsequent startup must upgrade it without any install API.
            old_xpi = work / 'previous-version.xpi'
            with zipfile.ZipFile(xpi) as source, zipfile.ZipFile(old_xpi, 'w') as older:
                expected_version = json.loads(source.read('manifest.json'))['version']
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == 'manifest.json':
                        old_manifest = json.loads(data)
                        old_manifest['version'] = '0.0.1'
                        old_manifest['browser_action'] = {'default_title': 'Close to Background settings',
                                                          'default_icon': 'icons/mail.svg'}
                        data = json.dumps(old_manifest).encode()
                    older.writestr(info, data)
            client = launch()
            assert addon_state(client) is None
            client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              const {FileUtils} = ChromeUtils.importESModule('resource://gre/modules/FileUtils.sys.mjs');
              const install = await AddonManager.getInstallForFile(new FileUtils.File(arguments[0]));
              await install.install();
              const addon = await AddonManager.getAddonByID(arguments[1]);
              await addon.disable();
              // Model a saved customized toolbar from the previous release,
              // including the reserved slot of a currently disabled add-on.
              const {getState, storeState} = ChromeUtils.importESModule('resource:///modules/CustomizationState.mjs');
              const toolbar = getState();
              toolbar.mail = [...(toolbar.mail ?? []), 'ext-' + arguments[1]];
              storeState(toolbar);
              Services.prefs.setStringPref('closetobackground.test.profile', 'preserved');
              return true;
            """, [str(old_xpi), EXTENSION_ID])
            assert addon_state(client)['version'] == '0.0.1'
            toolbar_state = """
              const {getState} = ChromeUtils.importESModule('resource:///modules/CustomizationState.mjs');
              return Object.values(getState()).some(items => items.includes('ext-' + arguments[0]));
            """
            assert client.script(toolbar_state, [EXTENSION_ID]), 'Previous toolbar button was not registered'
            stop(client)

            prepare_policy(work, xpi)
            client = launch()
            state = wait_for_version(client, expected_version)
            assert state == {'version': expected_version, 'disabled': True, 'temporary': False,
                             'source': xpi.as_uri(), 'canEnable': True, 'canRemove': False}, state
            assert client.script("return Services.prefs.getStringPref('closetobackground.test.profile');") == 'preserved'
            assert not client.script(toolbar_state, [EXTENSION_ID]), 'Obsolete toolbar button remains after upgrade'
            print('PASS automatic upgrade of a manually installed XPI in an existing profile', flush=True)
            print('PASS obsolete settings toolbar button removed during upgrade', flush=True)
            print('PASS disabled state and unrelated profile preferences preserved', flush=True)
            stop(client)

            # Real package removal restores the policy. Thunderbird owns its
            # profile copy: it must become removable, not be deleted as root.
            root = work / 'system'
            subprocess.run(['/bin/sh', str(root / 'DEBIAN/prerm'), 'remove'],
                           env={**os.environ, 'DPKG_ROOT': str(root)}, check=True, stdout=subprocess.DEVNULL)
            policy_path.write_text('{"policies":{}}')
            xpi.unlink()
            client = launch()
            state = addon_state(client)
            assert state['canRemove'] and state['disabled'], state
            client.script("""
              const {AddonManager} = ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
              await (await AddonManager.getAddonByID(arguments[0])).uninstall(); return true;
            """, [EXTENSION_ID])
            assert addon_state(client) is None
            stop(client)
            client = launch()
            assert addon_state(client) is None, 'Removed package must not reinstall the add-on'
            stop(client)
            print('PASS package removal releases add-on management and does not reinstall it', flush=True)
            print('PASS Thunderbird policy integration', flush=True)
        except Exception:
            if log.exists():
                print(log.read_text()[-14000:])
            raise
        finally:
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
