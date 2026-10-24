import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import policy
from integration import EXTENSION_ID, SYSTEM_XPI


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.xpi = self.root / SYSTEM_XPI.relative_to('/')
        self.xpi.parent.mkdir(parents=True)
        self.xpi.write_bytes(b'test payload')
        self.target = self.root / policy.SYSTEM_POLICY.relative_to('/')

    def write_policy(self, content):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_text(content)

    def test_install_reconfigure_upgrade_and_remove(self):
        policy.configure(self.root)
        first = self.target.read_bytes()
        self.assertEqual(policy.check_policy(self.root), self.target)
        self.assertEqual(json.loads(first)['policies']['ExtensionSettings'][EXTENSION_ID], policy.policy_entry())
        self.xpi.write_bytes(b'newer bundled version')
        policy.configure(self.root)
        self.assertEqual(first, self.target.read_bytes())
        policy.remove(self.root)
        policy.remove(self.root)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.root / policy.STATE_FILE.relative_to('/')).exists())
        self.assertFalse(self.target.parent.exists())

    def test_restore_existing_bytes_permissions_and_symlink(self):
        original = '{"policies":{"DisableTelemetry":true, "ExtensionSettings":{"other@local":{"installation_mode":"allowed"}}}}\n'
        real = self.root / 'etc/shared/settings.json'
        real.parent.mkdir(parents=True)
        real.write_text(original)
        real.chmod(0o640)
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to('../../shared/settings.json')
        policy.configure(self.root)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o640)
        document = json.loads(real.read_text())
        self.assertTrue(document['policies']['DisableTelemetry'])
        self.assertIn('other@local', document['policies']['ExtensionSettings'])
        policy.remove(self.root)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(real.read_text(), original)
        self.assertEqual(real.stat().st_mode & 0o777, 0o640)

    def test_keep_later_admin_edits_and_unrelated_files(self):
        self.write_policy('{"policies": {"DisableTelemetry": true}}')
        policy.configure(self.root)
        document = json.loads(self.target.read_text())
        document['policies']['ExtensionSettings']['other@local'] = {'installation_mode': 'allowed'}
        document['policies']['DisableAppUpdate'] = True
        self.target.write_text(json.dumps(document))
        policy.configure(self.root)
        policy.remove(self.root)
        del document['policies']['ExtensionSettings'][EXTENSION_ID]
        self.assertEqual(json.loads(self.target.read_text()), document)

    def test_conflicting_or_invalid_policy_never_changes(self):
        cases = ['{invalid', '[]', '{"policies":null}', '{"policies":{"ExtensionSettings":[]}}',
                 '{"policies":{"test":NaN}}',
                 '{"policies":{},"policies":{"DisableTelemetry":true}}',
                 json.dumps({'policies': {'ExtensionSettings': {EXTENSION_ID: {'installation_mode': 'blocked'}}}}),
                 json.dumps({'policies': {'Extensions': {'Locked': [EXTENSION_ID]}}})]
        for original in cases:
            with self.subTest(original=original):
                self.write_policy(original)
                with self.assertRaises(ValueError):
                    policy.configure(self.root)
                self.assertEqual(self.target.read_text(), original)
                self.assertFalse((self.root / policy.STATE_FILE.relative_to('/')).exists())

    def test_use_distribution_policy_without_shadowing_it(self):
        distribution = self.root / policy.DISTRIBUTION_POLICY.relative_to('/')
        distribution.parent.mkdir(parents=True)
        original = '{"policies":{"DisableTelemetry":true}}'
        distribution.write_text(original)
        self.assertEqual(policy.configure(self.root), distribution)
        self.assertFalse(self.target.exists())
        self.assertEqual(policy.check_policy(self.root), distribution)
        policy.remove(self.root)
        self.assertEqual(distribution.read_text(), original)

    def test_system_policy_has_precedence_and_new_override_is_detected(self):
        distribution = self.root / policy.DISTRIBUTION_POLICY.relative_to('/')
        distribution.parent.mkdir(parents=True)
        original = '{"policies":{"DisableTelemetry":true}}'
        distribution.write_text(original)
        policy.configure(self.root)
        self.write_policy('{"policies":{"DisableAppUpdate":true}}')
        with self.assertRaises(ValueError):
            policy.configure(self.root)
        with self.assertRaises(ValueError):
            policy.check_policy(self.root)
        policy.remove(self.root)
        self.assertEqual(distribution.read_text(), original)
        self.assertEqual(policy.configure(self.root), self.target)
        self.assertEqual(distribution.read_text(), original)

    def test_admin_changed_entry_is_not_clobbered(self):
        policy.configure(self.root)
        document = json.loads(self.target.read_text())
        document['policies']['ExtensionSettings'][EXTENSION_ID] = {'installation_mode': 'allowed'}
        self.target.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            policy.configure(self.root)
        policy.remove(self.root)
        self.assertEqual(json.loads(self.target.read_text()), document)

    def test_failed_write_can_be_retried_or_removed(self):
        self.write_policy('{"policies":{"DisableTelemetry":true}}')
        original = self.target.read_bytes()
        writer = policy.atomic_write

        def fail_policy(target, data, mode=0o644):
            if target == self.target:
                raise OSError('Simulated failure writing policy')
            writer(target, data, mode)

        with patch.object(policy, 'atomic_write', fail_policy), self.assertRaises(OSError):
            policy.configure(self.root)
        self.assertEqual(self.target.read_bytes(), original)
        policy.configure(self.root)
        policy.remove(self.root)
        self.assertEqual(self.target.read_bytes(), original)

    def test_isolated_root_rejects_outside_symlinks(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to('/tmp/outside-thunderbird-policy-test.json')
        with self.assertRaises(ValueError):
            policy.configure(self.root)


if __name__ == '__main__':
    unittest.main()
