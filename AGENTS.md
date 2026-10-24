# AGENTS.md

## What this is

Thunderbird "close to background" MailExtension (Manifest V2, persistent background page) plus a Python/PyGObject native-messaging helper that publishes a StatusNotifierItem/DBusMenu tray icon over session D-Bus. Linux/GNOME-first; no wmctrl/xdotool/X11 dependency for the runtime.

Canonical docs — read before nontrivial changes and update alongside behavior changes:
- `docs/design.md`: components, fail-safe semantics, native protocol spec
- `docs/packaging.md`: artifact layout, Debian policy handling, reproducible builds
- `docs/testing.md`: automated coverage + required desktop release checklist + verified baseline
- `docs/wayland.md`: Wayland behavior and its headless test

## Layout

| Path | Contents |
| --- | --- |
| `extension/` | JS add-on: `background.mjs`, `lib/core.mjs` + `lib/native-bridge.mjs`, `options/`; `experiments/backgroundWindows/` is the only privileged code (window visibility interception) |
| `native/` | Helper: `host.py` (native messaging), `tray.py` (SNI/DBusMenu), `protocol.py`, `icons.py` (GdkPixbuf badge) |
| `scripts/` | `build.py` (all artifacts), `install.py` (per-user), `policy.py` (Debian policies.json merge/restore), `doctor.py`, `integration.py` (shared packaging module imported by build) |
| `packaging/` | `debian/` definitions, `install.sh`/`uninstall.sh` (runtime tarball entry points), `release.json` (release metadata) |
| `tests/` | `*.test.mjs` (Node), `test_*.py` (unittest), `*_integration.py` (D-Bus/desktop), `mail_fixture.py`, `package_lifecycle.py` |

## Commands

All offline: no network, npm dependencies, or real mail accounts. Node ≥18 is only needed for the JS tests. Verified as of today.

- Build everything into `dist/<version>/`: `python3 scripts/build.py` (deb needs `dpkg-deb`; use `--formats xpi,tar,source` to skip). No Node/npm downloads involved.
- Full test: `npm test` — this is `node tests/run.mjs` **and** `python3 -m unittest discover -s tests -p 'test_*.py'`; both must pass. `make build`/`make test` are aliases.
- Focused: `node tests/core.test.mjs` (likewise `bridge`/`windows`); `python3 -m unittest tests.test_native` (and other modules).
- Integration: `npm run test:dbus` (private bus + real helper), `npm run test:packages` (`dpkg`+`fakeroot`, private dpkg root), `npm run test:policies` (bubblewrap + Xvfb, real Thunderbird restarts), `npm run test:thunderbird` (Xvfb+xfwm4+xdotool), `npm run test:gnome -- --package dist/<v>/<artifact>` (headless GNOME Wayland; requires the *system* AppIndicator and Dash to Dock extensions installed).
- Dev install: `python3 scripts/install.py` / `--uninstall`; diagnostics `python3 scripts/doctor.py`. Temporary add-on dev: "Load Temporary Add-on" → `extension/manifest.json` (helper must be installed separately).
- No lint/typecheck/formatter config exists in this repo — don't invent or expect one.
- CI: `.github/workflows/release.yml` publishes only the `.deb` + runtime tarball (and a SHA256SUMS filtered to them) on a `v*` tag push, after running both test suites. Tag must equal the manifest version. Desktop tests can't run on Actions runners (no GNOME Wayland/AppIndicator) — releases still require the docs/testing.md checklist.

## Hard rules and gotchas

- `extension/manifest.json` `version` is the version authority (strict X.Y.Z). `scripts/build.py` refuses to build if `package.json` differs. On a bump, sync `CHANGELOG.md` and `packaging/release.json` (`date`, and `debian_revision` for repackages). Reproducible builds use fixed timestamps from `release.json` (`SOURCE_DATE_EPOCH` override); without `--maintainer`/`--homepage`, builds are labeled `Local build <root@localhost>`.
- Thunderbird support is hard-bounded by manifest `strict_min_version`/`strict_max_version` (128.0–153.*). New major versions need a real compatibility run before raising the bound; the window Experiment targets Thunderbird internals that are version-sensitive.
- Helper **stdout is reserved for native-messaging frames** — diagnostics go to stderr only. The wire format is length-prefixed JSON, ≤64 KiB, every frame carries `"protocol": 1`; changing it requires updating both sides (`native/protocol.py` ↔ `extension/lib/native-bridge.mjs`).
- The helper must run under distro `/usr/bin/python3` (packaging/doctor hard-code it) — a venv hides GI bindings (PyGObject/GdkPixbuf). Never run the helper directly in a terminal; stdout would pollute the protocol.
- Fail-safe policy: startup default is **no hiding**; helper loss (immediate via EOF, ~40 s via heartbeat), watcher/tray loss, or add-on disable must restore hidden windows. Don't weaken these paths.
- Compose windows, standalone message viewers, and dialogs must never be intercepted; Quit must go through Thunderbird's normal shutdown path.
- There are two separate close interception paths — titlebar `window.close()` and the window-manager close event (plus `minimize()` and `focus()` interception for launcher restore). Compositor-only close/minimize coverage alone does not catch all regressions (this shipped 0.1.2→0.1.4 fixes); test each path.
- Unread counts skip Junk/Trash/Sent/etc. and are partial-failure aware (reported, retried); notifications are generic (no senders/subjects), grouped, and deduplicated — keep these privacy/counting invariants.
- `dist/` and `.test-artifacts/` are gitignored build/test outputs — never commit them. Desktop/package tests consume build artifacts; run `python3 scripts/build.py` first after manifest changes.
- New JS test suites must be imported in `tests/run.mjs` or they won't run; Python unit tests must be named `tests/test_*.py` to be discovered.
- `docs/testing.md` records the verified baseline (2026-10-24: Thunderbird 153.4.0 ESR, GNOME Shell 50.4, Ubuntu AppIndicators, Dash to Dock 106). Update it whenever you re-verify; passing unit/D-Bus tests alone does not clear a release — the manual desktop checklist still applies.
