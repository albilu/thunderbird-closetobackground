import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import os
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build import build, release_metadata
from integration import HOST_NAME, EXTENSION_ID, PACKAGE_NAME, SYSTEM_HELPER, SYSTEM_MANIFEST


class BuildTests(unittest.TestCase):
    def test_xpi_resources_and_release_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            formats = ('xpi', 'tar', 'source', 'deb') if shutil.which('dpkg-deb') else ('xpi', 'tar', 'source')
            artifacts = build(work / 'first', formats=formats, maintainer='Release Tester <release@example.invalid>',
                              homepage='https://example.invalid/project', revision='2')
            xpi, bundle = artifacts['xpi'], artifacts['source']
            with zipfile.ZipFile(xpi) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                paths = [manifest['background']['page'], manifest['options_ui']['page'],
                         *manifest['icons'].values()]
                for experiment in manifest['experiment_apis'].values():
                    paths.extend([experiment['schema'], experiment['parent']['script']])
                for path in paths:
                    self.assertIn(path, archive.namelist())
                self.assertEqual(manifest['default_locale'], 'en')
                for locale in ('en', 'fr'):
                    messages = json.loads(archive.read(f'_locales/{locale}/messages.json'))
                    for field in ('name', 'description'):
                        key = manifest[field].removeprefix('__MSG_').removesuffix('__')
                        self.assertTrue(messages[key]['message'])
                self.assertIn('lib/i18n.mjs', archive.namelist())
                self.assertFalse(any(name.startswith(('tests/', 'native/')) for name in archive.namelist()))
            with tarfile.open(artifacts['tar']) as archive:
                names = [member.name.split('/', 1)[1] for member in archive.getmembers()]
                self.assertFalse(any(name.startswith(('tests/', 'extension/', '.test-artifacts/')) for name in names))
                self.assertNotIn('scripts/build.py', names)
                self.assertIn('install.sh', names)
                self.assertIn('uninstall.sh', names)
                self.assertIn(xpi.name, names)
                for member in archive.getmembers():
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    self.assertNotIn('__pycache__', member.name)
                    if member.name.endswith(('/install.sh', '/uninstall.sh', '/native/host.py')):
                        self.assertEqual(member.mode, 0o755)
            with tarfile.open(bundle) as archive:
                # Archive is built entirely from this project's known local sources.
                archive.extractall(work / 'extracted', filter='data')
            source = next((work / 'extracted').iterdir())
            subprocess.run([sys.executable, str(source / 'scripts/build.py'), '--formats', ','.join(formats), '--output', str(work / 'second')],
                           check=True, stdout=subprocess.DEVNULL)
            for file in artifacts.values():
                self.assertEqual(file.read_bytes(), (work / 'second' / file.name).read_bytes(), file.name)
            checksums = artifacts['checksums'].read_text().splitlines()
            self.assertEqual(len(checksums), len(formats))
            for entry in checksums:
                digest, name = entry.split('  ')
                self.assertEqual(digest, hashlib.sha256((work / 'first' / name).read_bytes()).hexdigest())

    @unittest.skipUnless(shutil.which('dpkg-deb'), 'dpkg-deb is needed for Debian packages')
    def test_debian_metadata_paths_permissions_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            deb = build(work / 'release', formats=('deb',))['deb']
            control = subprocess.check_output(['dpkg-deb', '--field', str(deb)]).decode()
            for expected in ('Architecture: all', 'Depends: python3 (>= 3.10), python3-gi, gir1.2-glib-2.0, gir1.2-gdkpixbuf-2.0',
                             f'Package: {PACKAGE_NAME}', f"Maintainer: {release_metadata()[0]['maintainer']}"):
                self.assertIn(expected, control)
            root = work / 'root'
            subprocess.run(['dpkg-deb', '--raw-extract', str(deb), str(root)], check=True)
            self.assertEqual({path.name for path in (root / 'DEBIAN').iterdir()}, {'control', 'md5sums', 'postinst', 'prerm'})
            for script in ('postinst', 'prerm'):
                self.assertEqual((root / 'DEBIAN' / script).stat().st_mode & 0o777, 0o755)
            subprocess.run(['/bin/sh', str(root / 'DEBIAN/postinst'), 'configure'],
                           env={**os.environ, 'DPKG_ROOT': str(root)}, check=True, stdout=subprocess.DEVNULL)
            manifest = json.loads((root / SYSTEM_MANIFEST.relative_to('/')).read_text())
            self.assertEqual(manifest['path'], str(SYSTEM_HELPER))
            self.assertEqual(manifest['name'], HOST_NAME)
            self.assertEqual(manifest['allowed_extensions'], [EXTENSION_ID])
            self.assertTrue((root / SYSTEM_HELPER.relative_to('/')).stat().st_mode & 0o111)
            cli = root / 'usr/bin' / f'{PACKAGE_NAME}-doctor'
            self.assertTrue(cli.is_symlink())
            self.assertTrue(cli.resolve().is_file())
            self.assertIn(str(root), str(cli.resolve()))
            subprocess.run([str(cli), '--system-root', str(root), '--user-home', str(work / 'user'), '--installation-only'],
                           check=True, stdout=subprocess.DEVNULL)
            for line in (root / 'DEBIAN/md5sums').read_text().splitlines():
                digest, name = line.split('  ')
                self.assertEqual(digest, hashlib.md5((root / name).read_bytes(), usedforsecurity=False).hexdigest())
            data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(deb)])
            import io
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                self.assertTrue(all(member.uid == 0 and member.gid == 0 for member in archive))
            self.assertFalse(list(root.rglob('__pycache__')))
            self.assertFalse((root / 'home').exists())
            subprocess.run(['/bin/sh', str(root / 'DEBIAN/prerm'), 'remove'],
                           env={**os.environ, 'DPKG_ROOT': str(root)}, check=True, stdout=subprocess.DEVNULL)
            self.assertFalse((root / 'etc/thunderbird/policies/policies.json').exists())

    def test_metadata_injection_is_rejected(self):
        for arguments in ({'maintainer': 'Name <user@example.invalid>\nDepends: injected'},
                          {'homepage': 'https://example.invalid/\nConflicts: injected'},
                          {'revision': '../bad'}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                release_metadata(**arguments)

    def test_source_date_epoch_applies_to_archives(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SOURCE_DATE_EPOCH': '1704067200'}):
            artifacts = build(Path(directory), formats=('xpi', 'tar'))
            with zipfile.ZipFile(artifacts['xpi']) as archive:
                self.assertTrue(all(info.date_time == (2024, 1, 1, 0, 0, 0) for info in archive.infolist()))
            with tarfile.open(artifacts['tar']) as archive:
                self.assertTrue(all(member.mtime == 1704067200 for member in archive))
