#!/usr/bin/env python3
"""Install/remove the per-user Linux native-messaging helper. No sudo needed."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
from integration import HOST_NAME, EXTENSION_ID, APP_DIRECTORY, NATIVE_FILES, locations, host_manifest, validate_manifest

FILES = NATIVE_FILES
ROOT = Path(__file__).resolve().parents[1]


def atomic_write(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.flush()
            os.fchmod(temporary.fileno(), mode)
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def install(user_home):
    target, manifest_path = locations(user_home)
    manifest = host_manifest(target / "host.py")
    # Validate all inputs before writing anything.
    contents = {name: (ROOT / "native" / name).read_bytes() for name in FILES}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        validate_manifest(existing, target / "host.py")
    for name, data in contents.items():
        atomic_write(target / name, data, 0o755 if name == "host.py" else 0o644)
    atomic_write(manifest_path, (json.dumps(manifest, indent=2) + "\n").encode())
    return target, manifest_path


def uninstall(user_home):
    target, manifest_path = locations(user_home)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        validate_manifest(manifest, target / "host.py")
        manifest_path.unlink()
    for name in FILES:
        (target / name).unlink(missing_ok=True)
    # Only remove our own bytecode; never recursively delete a shared/user directory.
    cache = target / "__pycache__"
    if cache.is_dir():
        for name in FILES:
            if name.endswith(".py"):
                for bytecode in cache.glob(f"{Path(name).stem}.cpython-*.pyc"):
                    bytecode.unlink()
        try:
            cache.rmdir()
        except OSError:
            pass
    try:
        target.rmdir()
    except OSError:
        pass
    return target, manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true", help="Remove this helper, preserving unrelated files")
    parser.add_argument("--user-home", type=Path, default=Path.home(), help="Target user directory (default: current user)")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This helper supports Linux only.")
    if os.geteuid() == 0 and args.user_home == Path.home():
        parser.error("Run this per-user installer without sudo. For a system installation, use the .deb package.")
    try:
        target, manifest_path = (uninstall if args.uninstall else install)(args.user_home)
    except (OSError, ValueError) as error:
        print(f"Installation error: {error}", file=sys.stderr)
        return 1
    print(f"{'Removed' if args.uninstall else 'Installed'} tray helper: {target}")
    print(f"Native manifest: {manifest_path}")
    if not args.uninstall:
        print("Next: install the XPI in Thunderbird, enable GNOME AppIndicator support, and open the add-on settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
