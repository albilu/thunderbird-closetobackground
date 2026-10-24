import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native"))
sys.path.insert(0, str(ROOT / "scripts"))
from protocol import MAX_FRAME_BYTES, ProtocolError, Writer, read_message, tray_strings
import icons
from icons import argb_pixmaps, badge_label, png_bytes
from install import install, uninstall, EXTENSION_ID


class FragmentedStream(io.BytesIO):
    def read(self, count=-1):
        return super().read(min(count, 2))


class ProtocolTests(unittest.TestCase):
    def test_round_trip_fragmented_utf8_and_multiple_frames(self):
        output = io.BytesIO()
        Writer(output).send({"type": "status", "message": "Prêt ✉"})
        Writer(output).send({"type": "pong"})
        stream = FragmentedStream(output.getvalue())
        self.assertEqual(read_message(stream)["message"], "Prêt ✉")
        self.assertEqual(read_message(stream), {"type": "pong", "protocol": 1})
        self.assertIsNone(read_message(stream))

    def test_invalid_frames_are_rejected(self):
        for data in (b"\x00", struct.pack("=I", 0), struct.pack("=I", MAX_FRAME_BYTES + 1),
                     struct.pack("=I", 2) + b"{", struct.pack("=I", 2) + b"[]",
                     struct.pack("=I", 1) + b"\xff"):
            with self.subTest(data=data), self.assertRaises(ProtocolError):
                read_message(io.BytesIO(data))

    def test_optional_translated_tray_strings_are_bounded_and_validated(self):
        self.assertEqual(tray_strings({}), {})  # Existing v1 senders use English defaults.
        strings = {"show": "Afficher Thunderbird", "title": "Thunderbird — 2 messages non lus"}
        output = io.BytesIO()
        Writer(output).send({"type": "state", "strings": strings})
        self.assertEqual(tray_strings(read_message(io.BytesIO(output.getvalue()))["strings"]), strings)
        for invalid in (None, [], "fr", {"unknown": "text"}, {"show": 1}, {"show": ""},
                        {"show": "x" * 513}, {"title": "a\0b"}, {"title": "a\nb"}, {"title": "\ud800"}):
            with self.subTest(value=invalid), self.assertRaises(ProtocolError):
                tray_strings(invalid)


class IconTests(unittest.TestCase):
    def tearDown(self):
        icons.thunderbird_icon.cache_clear()
        icons.render_icon.cache_clear()

    def test_badge_cap(self):
        self.assertEqual(badge_label(0), "")
        self.assertEqual(badge_label(8), "8")
        self.assertEqual(badge_label(100), "99+")

    @unittest.skipUnless(icons.thunderbird_icon(), 'Thunderbird application artwork is not installed')
    def test_badge_pixel_layout(self):
        zero, unread = argb_pixmaps(0), argb_pixmaps(12)
        self.assertNotEqual(zero, unread)
        for width, height, data in unread:
            self.assertEqual(len(data), width * height * 4)
            self.assertEqual(data[:4], b"\0\0\0\0")
            center = ((height // 2) * width + width // 2) * 4
            self.assertEqual(data[center], 255)  # alpha is first, in network byte order
        self.assertTrue(png_bytes(32, 5).startswith(b"\x89PNG\r\n\x1a\n"))

    def test_uses_application_pixels_and_preserves_them_outside_badge(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'application.png'
            pixbuf = icons.GdkPixbuf.Pixbuf.new(icons.GdkPixbuf.Colorspace.RGB, True, 8, 32, 32)
            pixbuf.fill(0x0c2238ff)
            pixbuf.savev(str(source), 'png', [], [])
            broken = Path(directory) / 'broken.png'
            broken.write_text('invalid image')
            icons.thunderbird_icon.cache_clear()
            icons.render_icon.cache_clear()
            with patch.object(icons, 'icon_candidates', return_value=[broken, source]):
                self.assertEqual(icons.thunderbird_icon()[0], source)
                self.assertEqual(icons.render_icon(32), bytes((12, 34, 56, 255)) * 32 * 32)
                normal, badged = argb_pixmaps(0), argb_pixmaps(12)
                self.assertNotEqual(normal, badged)
                self.assertEqual(normal[0][2][:4], bytes((255, 12, 34, 56)))
                self.assertEqual(normal[0][2][:22 * 12 * 4], badged[0][2][:22 * 12 * 4])
                self.assertEqual(argb_pixmaps(12, False), normal)

    def test_missing_artwork_allows_tray_theme_fallback(self):
        icons.thunderbird_icon.cache_clear()
        icons.render_icon.cache_clear()
        with patch.object(icons, 'icon_candidates', return_value=[]):
            self.assertEqual(argb_pixmaps(12), [])
            with self.assertRaises(FileNotFoundError):
                png_bytes(32)


class InstallerTests(unittest.TestCase):
    def test_install_update_uninstall_with_spaces_and_foreign_files(self):
        with tempfile.TemporaryDirectory(prefix="tray user ") as directory:
            target, manifest_path = install(Path(directory))
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["allowed_extensions"], [EXTENSION_ID])
            self.assertEqual(manifest["path"], str(target / "host.py"))
            self.assertTrue((target / "host.py").stat().st_mode & 0o111)
            (target / "keep.txt").write_text("user file")
            install(Path(directory))
            uninstall(Path(directory))
            self.assertFalse(manifest_path.exists())
            self.assertFalse((target / "host.py").exists())
            self.assertEqual((target / "keep.txt").read_text(), "user file")
            uninstall(Path(directory))  # idempotent

    def test_foreign_manifest_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            _, manifest_path = install(Path(directory))
            manifest = json.loads(manifest_path.read_text())
            manifest["path"] = "/some/other/program"
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                install(Path(directory))
            with self.assertRaises(ValueError):
                uninstall(Path(directory))


if __name__ == "__main__":
    unittest.main()
