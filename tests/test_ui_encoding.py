"""Cikti yonlendirildiginde Unicode cokmesi - GERCEK, yasanmis sessiz hata.

Bagimsiz denetimde bulundu: `alleye walls > out.txt` ya da pythonw ile
baslatilan tepsi modu gibi stdout'un boruya/dosyaya gittigi her durumda Python
konsol yerine YEREL KOD SAYFASINI (bu makinede cp1254) kullaniyor. Banner'daki
◉ ve ─ karakterleri cp1254'te yok, dolayisiyla komut UnicodeEncodeError ile
tamamen cokuyordu (walls, autostart, calibrate, status - hepsi rc=1).

Bu ozellikle otomatik baslatma icin kritik: autostart pythonw ile calisiyor,
orada konsol yok.
"""

from __future__ import annotations

import io
import sys
import unittest

from alleye import ui


class LimitedStdout(unittest.TestCase):
    """stdout'u cp1254 ile sinirli bir akisa baglayip ui'yi zorla."""

    def setUp(self):
        self._real = sys.stdout
        self.buf = io.BytesIO()
        # write_through: reconfigure denemesi gercek bir TextIOWrapper'a carpsin
        sys.stdout = io.TextIOWrapper(self.buf, encoding="cp1254",
                                      errors="strict", write_through=True)
        self.addCleanup(self._restore)

    def _restore(self):
        try:
            sys.stdout.flush()
        except Exception:
            pass
        sys.stdout = self._real
        ui._UNICODE_OK = True   # diger testler etkilenmesin


class TestNoCrashOnRedirect(LimitedStdout):
    def test_banner_does_not_raise(self):
        """Duzeltmeden once burada UnicodeEncodeError firliyordu."""
        ui.init()
        ui.banner("durum")          # ◉ ve ─ icerir
        ui.rule()

    def test_helpers_survive_unmappable_glyphs(self):
        ui.init()
        ui.ok("✓ cozulmus")         # cp1254'te olmayan sembol
        ui.note("• acik duvar · 3x")
        ui.warn("takildin")
        ui.error("hata")

    def test_turkish_text_survives(self):
        ui.init()
        ui.note("gunluk bos - once birkac komut calistir (ı ş ğ ü ö ç)")

    def test_stream_out_survives(self):
        ui.init()
        text = ui.stream_out(iter(["ilk ", "parça ✓", " son"]))
        # Kayda giden metin HEP orijinal kalmali (store/mentor bunu kullaniyor)
        self.assertEqual(text, "ilk parça ✓ son")

    def test_glyph_falls_back_when_needed(self):
        ui.init()
        # cp1254 utf-8'e cevrilemediyse ASCII karsiligi gelmeli; cevrildiyse
        # zaten sorun yok. Iki durumda da patlamamali ve bos donmemeli.
        self.assertIn(ui.glyph("◉", "(o)"), ("◉", "(o)"))


class TestNormalStdoutUnaffected(unittest.TestCase):
    def test_init_is_idempotent_and_safe(self):
        ui.init()
        ui.init()
        self.assertIn(ui.glyph("─", "-"), ("─", "-"))


if __name__ == "__main__":
    unittest.main()
