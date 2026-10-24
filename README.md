# thunderbird-closetobackground

Keep Thunderbird running in the Linux system tray. Close or minimize the main
mail window, restore it from the tray, see an unread badge, and receive new-mail
notifications. Enable or disable everything from the add-on settings or tray menu.

This is a Thunderbird MailExtension plus a small local Python helper. It does
not patch your Thunderbird installation. All communication stays on your machine.

## Requirements

- **Linux**, with a desktop session bus. GNOME is the primary target.
- **Thunderbird 128–153**, installed as a native distro package or Mozilla tarball.
  The privileged window API is version-sensitive, so the manifest bounds this
  range. New major versions need a compatibility check before raising that bound.
- **Python 3.10+**, PyGObject, and GLib/Gio/GdkPixbuf introspection. No pip or npm runtime dependencies.
- A StatusNotifier/AppIndicator tray host. On GNOME, install and enable
  [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/).
  GNOME does not provide this tray protocol by default.

**Flatpak and Snap Thunderbird are not supported by this installer.** Their
sandboxes do not necessarily expose host executables, native-messaging manifests,
or the session bus. Use a native Thunderbird package for this version.

## Install a release

Release **0.1.4** provides a Debian package, a small runtime tarball, a separate
source archive, and the XPI, with `SHA256SUMS` in `dist/0.1.4/`. See the full
[packaging guide](docs/packaging.md) for file layouts, upgrades, migration, and
reproducible builds.

### Debian/Ubuntu

```sh
sudo apt install ./dist/0.1.4/thunderbird-closetobackground_0.1.4-1_all.deb
sudo apt install gnome-shell-extension-appindicator
thunderbird-closetobackground-doctor
```

Enable AppIndicator in GNOME Extensions, then **start or restart Thunderbird**.
The bundled add-on installs automatically; there is no manual XPI installation.
After package upgrades, restart Thunderbird to apply the updated add-on.

The package installs its dependencies and the native helper system-wide. It adds
only this add-on's entry to Thunderbird's policies, preserving other settings.
Users can disable the add-on; its installation and updates are managed by the
package. The scripts never edit user profiles or GNOME settings. Existing per-user
helper installations override it; remove those first using the tarball's uninstaller.

### Portable Linux tarball

On Debian/Ubuntu, install the desktop dependencies:

```sh
sudo apt install python3 python3-gi gir1.2-glib-2.0 gir1.2-gdkpixbuf-2.0 gnome-shell-extension-appindicator
```

On Fedora:

```sh
sudo dnf install python3 python3-gobject glib2 gdk-pixbuf2 gnome-shell-extension-appindicator
```

Enable **AppIndicator and KStatusNotifierItem Support** in GNOME’s Extensions
application. A logout/login may be needed after installing a Shell extension.
Ubuntu’s already-enabled AppIndicators extension also supplies this service.

Extract `thunderbird-closetobackground-0.1.4-linux.tar.gz`, enter the extracted
directory, and run:

```sh
./install.sh
```

The XPI is already included. The installer does not need root and does not modify
Thunderbird profiles. It copies the helper to
`~/.local/share/thunderbird-close-to-background/` and registers
`~/.mozilla/native-messaging-hosts/net.thunderbird.closetobackground.json`.
It is safe to run again to update the helper.

In Thunderbird, open **Add-ons and Themes → gear menu → Install Add-on From File**
and select `thunderbird-closetobackground-0.1.4.xpi` at the top level of the
extracted bundle. Review the access prompt, then open the add-on’s
preferences from Add-ons and Themes or the tray's **Settings…** menu.
**Your tray is ready** confirms the full connection.

From a source checkout, run `python3 scripts/build.py` to create all releases in
`dist/0.1.4/`. This requires Python and `dpkg-deb`; no Node or downloads are needed.
`python3 scripts/install.py` remains available for per-user source development.

The add-on uses a small [Experiment API](https://developer.thunderbird.net/add-ons/mailextensions/experiments)
because the standard windows API cannot hide a native window or intercept its
close button. It needs full, unrestricted access. Manual XPI installation shows
Thunderbird's permission prompt; installing the Debian package authorizes the
same access through its automatic installation policy. The
native helper is restricted to this add-on’s ID. It does not read mail or execute
shell commands; it receives a count/settings and sends fixed tray actions.

## Use

- **Close to tray** and **Minimize to tray** independently control main mail windows.
  New windows are handled too. Message viewers, compose windows, and dialogs are
  not intercepted.
- The tray uses Thunderbird's installed application icon with an unread badge.
  Settings are available from its **Settings…** menu or Add-ons and Themes;
  the add-on does not add a settings button to Thunderbird's toolbar.
- Restore from **Show Thunderbird** in the tray menu. Direct activation also
  restores windows. GNOME commonly opens a menu on single-click and activates on
  double-click or middle-click; exact gestures depend on the tray extension.
- Clicking Thunderbird's desktop/Dash launcher or launching Thunderbird again
  restores its existing hidden mail window. When already visible, normal desktop
  focus/minimize behavior is retained; the add-on does not toggle it into the tray.
- The badge sums unread mail across physical folders/accounts, excluding Junk,
  Trash, Sent, Drafts, Templates, Outbox, their descendants, and virtual/unified/tag
  views. It displays up to **99+**; the tray title/settings retain the full count.
  Counts follow Thunderbird’s locally synchronized folder data.
- New-mail events are grouped into generic notifications; no subject, sender,
  body, or account name is sent to the helper. Clicking a notification restores
  Thunderbird. The add-on does not notify about old unread mail on startup.
- For one notification per arrival, disable Thunderbird’s own incoming-mail
  **Show an alert** preference. The add-on leaves that preference unchanged.
- Turning **Enable Close to Background** off restores hidden windows and turns
  off interception, badges, and this add-on’s notifications. The tray remains
  available to re-enable it. Preferences are saved automatically per profile.
- **Quit Thunderbird** in the tray, Thunderbird’s **Quit** menu, or **Ctrl+Q**
  exits normally and respects unsaved-compose prompts. Closing a main window
  while background mode is active keeps mail checking alive.

If the helper is missing, its protocol is incompatible, or the tray disappears,
window hiding is disabled and hidden windows are restored. A dead connection is
detected immediately; an unresponsive helper is detected by heartbeat within
about 40 seconds. The helper reconnects automatically with bounded backoff.

On Wayland, window hiding is performed inside Thunderbird, without `wmctrl`,
`xdotool`, or X11 window IDs. The compositor still controls focus stealing:
restoring a window may require an additional click to focus it.
Wayland does not report compositor-initiated minimization to Thunderbird.
Thunderbird’s own minimize button is intercepted directly; desktop-level minimize
shortcuts or the compositor’s window menu may minimize normally. Close to tray
and the explicit **Send to tray** action remain available in either case.

## Troubleshooting

```sh
thunderbird-closetobackground-doctor  # Debian package
/usr/bin/python3 scripts/doctor.py   # Extracted tarball / source
```

- **No native application / helper missing:** rerun the installer as the same
  user who runs Thunderbird, then choose **Reconnect helper** in preferences.
- **No system tray:** enable the GNOME AppIndicator extension. The helper only
  reports ready after a tray host is present and registration succeeds.
- **PyGObject missing:** install the distribution packages above. The helper uses
  `/usr/bin/python3` so a virtual environment does not hide distro GI bindings.
- **Partial unread count:** a folder is unavailable or was moved during a scan.
  It is retried on folder events and every minute. Settings show the partial state.
- **No notification:** check both the add-on setting and desktop Do Not Disturb
  / notification permissions. Use **Test notification** in preferences.
- **Further diagnostics:** Thunderbird’s **Tools → Developer Tools → Error
  Console** includes helper stderr and add-on errors. Stdout is reserved for the
  native messaging protocol. Do not run the helper directly in a terminal.

To remove it, use the matching installation method:

```sh
sudo apt remove thunderbird-closetobackground  # Debian package
./uninstall.sh                               # Extracted runtime tarball
python3 scripts/install.py --uninstall       # Source checkout
```

After Debian removal, restart Thunderbird; the remaining profile copy becomes
removable in Add-ons and Themes. The package restores its policy change and never
deletes profile files. For tar/source installations, disable/remove the add-on
before uninstalling its helper. The uninstaller removes only this helper's known
files and registration. Thunderbird manages stored preferences separately.

## Development & verification

Python builds the XPI, runtime/source archives, Debian package, and checksums
without fetching dependencies:

```sh
python3 scripts/build.py
npm test
npm run test:dbus
npm run test:packages
npm run test:policies
```

Desktop integration tests (additional system packages are needed):

```sh
npm run test:thunderbird  # private Xvfb/X11 display; needs xfwm4 and xdotool
npm run test:gnome -- --package dist/0.1.4/thunderbird-closetobackground_0.1.4-1_all.deb
npm run test:gnome -- --package dist/0.1.4/thunderbird-closetobackground-0.1.4-linux.tar.gz
```

Verified locally with **Thunderbird 153.4.0 ESR** on X11 and **GNOME Shell 50.4
Wayland with Ubuntu AppIndicators**, for both release packages. GNOME confirms
Thunderbird is a native Wayland client, with XWayland disabled. The test uses
synthetic local mail to check counts and notifications, and exercises native
close/minimize, restoration, tray loss, preference persistence, add-on disable,
and normal Quit. Earlier supported Thunderbird versions still need
their own desktop compatibility run.

`make build`, `make test`, and `make test-dbus` are equivalent. Node 18+ is only
needed for JavaScript tests. Package lifecycle tests need `dpkg` and `fakeroot`
and use a temporary installation root/package database. Desktop tests additionally
need `bubblewrap` to isolate policy/native-host paths from installed packages.
The D-Bus integration test needs PyGObject and
`dbus-run-session`; it starts a private bus, a test watcher, and the actual native
helper. It never connects to your real tray or uses your email accounts.

For temporary add-on development use Thunderbird’s **Debug Add-ons → Load
Temporary Add-on** and select `extension/manifest.json`. The helper must still
be installed separately.

See [design and protocol](docs/design.md) and the [manual verification checklist](docs/testing.md).
Desktop integration tests use temporary profiles and desktop settings. The
distribution-specific manual checklist still matters, particularly for unsaved
compose prompts, multiple monitors, and focus policy. Compatibility outside the
checked Thunderbird version must be verified before publishing a release.

## Source layout

| Path | Purpose |
| --- | --- |
| `extension/` | Mail events, background controller, preferences, and window experiment |
| `native/` | Framed native messaging, StatusNotifierItem, DBusMenu, and application icon/badge rendering |
| `scripts/` | Build, per-user installer, Debian policy management, and diagnostics |
| `packaging/` | Runtime bundle entry points, release metadata, and Debian definitions |
| `tests/` | JavaScript/Python tests and isolated D-Bus integration |

## References

- [Thunderbird extension development](https://developer.thunderbird.net/add-ons/mailextensions)
- [Thunderbird folder API](https://webextension-api.thunderbird.net/en/esr-mv2/folders.html)
- [Mozilla native messaging](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging)
- [Native host manifests and Linux locations](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests)
- [StatusNotifierItem specification](https://specifications.freedesktop.org/status-notifier-item/latest/status-notifier-item.html)
- [GNOME AppIndicator implementation](https://github.com/ubuntu/gnome-shell-extension-appindicator)

MIT licensed. Not affiliated with or endorsed by the Thunderbird project.
