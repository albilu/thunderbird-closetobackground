#!/usr/bin/python3
"""Native-messaging entry point. stdout is reserved for framed JSON only."""

import signal
import sys
import threading

# Package-managed code must not leave unowned bytecode behind on uninstall.
sys.dont_write_bytecode = True
from protocol import ProtocolError, Writer, read_message


def main():
    writer = Writer(sys.stdout.buffer)
    try:
        from gi.repository import GLib
        from tray import Tray
    except (ImportError, ValueError) as error:
        writer.send({"type": "error", "message": "Install Python 3 PyGObject and GLib/GdkPixbuf introspection (python3-gi, gir1.2-glib-2.0, gir1.2-gdkpixbuf-2.0 on Debian/Ubuntu)."})
        print(f"Close to Background: {error}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()

    def send(message):
        try:
            writer.send(message)
        except (BrokenPipeError, OSError):
            loop.quit()

    try:
        tray = Tray(send)
    except Exception as error:
        send({"type": "error", "message": "Unable to connect to the desktop session bus. Start Thunderbird inside your desktop session."})
        print(f"Close to Background: {error}", file=sys.stderr)
        return 1

    def receive(message):
        try:
            tray.receive(message)
        except (ProtocolError, ValueError) as error:
            send({"type": "error", "message": str(error)})
            loop.quit()
        return GLib.SOURCE_REMOVE

    def failed(message):
        send({"type": "error", "message": message})
        loop.quit()
        return GLib.SOURCE_REMOVE

    def reader():
        try:
            while (message := read_message(sys.stdin.buffer)) is not None:
                GLib.idle_add(receive, message)
        except (ProtocolError, OSError) as error:
            GLib.idle_add(failed, str(error))
        finally:
            GLib.idle_add(loop.quit)

    try:
        from gi.repository import GLibUnix
        add_signal = GLibUnix.signal_add
    except ImportError:  # Older GLib exposes this function through GLib itself.
        add_signal = GLib.unix_signal_add
    for sig in (signal.SIGTERM, signal.SIGINT):
        add_signal(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    threading.Thread(target=reader, name="native-input", daemon=True).start()
    try:
        loop.run()
    finally:
        tray.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
