"""Shared installation identity and native-host manifest helpers."""

from pathlib import Path

PACKAGE_NAME = "thunderbird-closetobackground"
HOST_NAME = "net.thunderbird.closetobackground"
EXTENSION_ID = "closetobackground@thunderbird-background.local"
# Keep the original per-user location for seamless upgrades from 0.1.0.
APP_DIRECTORY = "thunderbird-close-to-background"
NATIVE_FILES = ("host.py", "protocol.py", "tray.py", "icons.py", "interfaces.xml")
SYSTEM_HELPER = Path("/usr/share") / PACKAGE_NAME / "native/host.py"
SYSTEM_MANIFEST = Path("/usr/lib/mozilla/native-messaging-hosts") / f"{HOST_NAME}.json"
SYSTEM_XPI = Path('/usr/share') / PACKAGE_NAME / f'{PACKAGE_NAME}.xpi'


def locations(user_home):
    home_path = user_home.expanduser().resolve()
    return (home_path / ".local/share" / APP_DIRECTORY,
            home_path / ".mozilla/native-messaging-hosts" / f"{HOST_NAME}.json")


def host_manifest(executable):
    return {"name": HOST_NAME, "description": "Close to Background Linux tray helper",
            "path": str(executable), "type": "stdio", "allowed_extensions": [EXTENSION_ID]}


def validate_manifest(manifest, executable=None):
    if not isinstance(manifest, dict):
        raise ValueError("Native host manifest must be a JSON object")
    if (manifest.get("name") != HOST_NAME or manifest.get("type") != "stdio" or
            manifest.get("allowed_extensions") != [EXTENSION_ID]):
        raise ValueError("Native host identity or allowed extension does not match")
    path = manifest.get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        raise ValueError("Native host executable must have an absolute path")
    if executable is not None and path != str(executable):
        raise ValueError("Native host belongs to a different installation")
    return Path(path)
