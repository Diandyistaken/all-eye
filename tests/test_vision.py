"""Faz 3: goruntu + vision beyni + gizlilik kapilari.

Bu turda sadece ELZEM olan test edildi:
  - saf yardimcilar (png_dimensions, fit_factor)
  - GIZLILIK kapilari: varsayilan KAPALI ve bozuk girdide REDDET
  - Gemini payload'i goruntuyle/goruntusuz dogru sekilleniyor mu
  - Router goruntu varken gorsel destegi olmayan saglayiciyi eliyor mu

GDI yakalama ve tkinter onizleme gercek masaustu ister; onlar burada test
edilmiyor (yanlis guven verir). Yakalamanin en kritik davranisi - "bos/siyah
kare gelirse None don" - yakalama sirasinda olculdu ve modul basliginda
belgelendi.
"""

from __future__ import annotations

import base64
import platform
import unittest
from unittest import mock

from alleye import config, vision
from alleye.brain import providers
from alleye.brain.router import Router

KEY = "AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLzXcVbNm"


def make_png(w: int = 4, h: int = 3) -> bytes:
    """Gecerli PNG imzasi + IHDR basligi (govde gerekmiyor - sadece baslik okunuyor)."""
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR"
            + w.to_bytes(4, "big") + h.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00govde")


class TestPureHelpers(unittest.TestCase):
    def test_png_dimensions_reads_ihdr(self):
        self.assertEqual(vision.png_dimensions(make_png(1920, 1080)), (1920, 1080))

    def test_png_dimensions_rejects_non_png(self):
        self.assertIsNone(vision.png_dimensions(b"GIF89a" + b"x" * 40))
        self.assertIsNone(vision.png_dimensions(b""))
        self.assertIsNone(vision.png_dimensions(b"\x89PNG\r\n\x1a\n"))  # cok kisa

    def test_png_dimensions_rejects_zero_size(self):
        self.assertIsNone(vision.png_dimensions(make_png(0, 0)))

    def test_fit_factor_no_shrink_when_fits(self):
        self.assertEqual(vision.fit_factor(400, 300, 900, 640), 1)

    def test_fit_factor_shrinks_big_image(self):
        f = vision.fit_factor(3456, 1408, 900, 640)
        self.assertGreater(f, 1)
        self.assertLessEqual(3456 // f, 900)
        self.assertLessEqual(1408 // f, 640)

    def test_fit_factor_never_zero(self):
        self.assertGreaterEqual(vision.fit_factor(10, 10, 0, 0), 1)
        self.assertGreaterEqual(vision.fit_factor(99999, 99999, 10, 10), 1)

    def test_available_matches_platform(self):
        self.assertEqual(vision.available(), platform.system() == "Windows")


class TestPrivacyGates(unittest.TestCase):
    """Iki bagimsiz kapi, ikisi de varsayilan REDDET."""

    def test_vision_disabled_by_default(self):
        """Faz 3 gizlilik yuzeyini en cok buyuten faz - varsayilan KAPALI olmali."""
        self.assertIs(config.DEFAULTS["vision"]["enabled"], False)

    def test_preview_rejects_invalid_png_without_gui(self):
        """Bozuk/bos goruntu asla gonderilmez; GUI'ye bile gidilmez."""
        self.assertFalse(vision.preview_and_confirm(b""))
        self.assertFalse(vision.preview_and_confirm(b"bu bir png degil"))

    def test_module_makes_no_network_calls(self):
        """vision.py sadece yakalar ve gosterir - ag cagrisi ICERMEZ."""
        from pathlib import Path
        src = Path(vision.__file__).read_text(encoding="utf-8")
        for bad in ("urllib", "http.client", "socket", "requests", "urlopen"):
            self.assertNotIn(bad, src, f"vision.py icinde ag kullanimi: {bad}")


def chunk(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class GeminiVisionCase(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple] = []
        env = mock.patch.dict("os.environ", {"GEMINI_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = {"models": ["gemini-3.5-flash-lite"],
                    "models_deep": ["gemini-3.6-flash"],
                    "api_key_env": "GEMINI_API_KEY"}

    def fake(self, *responses):
        queue = list(responses)

        def _stream(url, payload, headers, *a, **kw):
            self.calls.append((url, payload, headers, a, kw))
            item = queue.pop(0) if queue else []
            if isinstance(item, Exception):
                raise item
            yield from item

        return mock.patch.object(providers, "stream_sse", _stream)


class TestGeminiVision(GeminiVisionCase):
    def test_image_becomes_inline_data(self):
        png = make_png()
        with self.fake([chunk("gordum")]):
            out = "".join(providers.Gemini(self.cfg).stream("s", "u", png))
        self.assertEqual(out, "gordum")
        parts = self.calls[0][1]["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "u"})
        inline = parts[1]["inlineData"]
        self.assertEqual(inline["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(inline["data"]), png)

    def test_text_path_payload_unchanged(self):
        """Goruntu yoksa govde eskisiyle BIREBIR ayni kalmali."""
        with self.fake([chunk("x")]):
            list(providers.Gemini(self.cfg).stream("s", "u"))
        parts = self.calls[0][1]["contents"][0]["parts"]
        self.assertEqual(parts, [{"text": "u"}])

    def test_image_gets_longer_timeout(self):
        with self.fake([chunk("x")]):
            list(providers.Gemini(self.cfg).stream("s", "u", make_png()))
        with self.fake([chunk("x")]):
            list(providers.Gemini(self.cfg).stream("s", "u"))
        self.assertEqual(self.calls[0][3][0], 90.0)   # goruntulu
        self.assertEqual(self.calls[1][3][0], 45.0)   # metin

    def test_only_gemini_declares_vision(self):
        self.assertTrue(providers.Gemini(self.cfg).supports_vision)
        self.assertFalse(providers.Groq({"models": ["m"]}).supports_vision)
        self.assertFalse(providers.Ollama({"models": ["m"]}).supports_vision)


class TestRouterVision(GeminiVisionCase):
    def test_router_refuses_when_no_vision_provider(self):
        """Sessizce metin-only gondermek kullaniciyi yaniltirdi (goruntuye
        baktigini sanir); net hata veriyoruz."""
        cfg = {"providers": ["ollama"], "ollama": {"models": ["m"]}}
        with self.assertRaises(providers.ProviderError) as cm:
            list(Router(cfg).stream("s", "u", make_png()))
        self.assertIn("goruntu", str(cm.exception).lower())

    def test_router_passes_image_to_gemini(self):
        cfg = {"providers": ["ollama", "gemini"],
               "ollama": {"models": ["m"]}, "gemini": self.cfg}
        png = make_png()
        with self.fake([chunk("ok")]):
            out = "".join(Router(cfg).stream("s", "u", png))
        self.assertEqual(out, "ok")
        # ollama elendi, tek cagri gemini'ye gitti
        self.assertEqual(len(self.calls), 1)
        self.assertIn("inlineData", str(self.calls[0][1]))

    def test_router_text_path_still_works(self):
        cfg = {"providers": ["gemini"], "gemini": self.cfg}
        with self.fake([chunk("metin")]):
            out = "".join(Router(cfg).stream("s", "u"))
        self.assertEqual(out, "metin")
        self.assertNotIn("inlineData", str(self.calls[0][1]))


if __name__ == "__main__":
    unittest.main()
