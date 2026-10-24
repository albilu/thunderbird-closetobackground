#!/usr/bin/env python3
"""Test release installation, upgrade and removal without changing the host system."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from package_support import extract_tar, ROOT
from build import build
from integration import PACKAGE_NAME, SYSTEM_HELPER, SYSTEM_MANIFEST, locations
from policy import SYSTEM_POLICY, STATE_FILE, EXTENSION_ID


def main():
    if not shutil.which('dpkg') or not shutil.which('fakeroot'):
        raise SystemExit('Package lifecycle tests require dpkg and fakeroot')
    with tempfile.TemporaryDirectory(prefix='tray-package-test-') as directory:
        work = Path(directory)
        artifacts = build(work / 'release')
        bundle = extract_tar(artifacts['tar'], work / 'tar')
        home = work / 'home with spaces'
        target, manifest_path = locations(home)
        for _ in range(2):
            subprocess.run([str(bundle / 'install.sh'), '--user-home', str(home)], check=True, stdout=subprocess.DEVNULL)
        assert manifest_path.exists() and os.access(target / 'host.py', os.X_OK)
        (target / 'keep-user-file.txt').write_text('user-owned file')
        subprocess.run([str(bundle / 'uninstall.sh'), '--user-home', str(home)], check=True, stdout=subprocess.DEVNULL)
        assert not manifest_path.exists() and not (target / 'host.py').exists()
        assert (target / 'keep-user-file.txt').read_text() == 'user-owned file'
        print('PASS runtime tar install/update/uninstall with spaces and unrelated files')

        # The dpkg database AND install root are private. Maintainer scripts run
        # with DPKG_ROOT; no host package database or real policies are touched.
        root = work / 'dpkg-root'
        (root / 'var/lib/dpkg/updates').mkdir(parents=True)
        (root / 'var/lib/dpkg/status').write_text('')
        command = ['fakeroot', '--', 'dpkg', f'--root={root}', f'--log={work / "dpkg.log"}',
                   '--force-bad-path', '--force-depends', '--force-script-chrootless']
        policy_path = root / SYSTEM_POLICY.relative_to('/')
        policy_path.parent.mkdir(parents=True)
        original_policy = '{"policies":{"DisableTelemetry":true}}\n'
        policy_path.write_text(original_policy)

        def dpkg(*args):
            result = subprocess.run([*command, *args], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)

        dpkg('--install', str(artifacts['deb']))
        executable = root / SYSTEM_HELPER.relative_to('/')
        registration = root / SYSTEM_MANIFEST.relative_to('/')
        assert os.access(executable, os.X_OK) and registration.exists()
        assert json.loads(policy_path.read_text())['policies']['ExtensionSettings'][EXTENSION_ID]['installation_mode'] == 'normal_installed'
        # Same-version reinstall is the normal dpkg replacement path.
        dpkg('--install', str(artifacts['deb']))
        upgrade = build(work / 'upgrade', formats=('deb',), revision='2')['deb']
        dpkg('--install', str(upgrade))
        status = subprocess.check_output([*command, '--status', PACKAGE_NAME]).decode()
        version = json.loads((ROOT / 'extension/manifest.json').read_text())['version']
        assert f'Version: {version}-2' in status
        doctor = root / 'usr/bin' / f'{PACKAGE_NAME}-doctor'
        subprocess.run([str(doctor), '--system-root', str(root), '--user-home', str(work / 'empty-user'),
                        '--installation-only'], check=True, stdout=subprocess.DEVNULL)
        assert not list((root / 'usr/share' / PACKAGE_NAME).rglob('__pycache__'))
        dpkg('--remove', PACKAGE_NAME)
        assert not executable.exists() and not registration.exists() and not doctor.exists()
        assert policy_path.read_text() == original_policy
        assert not (root / STATE_FILE.relative_to('/')).exists()
        dpkg('--purge', PACKAGE_NAME)
        assert not (root / 'usr/share' / PACKAGE_NAME).exists()
        print('PASS Debian install/reinstall/upgrade/remove/purge in a private dpkg root')


if __name__ == '__main__':
    main()
