"""Bounded, native-endian WebExtension native-messaging frames."""

import json
import struct
import threading

VERSION = 1
MAX_FRAME_BYTES = 64 * 1024
TRAY_STRING_KEYS = frozenset(("title", "show", "hide", "enable", "settings", "quit"))


class ProtocolError(ValueError):
    pass


def tray_strings(value):
    """Optional v1 UI strings, already translated in Thunderbird's UI language."""
    if not isinstance(value, dict) or value.keys() - TRAY_STRING_KEYS:
        raise ProtocolError("Invalid tray strings")
    for text in value.values():
        if (not isinstance(text, str) or not 1 <= len(text) <= 512 or
                any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in text)):
            raise ProtocolError("Invalid tray string")
    return dict(value)


def read_exact(stream, size, *, allow_eof=False):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise ProtocolError("Truncated native-messaging frame")
        chunks.extend(chunk)
    return bytes(chunks)


def read_message(stream):
    header = read_exact(stream, 4, allow_eof=True)
    if header is None:
        return None
    size = struct.unpack("=I", header)[0]
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ProtocolError("Invalid native-messaging frame size")
    try:
        value = json.loads(read_exact(stream, size).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Invalid JSON in native-messaging frame") from error
    if not isinstance(value, dict):
        raise ProtocolError("Native messages must be objects")
    return value


class Writer:
    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def send(self, message):
        payload = json.dumps({**message, "protocol": VERSION}, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(payload) > MAX_FRAME_BYTES:
            raise ProtocolError("Outgoing native message is too large")
        with self.lock:
            self.stream.write(struct.pack("=I", len(payload)) + payload)
            self.stream.flush()
