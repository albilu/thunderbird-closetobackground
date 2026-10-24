#!/usr/bin/python3
"""Manage only this package's Thunderbird policy, without opening user profiles."""

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

sys.dont_write_bytecode = True
from integration import EXTENSION_ID, PACKAGE_NAME, SYSTEM_XPI

SYSTEM_POLICY = Path('/etc/thunderbird/policies/policies.json')
DISTRIBUTION_POLICY = Path('/usr/lib/thunderbird/distribution/policies.json')
STATE_FILE = Path('/var/lib') / PACKAGE_NAME / 'policy-state.json'
MISSING = object()


def rooted(root, absolute):
    """Follow administrator symlinks, but never escape an isolated install root."""
    absolute = Path(absolute)
    if not absolute.is_absolute() or '..' in absolute.parts:
        raise ValueError(f'Expected an absolute system path: {absolute}')
    target = (root / absolute.relative_to('/')).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f'Path escapes installation root: {absolute}')
    return target


def policy_entry():
    return {'installation_mode': 'normal_installed', 'install_url': SYSTEM_XPI.as_uri(),
            'updates_disabled': True}


def decode_policy(data):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate policy key: {key}')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f'Invalid JSON constant: {value}')

    document = json.loads(data, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)
    if not isinstance(document, dict) or not isinstance(document.get('policies', {}), dict):
        raise ValueError('The Thunderbird policy must contain a policies object')
    if not isinstance(document.get('policies', {}).get('ExtensionSettings', {}), dict):
        raise ValueError('ExtensionSettings must be an object')
    return document


def entry_from(document):
    return document.get('policies', {}).get('ExtensionSettings', {}).get(EXTENSION_ID, MISSING)


def check_legacy_conflicts(document):
    legacy = document.get('policies', {}).get('Extensions', {})
    if isinstance(legacy, dict) and any(EXTENSION_ID in legacy.get(key, []) for key in ('Uninstall', 'Locked')):
        raise ValueError('An existing Extensions policy uninstalls or locks this add-on')


def read_optional(target):
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None


def encode(document):
    return (json.dumps(document, indent=2, ensure_ascii=False) + '\n').encode()


def atomic_write(target, data, mode=0o644):
    target.parent.mkdir(parents=True, exist_ok=True)
    original = target.stat() if target.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{target.name}.', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            if original:
                os.fchown(output.fileno(), original.st_uid, original.st_gid)
            os.fchmod(output.fileno(), stat.S_IMODE(original.st_mode) if original else mode)
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def selected_policy(root):
    # Match Thunderbird's precedence. Do not create /etc policies that would
    # silently shadow a pre-existing distribution policy on Debian/Ubuntu.
    system = rooted(root, SYSTEM_POLICY)
    if system.exists():
        return system
    distribution = rooted(root, DISTRIBUTION_POLICY)
    return distribution if distribution.exists() else system


def load_state(root):
    data = read_optional(rooted(root, STATE_FILE))
    if data is None:
        return None
    state = json.loads(data)
    if state.get('version') != 1:
        raise ValueError('Unrecognized saved policy state; refusing to overwrite it')
    return state


def configure(root=Path('/')):
    root = root.resolve()
    if not rooted(root, SYSTEM_XPI).is_file():
        raise ValueError(f'Bundled add-on is missing: {SYSTEM_XPI}')
    state = load_state(root)
    target = selected_policy(root)
    original = read_optional(target)
    document = decode_policy(original) if original is not None else {}
    check_legacy_conflicts(document)
    current = entry_from(document)
    wanted = policy_entry()
    if state:
        if target != rooted(root, state['path']):
            raise ValueError('The active Thunderbird policy location changed; restore the previous policy before reconfiguring')
        saved = decode_policy(base64.b64decode(state['original'])) if state['original'] is not None else {}
        if current not in (state['installed'], entry_from(saved)):
            raise ValueError('An administrator changed this add-on\'s policy; refusing to replace it')
        state['installed'] = wanted
    else:
        if EXTENSION_ID in document.get('policies', {}).get('ExtensionSettings', {}):
            raise ValueError('An existing policy already manages this add-on; refusing to replace it')
        created = []
        parent = target.parent
        while not parent.exists():
            created.append('/' + str(parent.relative_to(root)))
            parent = parent.parent
        state = {'version': 1, 'path': '/' + str(target.relative_to(root)),
                 'original': base64.b64encode(original).decode() if original is not None else None,
                 'installed': wanted, 'created_directories': created}
    document.setdefault('policies', {}).setdefault('ExtensionSettings', {})[EXTENSION_ID] = wanted
    # Save recovery information first. Interrupted configuration can be retried
    # or removed whether or not the subsequent policy replacement completed.
    state_file = rooted(root, STATE_FILE)
    state_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    atomic_write(state_file, encode(state), 0o600)
    if read_optional(target) != original:
        raise ValueError('The policy changed during configuration; retry after the other edit finishes')
    if current != wanted:
        atomic_write(target, encode(document))
    return target


def remove(root=Path('/')):
    root = root.resolve()
    state = load_state(root)
    if state is None:
        return None
    target = rooted(root, state['path'])
    current_bytes = read_optional(target)
    original_bytes = base64.b64decode(state['original']) if state['original'] is not None else None
    original = decode_policy(original_bytes) if original_bytes is not None else {}
    if current_bytes is not None:
        document = decode_policy(current_bytes)
        if entry_from(document) == state['installed']:
            document = copy.deepcopy(document)
            settings = document['policies']['ExtensionSettings']
            settings.pop(EXTENSION_ID)
            if not settings and 'ExtensionSettings' not in original.get('policies', {}):
                document['policies'].pop('ExtensionSettings')
            if not document['policies'] and 'policies' not in original:
                document.pop('policies')
            if read_optional(target) != current_bytes:
                raise ValueError('The policy changed during removal; retry after the other edit finishes')
            if document == original:
                if original_bytes is None:
                    target.unlink()
                else:
                    atomic_write(target, original_bytes)
            else:
                atomic_write(target, encode(document))
        elif entry_from(document) != entry_from(original):
            print(f'Keeping administrator-modified add-on policy in {target}', file=sys.stderr)
    state_file = rooted(root, STATE_FILE)
    state_file.unlink()
    for directory in [*state['created_directories'], '/' + str(state_file.parent.relative_to(root))]:
        try:
            rooted(root, directory).rmdir()
        except OSError:
            pass  # Retain directories containing unrelated/admin-created files.
    return target


def check_policy(root=Path('/')):
    root = root.resolve()
    target = selected_policy(root)
    if not target.exists():
        raise ValueError('Automatic add-on policy is not configured; run sudo dpkg-reconfigure ' + PACKAGE_NAME)
    # Diagnostics run as an ordinary user. The root-only recovery backup is not
    # needed to verify the effective policy Thunderbird itself will read.
    document = decode_policy(target.read_bytes())
    check_legacy_conflicts(document)
    if entry_from(document) != policy_entry():
        raise ValueError('Automatic add-on policy is missing, overridden, or changed by an administrator')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('configure', 'remove'))
    parser.add_argument('--system-root', type=Path, default=Path(os.environ.get('DPKG_ROOT') or '/'))
    args = parser.parse_args()
    try:
        target = configure(args.system_root) if args.action == 'configure' else remove(args.system_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'Thunderbird policy: {error}\n')
    if target:
        print(f'Thunderbird policy {args.action}: {target}')
    if args.action == 'configure':
        print('Restart Thunderbird to install/update Close to Background automatically.')


if __name__ == '__main__':
    main()
