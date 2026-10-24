import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from doctor import check_installation
from integration import SYSTEM_HELPER, SYSTEM_MANIFEST, SYSTEM_XPI, NATIVE_FILES, host_manifest, locations
from policy import configure
from install import install


class DoctorTests(unittest.TestCase):
    def test_system_install_and_broken_user_override(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            home, root = work / 'user', work / 'system'
            target = root / SYSTEM_HELPER.relative_to('/')
            target.parent.mkdir(parents=True)
            for name in NATIVE_FILES:
                shutil.copyfile(ROOT / 'native' / name, target.parent / name)
            target.chmod(0o755)
            manifest_path = root / SYSTEM_MANIFEST.relative_to('/')
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(json.dumps(host_manifest(SYSTEM_HELPER)))
            xpi = root / SYSTEM_XPI.relative_to('/')
            xpi.write_bytes(b'test payload')
            self.assertTrue(check_installation(home, root)[1])
            configure(root)
            self.assertEqual(check_installation(home, root)[1], [])
            _, user_manifest = locations(home)
            user_manifest.parent.mkdir(parents=True)
            user_manifest.write_text('{bad json')
            messages, failures = check_installation(home, root)
            self.assertTrue(any('overrides' in message for message in messages))
            self.assertTrue(failures)

    def test_per_user_install_and_missing_module(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'user'
            target, _ = install(home)
            self.assertEqual(check_installation(home, Path(directory) / 'empty-system')[1], [])
            (target / 'tray.py').unlink()
            self.assertTrue(check_installation(home, Path(directory) / 'empty-system')[1])
