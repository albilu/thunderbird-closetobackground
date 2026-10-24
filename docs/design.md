# Design

## Components and responsibility

```text
Thunderbird mail/folder events ──→ persistent MailExtension background
                                         │               │
                              window Experiment     notifications API
                                         │
                               native messaging (stdio)
                                         │
                                  Python / Gio helper
                                         │
                           session D-Bus StatusNotifierItem + DBusMenu
                                         │
                                GNOME AppIndicator host
```

The extension owns preferences, counts, notifications, and all Thunderbird
actions. A persistent Manifest V2 background page keeps the native connection
alive. The only privileged code is `backgroundWindows`, which observes main
window lifecycle, manipulates `nsIBaseWindow.visibility`, and exposes the installed
Thunderbird branding icon for notifications. A per-window record
preserves its last non-minimized state. Hiding never closes the window, shuts down
mail checking, or stores a hidden state across launches.
The main window's `minimize()` command is intercepted and restored on unload:
Wayland does not send clients a minimized-state notification. Native X11 minimize
events are also observed. Compositor-only Wayland minimization retains normal
behavior; no GNOME Shell permissions or additional Shell hook are required.
Thunderbird's titlebar close button calls `window.close()` directly, bypassing
the cancelable close event used by the window manager. Both paths are intercepted
for main mail windows. The original functions are restored on unload, and Quit
requests continue through Thunderbird's normal shutdown path.
The main window's `focus()` function also restores hidden windows before invoking
the original focus operation. Thunderbird's remote command-line handler uses
that function when a second launch targets an existing window. Visible windows
continue through the original function, and restoration leaves activation tokens
and focus policy to Thunderbird and the compositor. The function is restored on
unload, and focus requests during an accepted Quit do not reopen hidden windows.

The helper exports `org.kde.StatusNotifierItem` at `/StatusNotifierItem` and
`com.canonical.dbusmenu` at `/MenuBar`. These are the interoperable interface names
used by GNOME AppIndicator and existing Linux panels. GdkPixbuf loads the existing
Thunderbird application icon from its installation (with standard system icon
locations as fallbacks). The helper overlays the unread badge and sends network-order
ARGB pixmaps at multiple sizes. If artwork cannot be found, it supplies the
`thunderbird` theme icon name and keeps counts in the tooltip. No upstream artwork
is bundled, and no icon files accumulate on disk. One helper process is launched per native connection,
so separate Thunderbird profiles have separate icons and preferences.
Each helper owns `org.kde.StatusNotifierItem-PID-1` and registers that service name.
`WindowId` uses the signed integer type expected by the deployed `org.kde`
interface; no X11 window ID is required.

## Failure handling

The startup/default policy is **no hiding**. A helper must use the same protocol
version, see a watcher with a registered host, and successfully register its item
before the extension enables interception. Watcher disappearance clears readiness
and triggers restoration. Watcher return re-registers the item.

The extension handles EOF/disconnect and probes the helper every ten seconds.
More than thirty seconds without a response drops the connection and restores
windows. Reconnection backs off from one second to thirty seconds. Stale events
from old connections cannot enable interception. Unloading the Experiment removes
listeners and restores windows, including when the add-on is disabled or updated.
Quitting uses Thunderbird’s normal request path; it never forces application exit.

The helper parses bounded native frames on a reader thread and dispatches messages
to the GLib main loop. The main loop serializes D-Bus state changes and output.
EOF exits the process and removes its tray objects. Diagnostics use stderr only.

## Native protocol v1

Each JSON object is prefixed by its UTF-8 byte length as a native-endian unsigned
32-bit integer. Frames are limited to 64 KiB; partial reads are accumulated before
parsing. Every object includes `"protocol": 1`.

Extension → helper:

| Type | Additional fields | Meaning |
| --- | --- | --- |
| `hello` | `enabled`, `showUnread`, `incomplete` booleans; `unread` nonnegative safe integer | Initialize connection/state |
| `state` | Same as `hello` | Replace state |
| `ping` | None | Liveness probe |

Helper → extension:

| Type | Additional fields | Meaning |
| --- | --- | --- |
| `status` | `available` boolean, `message` string | Whether it is safe to hide windows |
| `action` | `action`: `restore`, `hide`, `toggle`, `settings`, or `quit` | User tray interaction |
| `pong` | None | Liveness reply |
| `error` | `message` string | Dependency, protocol, or startup failure |

Unknown commands are rejected. The helper receives no message content, account
credentials, folder paths, arbitrary executable names, or shell commands. The
native manifest authorizes only the extension’s fixed ID. D-Bus actions have the
same local-session trust boundary as other desktop tray applications.

## Mail data

Unread counts use folder summaries, not queries over message bodies. At most
eight folder summaries are requested concurrently. Events are debounced, refreshes
are serialized, and a periodic refresh corrects missed events. A count that cannot
be read is reported as partial rather than silently presented as complete.

New-mail notifications are off by default; existing saved boolean preferences
are preserved on upgrade. Users can opt in from the add-on settings.
Notifications use `messages.onNewMailReceived`, skip read/junk messages,
consume paginated lists, and explicitly abort lists when disabled. A bounded
five-minute cache deduplicates message IDs. Bursts are grouped over 800 ms. Generic
notification text never includes sender names or subjects. Both new-mail and
test notifications use Thunderbird's original installed branding icon. The
Experiment reads a fixed local branding resource and returns a PNG data URL,
since the notification's extension principal cannot load privileged chrome URLs.
No artwork is bundled or fetched from the network, and notification disable is
checked again after the icon loads. Existing Thunderbird notification preferences
remain user-controlled.

## Boundaries

This implementation needs a GNOME tray extension; a MailExtension cannot add a
GNOME Shell panel item by itself. It does not install a Shell extension, change
GNOME settings, modify startup services, or bypass Flatpak/Snap confinement.
It depends on Thunderbird internals, so upgrades need smoke testing. Wayland
focus policy belongs to the compositor. Direct activation gestures belong to the
tray host, with the menu as the consistent restore path.
