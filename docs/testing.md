# Verification

## Automated checks

- `npm test`: settings normalization, folder inclusion/deduplication, bounded
  concurrent counts, partial failures, paginated new mail, list disposal, native
  handshake/version/failure/backoff, stale connection events, main-window scope,
  close/minimize interception, focus-driven restoration, visible-window behavior,
  canceled quit, and teardown.
  Python tests cover framing/UTF-8/partial reads, badge pixmaps, and installation
  lifecycle in a temporary directory including spaces and unrelated files.
  Policy tests cover idempotence, exact restoration, later administrator edits,
  conflicts, malformed JSON, symlinks, policy precedence, and interrupted writes.
- `npm run test:dbus`: actual helper and Gio calls on a private session bus.
  Exercises absent watcher, registration, icon/count changes, direct activation,
  every menu action, disable state, watcher disappearance/recovery, and EOF exit.

No test needs real accounts or credentials. Builds require no network access.

- `npm run test:thunderbird`: runs Thunderbird in a temporary profile on a private
  Xvfb/X11 display with xfwm4 and a test tray watcher. Checks actual X11 mapping,
  titlebar close and native Alt+F4 interception, minimize, restore, actual second
  launches against the same profile, options loading, and tray loss.
- `npm run test:gnome`: starts a private headless GNOME Wayland compositor, the
  system AppIndicator and Dash to Dock extensions, and Thunderbird. A tiny
  inspector extension lives only in a temporary data directory. Checks real window actors, both
  Thunderbird's own titlebar close command and compositor close, and
  minimize commands, tray registration/actions, synthetic local mail counts,
  grouped notifications, mark-read updates, enable/disable preferences, tray loss,
  add-on teardown, and normal Quit. Also starts a real second Thunderbird process
  and activates the private GNOME application launcher, checking restoration of
  the same window and completion of startup. Exercises Dash to Dock's actual
  primary-click handler with the **Minimize window** setting: focus an unfocused
  window, minimize/restore it, restore from the tray, then minimize/restore again.
  Checks Mutter's actual minimized state and verifies a different dock click
  setting still focuses without minimizing.
  Uses a freshly built `.deb` by default, or
  `--package <release.deb|release-linux.tar.gz>` to test a specific artifact.
  Debian's XPI is installed automatically by the normal startup policy loader;
  the tarball uses the manual-install test path. The helper is loaded from the
  release, and GNOME confirms the client is
  native Wayland with XWayland disabled. No user desktop preferences are modified.
- `npm run test:packages`: requires `dpkg` and `fakeroot`. Installs, reinstalls,
  upgrades to a newer revision, removes and purges the `.deb` in a private dpkg root and tests the portable
  install/update/uninstall flow. Unit/package tests verify dependencies, file
  permissions, root ownership, manifest paths, user overrides, checksums and
  byte-for-byte reproducibility of every release artifact.
- `npm run test:policies`: real Thunderbird restarts verify that the Debian
  policy upgrades a previously manually installed XPI, preserves disabled state
  and unrelated preferences, removes the old settings toolbar button, and releases management on removal. A byte copy of
  the system executable runs in a private application directory with symlinked
  libraries. Desktop tests require `bubblewrap` and use private mounts for
  policies and native-host manifests, including on a machine where the package
  is already installed. They never alter real policies or security settings.

## Verified environment

On 2026-10-24: Thunderbird **153.4.0 ESR**, GNOME Shell **50.4**, the system
`ubuntu-appindicators@ubuntu.com` extension, Python **3.14.8**, Node **24.21.0**.
Dash to Dock **106** was used for the configured dock-click checks.
X11 and GNOME Wayland were tested on disposable virtual displays. Release 0.1.4
was tested on native GNOME Wayland from both the `.deb` and runtime tarball.
All 47 unit/package tests, package lifecycle checks and the private D-Bus test
pass. Automatic XPI startup, upgrade, and policy removal are also covered by
real Thunderbird tests. Options screenshots are written under
`.test-artifacts/` and are not packaged.

The titlebar regression was reproduced with 0.1.2: clicking Thunderbird's own
close button exited the application. Version 0.1.3 keeps the window alive and
restores it from the tray on both X11 and native GNOME Wayland. The compositor
close test alone did not cover that separate command path.

The launcher regression was reproduced with 0.1.3: a second process returned
success but its focus request left the existing window hidden. Version 0.1.4
restores it on X11 and native Wayland; GNOME launcher activation also completes.

Wayland’s compositor-only minimize action does not send a minimized-state event
to Thunderbird. The test verifies that Dash to Dock minimizes and restores the
window normally, while Thunderbird's own minimize button hides it in the tray.
Converting compositor-only minimization into a tray hide remains a documented
limitation; compositor minimization itself works.

## Desktop release checklist

Run with a disposable Thunderbird profile on GNOME Wayland and GNOME Xorg.
Record Thunderbird, GNOME, distribution, and AppIndicator extension versions.
Test each Thunderbird major version before claiming compatibility with it.

1. Load the add-on without its helper. Verify settings explain the failure and
   Close/Minimize retain normal behavior.
2. Install the helper without a tray host. Verify no windows can be hidden.
   Enable the GNOME extension and check readiness appears automatically.
3. Close a normal and then a maximized mail window. Verify Thunderbird continues
   running and disappears from overview/Alt+Tab. Restore from the menu and direct
   activation. Check position, size, maximized state, and usable focus.
4. Minimize with the setting on/off. Open two main windows; hide them separately,
   restore both, and verify new main windows are handled.
5. Compose an unsent message and open a standalone message viewer. Verify the
   add-on never intercepts their close behavior or bypasses draft prompts.
6. While hidden, disable the GNOME tray extension, terminate the helper, and
   disable/remove the add-on separately. Verify main windows reappear in all cases.
   Pause the helper process and allow forty seconds for the heartbeat timeout.
7. Turn background mode off and back on from preferences and from the tray menu.
   Verify immediate restoration, persisted preferences, and no delayed alerts
   after notification disable.
8. Use two test accounts, nested folders, and virtual/unified folders. Receive,
   read, delete, copy, and move mail. Verify badge totals, exclusion of Junk/Trash
   and descendants, zero unread, 99+, and partial/offline folder behavior.
9. Receive batches larger than one API page. Verify one grouped generic alert,
   clickable restoration, no startup alerts for old unread mail, and desktop
   Do Not Disturb behavior. Disable Thunderbird’s built-in alerts for this check.
10. Quit through the tray, File menu, and Ctrl+Q. Repeat with an unsaved compose
    window, cancel Quit, and verify close-to-tray still works. Confirm the helper
    exits with Thunderbird and no icon is left behind.
11. Restart Thunderbird; main windows should start visible. Update and uninstall
    the add-on/helper while hidden and check no invisible window is stranded.
12. Inspect preferences with keyboard-only navigation, dark mode, and a narrow
    window. Check live state, error messages, and all test actions.
13. Hide Thunderbird and launch it again from a terminal and the desktop/Dash.
    Verify the existing window returns, no duplicate main window appears, and
    the launcher stops showing startup activity. Repeat while already visible
    with Dash to Dock's **Minimize window** action: the focused window minimizes
    and the next click restores it. An unfocused visible window is focused first.
    Repeat after a tray restore, and check that a focus-only dock action remains
    focus-only. Use a disposable desktop configuration for changing settings.

Passing unit and isolated integration tests does not establish desktop-specific
behavior. The GNOME release checklist remains necessary for distribution releases.
