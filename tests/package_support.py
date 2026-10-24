"""Install a release into a disposable directory for integration tests."""

import json
import os
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build import build
from integration import PACKAGE_NAME, HOST_NAME, SYSTEM_HELPER, SYSTEM_MANIFEST, validate_manifest, locations
from policy import check_policy, EXTENSION_ID, SYSTEM_XPI, policy_entry


def extract_tar(artifact, destination):
    """Only accept directories and regular files under one top-level directory."""
    with tarfile.open(artifact) as archive:
        members = archive.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsafe runtime archive member: {member.name}')
        roots = {PurePosixPath(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError('Runtime archive must contain one top-level directory')
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
                target.chmod(member.mode & 0o777)
    return destination / roots.pop()


def prepare_package(work, artifact=None):
    if artifact is None:
        artifact = build(work / 'release', formats=('deb',))['deb']
    artifact = Path(artifact).resolve()
    user_home = work / 'user'
    user_home.mkdir()
    if artifact.suffix == '.deb':
        root = work / 'system'
        subprocess.run(['dpkg-deb', '--raw-extract', str(artifact), str(root)], check=True)
        subprocess.run(['/bin/sh', str(root / 'DEBIAN/postinst'), 'configure'],
                       env={**os.environ, 'DPKG_ROOT': str(root)}, check=True, stdout=subprocess.DEVNULL)
        manifest = json.loads((root / SYSTEM_MANIFEST.relative_to('/')).read_text())
        validate_manifest(manifest, SYSTEM_HELPER)
        executable = root / SYSTEM_HELPER.relative_to('/')
        # Native manifests require absolute paths. Relocate ONLY this test copy;
        # helper code, installed permissions, and XPI remain exactly as packaged.
        manifest['path'] = str(executable)
        _, manifest_path = locations(user_home)
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(manifest))
        xpi = root / 'usr/share' / PACKAGE_NAME / f'{PACKAGE_NAME}.xpi'
    elif artifact.name.endswith('-linux.tar.gz'):
        bundle = extract_tar(artifact, work / 'extracted')
        subprocess.run([str(bundle / 'install.sh'), '--user-home', str(user_home)], check=True, stdout=subprocess.DEVNULL)
        _, manifest_path = locations(user_home)
        xpis = list(bundle.glob('*.xpi'))
        if len(xpis) != 1:
            raise ValueError('Runtime archive must contain one XPI')
        xpi = xpis[0]
    else:
        raise ValueError('Use a release .deb or -linux.tar.gz')
    if not xpi.is_file():
        raise ValueError('The release does not contain its XPI')
    return manifest_path, xpi, artifact


def prepare_policy(work, xpi):
    """Relocate only the generated package policy's absolute local XPI URL."""
    document = json.loads(check_policy(work / 'system').read_text())
    entry = document['policies']['ExtensionSettings'][EXTENSION_ID]
    assert entry == policy_entry()
    assert entry['install_url'] == SYSTEM_XPI.as_uri()
    entry['install_url'] = xpi.as_uri()
    target = work / 'test-policies.json'
    target.write_text(json.dumps(document))
    return target


def policy_test_command(work, target, manifest):
    """Use an isolated application directory with the unmodified system binary.

    This exercises the normal production policy loader, without automation-only
    policy overrides or security preference changes. Shared libraries/resources
    remain symlinks to the system installation; the executable is a byte copy.
    """
    if not shutil.which('bwrap'):
        raise RuntimeError('Desktop integration tests require bubblewrap (bwrap) for policy/native-host isolation')
    source = Path('/usr/lib/thunderbird')
    runtime = work / 'thunderbird-runtime'
    runtime.mkdir()
    binary = runtime / 'thunderbird-bin'
    shutil.copy2(source / 'thunderbird-bin', binary)
    for resource in source.iterdir():
        if resource.name not in ('thunderbird-bin', 'thunderbird', 'distribution'):
            (runtime / resource.name).symlink_to(resource)
    (runtime / 'distribution').mkdir()
    (runtime / 'distribution/policies.json').symlink_to(target)
    user_mozilla = Path.home() / '.mozilla'
    return ['bwrap', '--die-with-parent', '--unshare-pid', '--ro-bind', '/', '/', '--proc', '/proc',
            '--dev', '/dev', '--tmpfs', '/dev/shm',
            '--bind', '/tmp', '/tmp', '--bind', str(work), str(work),
            '--tmpfs', '/etc/thunderbird/policies',
            '--ro-bind', str(target), '/etc/thunderbird/policies/policies.json',
            '--tmpfs', str(SYSTEM_MANIFEST.parent), '--ro-bind', str(manifest), str(SYSTEM_MANIFEST),
            '--tmpfs', str(user_mozilla), '--dir', str(user_mozilla / 'native-messaging-hosts'),
            '--ro-bind', str(manifest), str(user_mozilla / 'native-messaging-hosts' / manifest.name),
            '--', str(binary)]
