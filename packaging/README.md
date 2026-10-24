# Close to Background @VERSION@

Keep Thunderbird in the Linux tray, with unread badges and new-mail notifications.
Requires native Thunderbird 128–153, Python 3.10+, PyGObject/GLib/GdkPixbuf, and a
StatusNotifier tray host. On GNOME, enable AppIndicator support. Native Wayland
and X11 are supported; Flatpak and Snap Thunderbird are not supported.

## Debian/Ubuntu package

```sh
sudo apt install ./thunderbird-closetobackground_@DEBIAN_VERSION@_all.deb
sudo apt install gnome-shell-extension-appindicator
thunderbird-closetobackground-doctor
```

Enable AppIndicator in GNOME Extensions, then **start or restart Thunderbird**.
The bundled add-on installs automatically. Restart after package upgrades to
apply its updated version. You can disable the add-on in Thunderbird; installation
is managed by the package. Installing the package authorizes the add-on's
unrestricted-access Experiment API, without a separate XPI permission prompt.

## Linux tarball

Extract the tarball and run `./install.sh` as your normal user, without sudo.
In Thunderbird, choose **Add-ons and Themes → gear → Install Add-on From File**
and select the included `thunderbird-closetobackground-@VERSION@.xpi`.
For diagnostics run `/usr/bin/python3 scripts/doctor.py`.
The helper is copied to your user data directory, so the extracted folder is not
needed at runtime. Retain or re-extract it when you need `./uninstall.sh`.

## Use and remove

Open the add-on's preferences and wait for **Your tray is ready**. Close or use
Thunderbird's minimize button to send the mail window to the tray. Restore it
with **Show Thunderbird** in the tray menu. **Quit Thunderbird** exits normally.
Clicking Thunderbird's desktop launcher or launching it again also restores the
existing hidden window. Already visible windows keep normal desktop behavior.
The tray uses Thunderbird's own installed icon, with unread badges. Access
preferences from the tray's **Settings…** menu or Thunderbird's Add-ons and Themes.

On Wayland, compositor-level minimize shortcuts may still minimize normally.
Use Thunderbird's own minimize button, close button, or **Send to tray**.

For Debian, run `sudo apt remove thunderbird-closetobackground`, then restart
Thunderbird. The package restores the policy; the remaining profile copy becomes
removable in Add-ons and Themes. Without its helper it leaves mail windows visible.
For the tarball, disable/remove the add-on and run `./uninstall.sh`; tarball upgrades
still require updating the XPI manually. A per-user installation overrides a system
installation; remove the user helper before switching from tar to Debian.

See [packaging and setup](docs/packaging.md), [Wayland support](docs/wayland.md),
and [verification](docs/testing.md). The separate source archive contains the
build tools and tests. Checksums are supplied alongside the release downloads.

MIT licensed. Not affiliated with or endorsed by the Thunderbird project.
