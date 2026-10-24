# Packaging and distribution

## Release artifacts

`python3 scripts/build.py` builds everything offline in `dist/0.1.5/`:

| File | Contents |
| --- | --- |
| `thunderbird-closetobackground_0.1.5-1_all.deb` | System helper, native-host registration, automatically installed XPI, diagnostic command, manual and documentation |
| `thunderbird-closetobackground-0.1.5-linux.tar.gz` | Small per-user install bundle, XPI, installer/uninstaller, diagnostics and setup documentation |
| `thunderbird-closetobackground-0.1.5-source.tar.gz` | Rebuildable source, packaging definitions, tests and developer documentation |
| `thunderbird-closetobackground-0.1.5.xpi` | Thunderbird add-on only; requires the matching helper |
| `SHA256SUMS` | SHA-256 digests of the four artifacts above |

The runtime archives contain no test profiles, screenshots, development caches,
build outputs, or personal paths. The source archive includes the effective release
metadata so it can reproduce a customized build. No root access or downloads are
needed to build. Building `.deb` requires the `dpkg-deb` tool from `dpkg`.

```sh
python3 scripts/build.py
cd dist/0.1.5
sha256sum -c SHA256SUMS
```

On a distribution without `dpkg`, build only the portable formats:

```sh
python3 scripts/build.py --formats xpi,tar,source
```

## Debian/Ubuntu installation

```sh
sudo apt install ./thunderbird-closetobackground_0.1.5-1_all.deb
sudo apt install gnome-shell-extension-appindicator
```

Enable the GNOME AppIndicator extension in the Extensions application. Then
**start or restart Thunderbird**. It installs the bundled add-on automatically;
there is no manual XPI selection. The policy uses only a local file, with no
download, and works for new and existing profiles that use the system policy.

The add-on uses a privileged Experiment API. Installing the Debian package
authorizes its unrestricted Thunderbird access through the policy, without a
separate interactive XPI permission prompt. Users can disable the add-on. While
the policy is active, Thunderbird treats its installation as managed and does
not offer removal. The package never edits user profiles, starts Thunderbird,
or changes GNOME settings. Native Thunderbird 128–153 is required; Flatpak and
Snap builds remain unsupported.

```sh
thunderbird-closetobackground-doctor
```

Installation layout:

| Path | Purpose |
| --- | --- |
| `/usr/share/thunderbird-closetobackground/native/` | Architecture-independent Python helper and D-Bus interfaces |
| `/usr/lib/mozilla/native-messaging-hosts/net.thunderbird.closetobackground.json` | System native-messaging registration |
| `/usr/share/thunderbird-closetobackground/thunderbird-closetobackground.xpi` | Add-on automatically installed/updated on Thunderbird startup |
| `/usr/bin/thunderbird-closetobackground-doctor` | Read-only setup diagnostics |
| `/etc/thunderbird/policies/policies.json` | Automatic installation policy, merged with existing settings |
| `/var/lib/thunderbird-closetobackground/policy-state.json` | Private recovery information for the policy change |
| `/usr/share/doc/thunderbird-closetobackground/` | Setup, license, changelog, and compatibility notes |

`Architecture: all` means the Python/XPI payload is CPU-independent; it still
requires the target distribution's Python and GI packages. The package declares
those dependencies and contains root-owned files with normalized permissions.
Its maintainer scripts configure and restore the automatic installation policy.
There are no system services, and the helper does not create bytecode in package
directories.

After upgrading the package, **restart Thunderbird**. It compares the installed
add-on with the bundled XPI and applies newer versions. Existing settings and
the user's disabled state are retained. Separate online add-on updates are
disabled for this add-on so the helper and XPI come from the same package.
To remove the package:

```sh
sudo apt remove thunderbird-closetobackground
```

Restart Thunderbird to release policy management. The profile's installed copy
remains available to remove through Add-ons and Themes; package scripts never
delete profile files as root. With the native helper gone, the add-on keeps mail
windows visible. Removing the package does not reinstall the add-on on later
starts. User preferences remain untouched.

### Preserving administrator policies

The package uses Thunderbird's `ExtensionSettings` policy with
`installation_mode: normal_installed` and a `file:///` URL. It merges only
`closetobackground@thunderbird-background.local`. It never replaces the whole
policy with a package-owned file. If `/etc/thunderbird/policies/policies.json`
does not exist but `/usr/lib/thunderbird/distribution/policies.json` does, it
edits that existing policy instead of creating a system policy that would hide it.
This automatic setup targets the native Debian/Ubuntu layout; customized policy
locations in other Thunderbird installations need administrator configuration.

Removal restores the original bytes and permissions when no other edits were
made. Otherwise it removes only its own unchanged entry, preserving subsequent
administrator edits, other extensions, and symlinks. The original configuration
is backed up privately before writing the policy. Reinstall/configure is
idempotent and interrupted configuration can be retried.

Malformed JSON, duplicate keys, conflicting policies for this add-on, or a
changed policy location stop package configuration with a clear error. No
conflicting administrator policy is overwritten. After resolving the conflict,
run `sudo dpkg-reconfigure thunderbird-closetobackground`. The diagnostic command
checks the policy visible to Thunderbird as well as the native helper.

### Switching from a per-user installation

A per-user native manifest takes precedence over the system manifest. Disable
the add-on, run `./uninstall.sh` from the extracted Linux tarball as your normal
user, install the Debian package, restart Thunderbird, then re-enable the add-on.
The bundled XPI upgrades a previous manual installation automatically. The diagnostic
command detects overrides, including a stale or broken user registration.
The Debian package never removes another user's files.

## Portable tar installation

Install Python 3.10+, PyGObject with GLib and GdkPixbuf introspection, native Thunderbird, and a tray
host using your distribution packages. Then:

```sh
tar -xzf thunderbird-closetobackground-0.1.5-linux.tar.gz
cd thunderbird-closetobackground-0.1.5
./install.sh
/usr/bin/python3 scripts/doctor.py
```

Install the included `thunderbird-closetobackground-0.1.5.xpi` through Thunderbird.
Do not use sudo for this installer. It copies the helper into
`~/.local/share/thunderbird-close-to-background/` and registers it in
`~/.mozilla/native-messaging-hosts/`. The runtime does not depend on the extracted
directory. Retain or re-extract the tarball when you need the uninstaller:

```sh
./uninstall.sh
```

Re-running the installer updates the helper. Updates preserve Thunderbird's
settings; update the XPI separately. The uninstaller preserves unrelated files.

## Reproducible builds and release metadata

The add-on manifest is the version authority; `package.json` must match. ZIP,
tar, gzip, and Debian metadata use fixed timestamps and permissions. Debian
archives use xz compression, with no dependency downloads. `SOURCE_DATE_EPOCH`
can override the release date in `packaging/release.json`.

The maintainer and homepage of every artifact come from `packaging/release.json`;
override them when distributing under different contact data:

```sh
python3 scripts/build.py \
  --maintainer 'Your Name <you@your-domain.example>' \
  --homepage 'https://your-project.example/' \
  --debian-revision 1
```

These arguments are validated and recorded in the source archive. Builds with
the same source, effective metadata, `SOURCE_DATE_EPOCH`, and toolchain are
byte-for-byte reproducible. SHA-256 checks detect corrupted downloads; they are
not publisher signatures. No signing key, repository, or publication is assumed.
For an authenticated public release, publish artifacts and sign `SHA256SUMS`
using the project's existing release-signing process.

## Release verification

```sh
npm test
npm run test:dbus
npm run test:packages
npm run test:policies
npm run test:gnome -- --package dist/0.1.5/thunderbird-closetobackground_0.1.5-1_all.deb
npm run test:gnome -- --package dist/0.1.5/thunderbird-closetobackground-0.1.5-linux.tar.gz
```

Package lifecycle tests require `dpkg` and `fakeroot`. Package tests inspect
metadata/ownership/dependencies, verify checksums, reproduce
the release from its source archive, exercise tar install/update/remove, and run
Debian install/update/remove in a temporary dpkg root. They never install into
the machine's real package database. Maintainer scripts run with `DPKG_ROOT`
pointing into that private root. Policy tests cover preservation, conflicts,
symlinks, removal, and retry after a write failure.

The GNOME tests use the packaged XPI and helper in disposable native Wayland
sessions. For Debian, Thunderbird installs the XPI through its normal startup
policy loader. A separate real Thunderbird test checks automatic upgrades from
a manually installed XPI, disabled state, and management removal across restarts.
Tests relocate only absolute helper/XPI paths and use a private application
directory with an unchanged Thunderbird binary. Bubblewrap gives each test
private policy and native-host mounts, so an installed package cannot interfere
and the user's installation remains untouched. No production security settings
or automation-only policy overrides are used.

Packaging follows the documented [Debian filesystem layout](https://www.debian.org/doc/debian-policy/ch-opersys.html)
and [dpkg-deb build interface](https://manpages.debian.org/bookworm/dpkg/dpkg-deb.1.en.html).
Native registrations use [Mozilla's Linux manifest locations](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests).
Automatic add-on installation uses [Thunderbird's documented extension policies](https://thunderbird.github.io/policy-templates/policies/release/#extensionsettings-extension-management).
