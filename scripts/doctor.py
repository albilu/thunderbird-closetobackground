#!/usr/bin/python3
"""Read-only checks for helper installation and desktop tray availability."""

import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from integration import HOST_NAME, SYSTEM_HELPER, SYSTEM_MANIFEST, NATIVE_FILES, locations, validate_manifest


def check_installation(user_home, system_root=Path("/")):
    """Follow Thunderbird's precedence; a broken user manifest must not fall back."""
    target, user_manifest = locations(user_home)
    system_root = system_root.resolve()
    system_manifest = system_root / SYSTEM_MANIFEST.relative_to("/")
    messages, failures = [], []
    if user_manifest.exists() or user_manifest.is_symlink():
        manifest_path = user_manifest
        expected = target / "host.py"
        if system_manifest.exists():
            messages.append("A per-user helper overrides the Debian system helper. Remove the user installation to switch to the .deb.")
        resolve_path = lambda path: path
    elif system_manifest.exists():
        manifest_path = system_manifest
        expected = SYSTEM_HELPER
        resolve_path = lambda path: system_root / path.relative_to("/")
    else:
        return messages, ["No helper registered. Install the .deb or run ./install.sh from the Linux tarball."]
    try:
        manifest = json.loads(manifest_path.read_text())
        executable = resolve_path(validate_manifest(manifest, expected))
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(f"Helper is missing or not executable: {executable}")
        missing = [name for name in NATIVE_FILES if not (executable.parent / name).is_file()]
        if missing:
            raise ValueError(f"Incomplete helper installation: {', '.join(missing)}")
        messages.append(f"Helper: {executable}")
        messages.append(f"Native manifest: {manifest_path}")
        if manifest_path == system_manifest:
            from policy import check_policy
            messages.append(f"Automatic add-on installation: {check_policy(system_root)}")
            messages.append("Restart Thunderbird after package installation or upgrades; no manual XPI installation is needed.")
    except (OSError, ValueError) as error:
        failures.append(f"Invalid native registration at {manifest_path}: {error}")
    return messages, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-home", type=Path, default=Path.home())
    parser.add_argument("--system-root", type=Path, default=Path("/"), help="Root of an extracted package for staged checks")
    parser.add_argument("--installation-only", action="store_true", help="Do not contact the desktop bus")
    args = parser.parse_args()
    messages, failures = check_installation(args.user_home, args.system_root)
    print(f"Python: {sys.executable} ({sys.version.split()[0]})")
    print(f"Session: {os.environ.get('XDG_SESSION_TYPE', 'unknown')}")
    for message in messages:
        print(message)
    if args.installation_only:
        for failure in failures:
            print(f"FAIL: {failure}")
        return int(bool(failures))
    try:
        from gi.repository import Gio, GLib
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'native'))
        from icons import thunderbird_icon
        artwork = thunderbird_icon()
        print("PyGObject / GLib / GdkPixbuf: available")
        print(f"Tray artwork: {artwork[0]}" if artwork else
              "Tray artwork: using the desktop's thunderbird icon name; unread count remains in the tooltip")
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                               "org.freedesktop.DBus.Properties", "Get",
                               GLib.Variant("(ss)", ("org.kde.StatusNotifierWatcher", "IsStatusNotifierHostRegistered")),
                               GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 3000, None)
        if result.unpack()[0]:
            print("Desktop tray: available")
        else:
            failures.append("Tray watcher is running, but no panel host is registered")
    except (ImportError, ValueError):
        failures.append("Introspection missing: install python3-gi, gir1.2-glib-2.0 and gir1.2-gdkpixbuf-2.0 (Debian/Ubuntu), or python3-gobject and gdk-pixbuf2 (Fedora)")
    except Exception as error:
        failures.append(f"Desktop tray unavailable: enable GNOME AppIndicator support ({error})")
    for failure in failures:
        print(f"FAIL: {failure}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
