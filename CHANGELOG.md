# Changelog

## 0.1.4 — 2026-10-24

- Restore hidden mail windows when Thunderbird receives a focus request from
  a second launch or desktop launcher. Reuse the running window and preserve
  its maximized state. Already visible windows keep normal desktop behavior.
- Restore the original focus function on add-on unload and leave compose windows
  and normal application shutdown unchanged.
- Test actual second processes on X11 and Wayland, plus GNOME's Dash application
  activation and completion of the launcher's startup state.

## 0.1.3 — 2026-10-24

- Remove the settings toolbar button. Settings remain available from the tray
  menu and Thunderbird's Add-ons and Themes page.
- Use Thunderbird's installed application icon in the tray, retaining unread
  badges. Add the GdkPixbuf runtime dependency for loading the existing artwork.
- Fix Thunderbird's own titlebar close button exiting the application: intercept
  its direct window.close() command as well as window-manager close events.
  Normal Quit, disabled settings, and compose windows retain their behavior.
- Add real titlebar-close regressions on X11 and GNOME Wayland, legacy toolbar
  upgrade coverage, and isolated desktop tests that work with an installed package.

## 0.1.2 — 2026-10-24

- Debian installation automatically installs the bundled add-on when Thunderbird
  next starts, with no manual XPI selection. Package updates apply on restart.
- Managed installation allows users to disable the add-on and preserves disabled
  state when upgrading an existing manually installed version.
- Merge and restore only this add-on's policy; retain unrelated administrator
  settings and refuse invalid/conflicting policies without overwriting them.
- Diagnostics check automatic installation. Tests cover real startup, upgrades,
  removal, policy preservation, and native GNOME Wayland.

## 0.1.1 — 2026-10-23

- Separate runtime tarball and reproducible source archive.
- Architecture-independent Debian package with dependencies, system native-host
  registration, bundled XPI, documentation, and a diagnostic command.
- Versioned release directory and SHA-256 checksums for every artifact.
- Diagnostics detect system installations and per-user overrides.
- Wayland integration checks run against the packaged helper and XPI.

## 0.1.0 — 2026-10-23

- Thunderbird add-on and Linux StatusNotifierItem helper.
- Close/minimize-to-tray, restore, unread badges, notifications, and preferences.
- Automatic window recovery after helper, tray, or add-on shutdown.
- X11 and GNOME Wayland integration coverage.
