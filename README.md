# thunderbird-closetobackground

[![Release](https://github.com/albilu/thunderbird-closetobackground/actions/workflows/release.yml/badge.svg)](https://github.com/albilu/thunderbird-closetobackground/actions/workflows/release.yml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Thunderbird](https://img.shields.io/badge/Thunderbird-128%E2%80%93153-blue.svg)]()

**Keep Thunderbird running in the Linux system tray — close or minimize the main
mail window, restore it from the tray, and get unread badges and new-mail
notifications.**

A Thunderbird MailExtension plus a small local Python helper. It does not patch
Thunderbird, and all communication stays on your machine.

## Why?

Closing Thunderbird's main window normally exits the application, and GNOME
ships no tray protocol at all. **thunderbird-closetobackground** sends the
window to a tray icon instead: mail keeps checking, unread mail shows a badge,
and the window silently keeps running.

## Requirements

- **Linux** with a desktop session bus (GNOME is the primary target).
- **Thunderbird 128–153** as a native distro package or Mozilla tarball.
  **Flatpak/Snap Thunderbird are not supported.**
- **Python 3.10+** with PyGObject, GLib, and GdkPixbuf introspection
  (`python3-gi`, `gir1.2-glib-2.0`, `gir1.2-gdkpixbuf-2.0` on Debian/Ubuntu).
- A StatusNotifier/AppIndicator tray host; on GNOME, enable
  [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/).

## Install

Download the Debian package or the runtime tarball from the
[Releases page](https://github.com/albilu/thunderbird-closetobackground/releases).

### Debian/Ubuntu

```sh
sudo apt install ./thunderbird-closetobackground_0.1.5-1_all.deb
sudo apt install gnome-shell-extension-appindicator
thunderbird-closetobackground-doctor
```

Enable AppIndicator in GNOME Extensions, then **start or restart Thunderbird** —
the bundled add-on installs automatically. Restart Thunderbird again after a
package upgrade. Remove with `sudo apt remove thunderbird-closetobackground`.

### Portable tarball

```sh
sudo apt install python3 python3-gi gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 gnome-shell-extension-appindicator
# or: sudo dnf install python3 python3-gobject glib2 gdk-pixbuf2 gnome-shell-extension-appindicator
tar -xzf thunderbird-closetobackground-0.1.5-linux.tar.gz
cd thunderbird-closetobackground-0.1.5
./install.sh
```

Then in Thunderbird, open **Add-ons and Themes → gear menu → Install Add-on
From File** and select the included `.xpi`. Open the add-on preferences and
confirm **Your tray is ready**. The installer needs no root and touches no
profiles. Disable the add-on, then remove with `./uninstall.sh`; source
checkouts use `python3 scripts/install.py --uninstall`.

## Features

- **Close to tray and minimize to tray** for main mail windows (new windows
  too). Compose windows, message viewers, and dialogs are never intercepted.
- **Restore** from the tray menu, direct activation, or by launching
  Thunderbird again; hidden windows keep size, position, and maximized state.
- **Unread badge** summed across folders — Junk, Trash, Sent, Drafts, and
  similar are excluded — shown up to **99+** on Thunderbird's real icon.
- **Optional grouped new-mail notifications**, off by default, with Thunderbird's
  original icon and generic text. Senders, subjects, and account names never leave
  Thunderbird. Clicking restores the window. Existing saved preferences are kept.
- **Settings** in the tray's **Settings…** menu or add-on preferences, saved
  per profile. Turning the feature off restores hidden windows immediately.
- **Wayland-native**: hiding happens inside Thunderbird, without `wmctrl`,
  `xdotool`, or X11 window IDs.

Fail-safe by design: if the helper dies (immediately via EOF, within about
40 seconds without a heartbeat), the tray disappears, or the add-on is
disabled, hidden windows are restored. **Quit** (tray or Ctrl+Q) always uses
Thunderbird's normal shutdown path.

## Troubleshooting

```sh
thunderbird-closetobackground-doctor  # Debian package
/usr/bin/python3 scripts/doctor.py    # Extracted tarball / source checkout
```

- **Helper missing:** rerun the installer as the user who runs Thunderbird,
  then choose **Reconnect helper** in preferences.
- **No tray icon:** enable the GNOME AppIndicator extension; the helper only
  reports ready once a live tray host accepts registration.
- **Partial unread count or missing notification:** unavailable folders are
  retried periodically; also check desktop Do Not Disturb.
- **Deeper diagnostics:** Thunderbird's Error Console shows helper stderr.
  Never run the helper directly in a terminal — stdout is reserved for the
  native-messaging protocol.

## Development

All commands run offline; nothing is fetched from npm or pip (Node 18+ is only
needed for the JS tests):

```sh
python3 scripts/build.py          # XPI, tarballs, and .deb into dist/<version>/
npm test                          # JS + Python unit tests
npm run test:dbus                 # helper on a private D-Bus session
npm run test:packages             # .deb lifecycle in a private dpkg root
npm run test:policies             # policy handling with real Thunderbird restarts
npm run test:thunderbird          # X11 desktop test (Xvfb, xfwm4, xdotool)
npm run test:gnome -- --package dist/0.1.5/thunderbird-closetobackground_0.1.5-1_all.deb   # headless GNOME Wayland
```

Desktop behavior ultimately needs the manual checklist in
[docs/testing.md](docs/testing.md); passing automated tests alone does not
clear a release. Verified baseline: Thunderbird **153.4.0 ESR** on X11 and
**GNOME Shell 50.4** Wayland. GitHub Actions publishes tagged releases
(`v*`) from `.github/workflows/release.yml`.

More details: [design and protocol](docs/design.md),
[packaging](docs/packaging.md), [Wayland behavior](docs/wayland.md). For
temporary add-on development, use **Debug Add-ons → Load Temporary Add-on**
with `extension/manifest.json`; the helper must be installed separately.

## Keywords

Thunderbird system tray, Thunderbird close to tray, Thunderbird minimize to
tray, Thunderbird tray icon, Thunderbird close button, Thunderbird unread
badge, Thunderbird new-mail notifications, GNOME tray icon, StatusNotifierItem,
AppIndicator, DBusMenu, DBus, Wayland, native messaging, Linux mail client,
background mode.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with or endorsed by the
Thunderbird project.
