"""Thunderbird's installed application artwork with a local unread-count badge."""

from functools import lru_cache
import os
from pathlib import Path
import shutil
import struct
import zlib

import gi
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GdkPixbuf, GLib


def icon_candidates():
    # Prefer the running application's own artwork over desktop icon-theme
    # substitutions. Nothing is downloaded or redistributed in the package.
    directories = []
    try:
        parent = Path(f'/proc/{os.getppid()}/exe').resolve(strict=True)
        if parent.name.startswith('thunderbird'):
            directories.append(parent.parent / 'chrome/icons/default')
    except OSError:
        pass
    executable = shutil.which('thunderbird')
    if executable:
        directories.append(Path(executable).resolve().parent / 'chrome/icons/default')
    directories.extend(Path(prefix) / 'chrome/icons/default' for prefix in (
        '/usr/lib/thunderbird', '/usr/lib64/thunderbird', '/usr/share/thunderbird',
        '/opt/thunderbird', '/usr/local/lib/thunderbird'))
    for directory in dict.fromkeys(directories):
        for size in (256, 128, 64, 48, 32):
            yield directory / f'default{size}.png'
    for size in (256, 128, 64, 48, 32):
        yield Path(f'/usr/share/icons/hicolor/{size}x{size}/apps/thunderbird.png')
    yield Path('/usr/share/icons/hicolor/scalable/apps/thunderbird.svg')
    yield Path('/usr/share/pixmaps/thunderbird.png')
    yield Path('/usr/share/pixmaps/thunderbird.svg')


@lru_cache(maxsize=1)
def thunderbird_icon():
    for candidate in icon_candidates():
        if not candidate.is_file():
            continue
        try:
            return candidate, GdkPixbuf.Pixbuf.new_from_file(str(candidate))
        except GLib.Error:
            continue
    return None

GLYPHS = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
    "+": ("000", "010", "111", "010", "000"),
}


def badge_label(unread):
    return "99+" if unread > 99 else str(unread) if unread > 0 else ""


@lru_cache(maxsize=24)
def render_icon(size, label=""):
    # Supersampling keeps the curves smooth at panel sizes and on HiDPI displays.
    scale = 3
    width = size * scale
    source = thunderbird_icon()
    if source is None:
        return None
    pixbuf = source[1].scale_simple(width, width, GdkPixbuf.InterpType.BILINEAR)
    if not pixbuf.get_has_alpha():
        pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    raw, stride = pixbuf.get_pixels(), pixbuf.get_rowstride()
    pixels = bytearray(b''.join(raw[y * stride:y * stride + width * 4] for y in range(width)))
    unit = width / 32

    def rounded_rect(x, y, w, h, radius, color):
        for py in range(max(0, int(y * unit)), min(width, int((y + h) * unit + 1))):
            for px in range(max(0, int(x * unit)), min(width, int((x + w) * unit + 1))):
                fx, fy = (px + .5) / unit, (py + .5) / unit
                if not (x <= fx < x + w and y <= fy < y + h):
                    continue
                cx = max(x + radius, min(x + w - radius, fx))
                cy = max(y + radius, min(y + h - radius, fy))
                if (fx - cx) ** 2 + (fy - cy) ** 2 <= radius ** 2:
                    offset = (py * width + px) * 4
                    pixels[offset:offset + 4] = bytes(color)

    if label:
        glyph_width = len(label) * 4 - 1
        badge_width = glyph_width + 4
        left = 32 - badge_width
        rounded_rect(left - 1, 20, badge_width + 1, 12, 4, (255, 255, 255, 255))
        rounded_rect(left, 21, badge_width, 11, 3.5, (196, 49, 55, 255))
        for index, char in enumerate(label):
            for row, bits in enumerate(GLYPHS[char]):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        rounded_rect(left + 2 + index * 4 + col, 24 + row, 1, 1, 0,
                                     (255, 255, 255, 255))
    result = bytearray(size * size * 4)
    # Average premultiplied colors to avoid dark fringes on transparent edges.
    for y in range(size):
        for x in range(size):
            samples = [pixels[((y * scale + dy) * width + x * scale + dx) * 4:
                              ((y * scale + dy) * width + x * scale + dx) * 4 + 4]
                       for dy in range(scale) for dx in range(scale)]
            alpha = sum(pixel[3] for pixel in samples)
            target = (y * size + x) * 4
            if alpha:
                result[target:target + 4] = bytes([
                    *(round(sum(pixel[c] * pixel[3] for pixel in samples) / alpha) for c in range(3)),
                    round(alpha / (scale * scale)),
                ])
    return bytes(result)


def argb_pixmaps(unread, enabled=True):
    result = []
    for size in (22, 32, 48):
        rgba = render_icon(size, badge_label(unread) if enabled else '')
        if rgba is None:
            return []  # The tray host can resolve the standard theme name instead.
        argb = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            argb[i:i + 4] = bytes((rgba[i + 3], rgba[i], rgba[i + 1], rgba[i + 2]))
        result.append((size, size, bytes(argb)))
    return result


def png_bytes(size, unread=0):
    rgba = render_icon(size, badge_label(unread))
    if rgba is None:
        raise FileNotFoundError('Thunderbird application artwork was not found')

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
