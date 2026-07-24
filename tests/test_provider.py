"""Saglayici sozlesmesi - ag'a cikmadan.

Gemini tuzagi: kimlik dogrulama `x-goog-api-key` BASLIGI ile yapilmali.
Yeni "AQ." auth key'ler URL'deki eski `?key=` parametresiyle CALISMIYOR
(401 doner) - bircok ucuncu parti arac tam olarak bu yuzden kirik.
"""

from __future__ import annotations

import unittest
from unittest import mock

from alleye.brain import providers
from alleye.brain.http import HttpError

KEY = "AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLzXcVbNm"

GEMINI_CFG = {
    "models": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
    "models_deep": ["gemini-3.6-flash", "gemini-flash-latest"],
    "api_key_env": "GEMINI_API_KEY",
}


def chunk(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class GeminiCase(unittest.TestCase):
    def setUp(self):
        self.calls: list[tuple[str, dict, dict]] = []
        env = mock.patch.dict("os.environ", {"GEMINI_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)

    def fake_stream(self, *responses):
        """Her cagriya sirayla bir cevap: chunk listesi ya da HttpError."""
        queue = list(responses)

        def _stream(url, payload, headers, *a, **kw):
            self.calls.append((url, payload, headers))
            item = queue.pop(0) if queue else []
            if isinstance(item, Exception):
                raise item
            yield from item

        return mock.patch.object(providers, "stream_sse", _stream)


class TestGeminiAuth(GeminiCase):
    def test_api_key_sent_as_header(self):
        with self.fake_stream([chunk("merhaba")]):
            out = "".join(providers.Gemini(GEMINI_CFG).stream("sys", "user"))
        self.assertEqual(out, "merhaba")
        _, _, headers = self.calls[0]
        self.assertEqual(headers.get("x-goog-api-key"), KEY)

    def test_key_never_in_url(self):
        """URL'ye anahtar konursa hem AQ. anahtarlari kirilir hem de anahtar
        loglara/proxy'lere sizar."""
        with self.fake_stream([chunk("x")]):
            list(providers.Gemini(GEMINI_CFG).stream("sys", "user"))
        url = self.calls[0][0]
        self.assertNotIn("key=", url)
        self.assertNotIn(KEY, url)

    def test_streaming_endpoint(self):
        with self.fake_stream([chunk("x")]):
            list(providers.Gemini(GEMINI_CFG).stream("sys", "user"))
        url = self.calls[0][0]
        self.assertIn(":streamGenerateContent", url)
        self.assertIn("alt=sse", url)
        self.assertIn("gemini-3.5-flash-lite", url)

    def test_missing_key_raises_before_network(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}), self.fake_stream():
            with self.assertRaises(providers.ProviderError):
                list(providers.Gemini(GEMINI_CFG).stream("sys", "user"))
        self.assertEqual(self.calls, [])

    def test_ready_reports_key_problems(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "gsk_yanlis"}):
            ok, why = providers.Gemini(GEMINI_CFG).ready()
        self.assertFalse(ok)
        self.assertIn("GROQ", why)


class TestGeminiFallback(GeminiCase):
    def test_503_moves_to_next_model(self):
        """Ucretsiz katmanda buyuk flash modelleri sik 503 veriyor."""
        err = HttpError(503, '{"error":{"message":"overloaded"}}', "u")
        with self.fake_stream(err, [chunk("ikinci model")]):
            out = "".join(providers.Gemini(GEMINI_CFG).stream("s", "u"))
        self.assertEqual(out, "ikinci model")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("gemini-3.1-flash-lite", self.calls[1][0])

    def test_404_and_429_move_on(self):
        for status in (404, 429, 400, 0):
            with self.subTest(status=status):
                self.calls.clear()
                err = HttpError(status, "{}", "u")
                with self.fake_stream(err, [chunk("ok")]):
                    out = "".join(providers.Gemini(GEMINI_CFG).stream("s", "u"))
                self.assertEqual(out, "ok")

    def test_auth_error_stops_the_chain(self):
        """403/401'de sonraki modeli denemek anlamsiz - anahtar sorunu."""
        err = HttpError(403, '{"error":{"message":"forbidden"}}', "u")
        with self.fake_stream(err, [chunk("asla")]):
            with self.assertRaises(providers.ProviderError):
                list(providers.Gemini(GEMINI_CFG).stream("s", "u"))
        self.assertEqual(len(self.calls), 1)

    def test_all_models_failed_reports_each(self):
        errs = (HttpError(503, "{}", "u"), HttpError(429, "{}", "u"))
        with self.fake_stream(*errs):
            with self.assertRaises(providers.ProviderError) as cm:
                list(providers.Gemini(GEMINI_CFG).stream("s", "u"))
        msg = str(cm.exception)
        self.assertIn("gemini-3.5-flash-lite", msg)
        self.assertIn("gemini-3.1-flash-lite", msg)

    def test_empty_answer_tries_next_model(self):
        with self.fake_stream([], [chunk("ikinci")]):
            out = "".join(providers.Gemini(GEMINI_CFG).stream("s", "u"))
        self.assertEqual(out, "ikinci")

    def test_used_model_recorded(self):
        err = HttpError(503, "{}", "u")
        p = providers.Gemini(GEMINI_CFG)
        with self.fake_stream(err, [chunk("ok")]):
            list(p.stream("s", "u"))
        self.assertEqual(p.model, "gemini-3.1-flash-lite")


class TestDeepSelection(unittest.TestCase):
    def test_level3_uses_deep_chain(self):
        self.assertEqual(providers.Gemini(GEMINI_CFG, deep=True).models,
                         GEMINI_CFG["models_deep"])

    def test_default_uses_fast_chain(self):
        self.assertEqual(providers.Gemini(GEMINI_CFG).models, GEMINI_CFG["models"])

    def test_deep_falls_back_when_absent(self):
        cfg = {"models": ["a", "b"], "api_key_env": "X"}
        self.assertEqual(providers.Gemini(cfg, deep=True).models, ["a", "b"])


class TestOpenAICompat(unittest.TestCase):
    def test_groq_uses_bearer_header(self):
        calls = []

        def _stream(url, payload, headers, *a, **kw):
            calls.append((url, payload, headers))
            yield {"choices": [{"delta": {"content": "selam"}}]}

        cfg = {"models": ["llama-3.3-70b-versatile"], "api_key_env": "GROQ_API_KEY"}
        with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk_test123"}), \
             mock.patch.object(providers, "stream_sse", _stream):
            out = "".join(providers.Groq(cfg).stream("s", "u"))
        self.assertEqual(out, "selam")
        self.assertEqual(calls[0][2]["Authorization"], "Bearer gsk_test123")
        self.assertTrue(calls[0][1]["stream"])

    def test_registry_has_every_default_provider(self):
        from alleye import config
        for name in config.DEFAULTS["providers"]:
            self.assertIn(name, providers.REGISTRY)


if __name__ == "__main__":
    unittest.main()
