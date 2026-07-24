"""Pano izleyici testleri.

looks_like_error SAF fonksiyon dogrudan kilitleniyor. clipboard_signal icin
sahte Turn nesneleri kullaniliyor - gercek pano gerekmiyor. read_text icin
sadece non-Windows/erisimsiz koruma test ediliyor; gercek pano okunursa
(Windows + oturum acik) bir duman testi de var, olmazsa skip.
"""

from __future__ import annotations

import platform
import time
import unittest
from unittest import mock

from alleye import clipboard, detect
from alleye.journal import Turn


def turn(cmd: str, exit_code: int = 0, out: str = "") -> Turn:
    return Turn(ts=time.time(), cmd=cmd, out=out, exit=exit_code, dur_ms=10)


class TestLooksLikeError(unittest.TestCase):
    def test_error_text_true(self):
        self.assertTrue(clipboard.looks_like_error(
            "ModuleNotFoundError: No module named 'requests'"))

    def test_traceback_true(self):
        self.assertTrue(clipboard.looks_like_error(
            "Traceback (most recent call last):\n  File \"a.py\", line 1"))

    def test_turkish_hata_true(self):
        self.assertTrue(clipboard.looks_like_error("erisim reddedildi: dosya bulunamadi"))

    def test_ordinary_text_false(self):
        self.assertFalse(clipboard.looks_like_error(
            "bu sadece siradan bir not, ozel bir sey yok burada"))

    def test_empty_false(self):
        self.assertFalse(clipboard.looks_like_error(""))
        self.assertFalse(clipboard.looks_like_error("   "))

    def test_too_long_false(self):
        long_text = "error: x\n" * 2000
        self.assertFalse(clipboard.looks_like_error(long_text))

    def test_code_without_keyword_false(self):
        self.assertFalse(clipboard.looks_like_error("def add(a, b):\n    return a + b"))


class TestClipboardSignal(unittest.TestCase):
    def test_matching_error_produces_signal(self):
        err = "ModuleNotFoundError: No module named 'requests'"
        turns = [turn("python a.py", 1, err)]
        sig = clipboard.clipboard_signal(err, turns)
        self.assertIsNotNone(sig)
        self.assertIsInstance(sig, detect.Signal)
        self.assertEqual(sig.kind, "pano-arama")
        self.assertEqual(sig.weight, 2)

    def test_unrelated_error_returns_none(self):
        """Pano bir hataya benziyor ama son basarisiz komutun ciktisiyla alakasiz."""
        turns = [turn("python a.py", 1, "ModuleNotFoundError: No module named 'requests'")]
        sig = clipboard.clipboard_signal("error: disk full, cannot allocate space", turns)
        self.assertIsNone(sig)

    def test_empty_clip_returns_none(self):
        turns = [turn("python a.py", 1, "error: something failed")]
        self.assertIsNone(clipboard.clipboard_signal("", turns))

    def test_non_error_clip_returns_none(self):
        """Pano metni hata gibi gorunmuyorsa, ciktiyla ayni bile olsa sinyal yok."""
        out = "derleme bitti, hersey normal gorunuyor burada"
        turns = [turn("python a.py", 1, out)]
        self.assertIsNone(clipboard.clipboard_signal(out, turns))

    def test_no_turns_returns_none(self):
        self.assertIsNone(clipboard.clipboard_signal("error: something failed", []))

    def test_no_failed_turn_returns_none(self):
        turns = [turn("ls"), turn("git status")]
        self.assertIsNone(clipboard.clipboard_signal("error: something failed", turns))

    def test_uses_last_failed_turn(self):
        """Basarili son komuttan once gelen hatayla bile eslesme yapabilmeli."""
        err = "fatal: not a git repository (or any of the parent directories)"
        turns = [turn("git log", 128, err), turn("ls")]
        sig = clipboard.clipboard_signal(err, turns)
        self.assertIsNotNone(sig)


class TestReadTextGuard(unittest.TestCase):
    def test_non_windows_returns_empty(self):
        with mock.patch.object(clipboard.platform, "system", return_value="Linux"):
            self.assertEqual(clipboard.read_text(), "")

    def test_available_false_on_non_windows(self):
        with mock.patch.object(clipboard.platform, "system", return_value="Darwin"):
            self.assertFalse(clipboard.available())

    def test_available_matches_platform(self):
        self.assertIsInstance(clipboard.available(), bool)
        if platform.system() == "Windows":
            self.assertTrue(clipboard.available())
        else:
            self.assertFalse(clipboard.available())


@unittest.skipUnless(platform.system() == "Windows", "pano yalniz Windows'ta")
class TestSmoke(unittest.TestCase):
    """Gercek pano erisimi dumani. Pano okunamiyorsa (bassiz oturum vb) skip."""

    def test_read_text_does_not_raise(self):
        if not clipboard.available():
            self.skipTest("pano erisilebilir degil")
        try:
            result = clipboard.read_text()
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"pano okunamadi: {exc}")
        self.assertIsInstance(result, str)


if __name__ == "__main__":
    unittest.main()
