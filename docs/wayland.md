# Wayland support

Close to Background runs natively on GNOME Wayland. The add-on hides and restores
Thunderbird windows inside Thunderbird; the helper uses session D-Bus for its
tray icon. No `wmctrl`, `xdotool`, X11 window ID, or XWayland process is used by
the runtime.

## Supported behavior

- Thunderbird's close button keeps the main window alive but hides it.
- Thunderbird's own minimize button sends the main window to the tray.
- The tray's Show action/direct activation restores hidden mail windows.
- The desktop/Dash launcher and a normal second Thunderbird launch restore the
  existing hidden window. Dash to Dock's **Minimize window** click action
  minimizes focused Thunderbird and restores it on the next click, including
  after restoring from the tray. An unfocused visible window is focused first.
- Unread badges, optional new-mail notifications (off by default), and
  enable/disable settings work. Notifications use Thunderbird's original icon.
- Disabling the tray extension, losing the helper, or disabling the add-on
  restores hidden windows instead of leaving Thunderbird inaccessible.
- Normal Quit exits Thunderbird and its helper.

GNOME still needs an enabled AppIndicator/StatusNotifier tray extension. A native
Debian/Mozilla Thunderbird installation is required; packaging does not bypass
Snap or Flatpak sandbox restrictions.

## Desktop minimize shortcuts and focus

The Wayland compositor does not report its own minimized state to the client.
Consequently, a GNOME desktop shortcut or compositor window-menu Minimize may
minimize normally. Thunderbird's button is intercepted before it reaches GTK.
Use that button, Close to tray, or Send to tray when you want background mode.
Dash to Dock's minimize click also uses the compositor: it keeps Thunderbird in
the dock, and another click restores it. The add-on respects the dock's configured
click action and does not change desktop preferences.

The compositor also controls focus. A restored window may need an extra click
to receive keyboard focus. Restoration does not bypass Wayland focus policy.

## Verification

The integration test requires system AppIndicator and Dash to Dock extensions.
It starts GNOME Shell with `--headless --wayland --no-x11`,
removes `DISPLAY`, and starts Thunderbird with `MOZ_ENABLE_WAYLAND=1`. A
test-only Shell inspector verifies that the actual mail window is a Wayland
client and observes its visibility; environment variables alone are not accepted
as proof of the backend.

For Debian the test starts Thunderbird with the package's installation policy
and verifies that the XPI installs automatically, with disabling allowed. It
uses an isolated application directory and the unchanged system executable.
The test loads the release helper, clicks the minimize command used by
the titlebar, tests compositor close, direct tray activation, synthetic local mail,
notification creation, unread updates, preferences, tray disappearance/recovery,
add-on disable, and normal Quit. It uses temporary desktop settings, profiles,
and a private D-Bus session. No personal mail account or desktop extension is
changed.

Remoting stays enabled inside the private session: the test starts a real second
Thunderbird process against the same disposable profile. It also uses GNOME's
application activation API with a private desktop entry, checks that the existing
window returns, and waits for the launcher to leave its startup state. The
installed Dash to Dock extension's actual primary-click handler is exercised
with **Minimize window** and a focus-only setting. Checks cover compositor
minimize/restore and a tray restore followed by further minimize/restore clicks.
Neither the real desktop entry nor the user's running Thunderbird is changed.

```sh
npm run test:gnome -- --package dist/0.1.6/thunderbird-closetobackground_0.1.6-1_all.deb
```

Add `--locale fr` to verify French tray menus, options and desktop notifications.
The test overrides Thunderbird's locale only inside its disposable process.

The validated baseline is Thunderbird 153.4.0 ESR, GNOME Shell 50.4, Dash to Dock
106, and the system Ubuntu AppIndicators extension. Other supported Thunderbird
versions and desktop distributions still need the [manual release checklist](testing.md).
