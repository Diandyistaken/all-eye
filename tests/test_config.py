""".env ayristirma, anahtar dogrulama ve model listesi saniteligi.

BOM tuzagi burada kilitleniyor: Notepad ve `Set-Content -Encoding utf8`
dosyayi BOM ile kaydediyor. Dosya utf-8 (sig'siz) okunursa ilk satirin
anahtar adi gorunmez bir karakterle basliyor, `GEMINI_API_KEY` yerine
`﻿GEMINI_API_KEY` tanimlaniyor ve arac "kaydettim ama tanimli degil"
diyen sessiz bir hataya dusuyor. Bir kez oldu, tekrar olmasin.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from alleye import config

# Gercek anahtar adlarini kullanmiyoruz: testi calistiran makinede tanimli
# olabilirler ve setdefault yuzunden test yalancisi cikar.
A = "ALLEYE_TEST_A"
B = "ALLEYE_TEST_B"
C = "ALLEYE_TEST_C"
D = "ALLEYE_TEST_D"


class EnvFileCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / ".env"
        for name in (A, B, C, D):
            os.environ.pop(name, None)
        self.addCleanup(lambda: [os.environ.pop(n, None) for n in (A, B, C, D)])
        config.ENV_SOURCE.clear()

    def load(self, text: str, encoding: str = "utf-8") -> None:
        self.path.write_text(text, encoding=encoding)
        with mock.patch.object(config, "ENV_FILE", self.path):
            config.load_env_file()


class TestLoadEnvFile(EnvFileCase):
    def test_plain_key(self):
        self.load(f"{A}=AQ.Ab1234567890\n")
        self.assertEqual(os.environ[A], "AQ.Ab1234567890")

    def test_bom_prefixed_file(self):
        """utf-8-sig ile okunmazsa anahtar adi BOM ile baslar ve hicbir yerde
        eslesmez. Bu testi kirmizi gormek icin config.py'de encoding'i
        'utf-8' yapmak yeterli."""
        self.load(f"{A}=AQ.Ab1234567890\n", encoding="utf-8-sig")
        self.assertIn(A, os.environ, "BOM temizlenmemis - anahtar tanimlanamadi")
        self.assertEqual(os.environ[A], "AQ.Ab1234567890")
        self.assertNotIn("﻿" + A, os.environ)

    def test_bom_written_as_literal_char(self):
        # Bazi araclar BOM'u dosyanin icine gomulu karakter olarak birakiyor.
        self.load(f"﻿{A}=deger1\n")
        self.assertEqual(os.environ.get(A), "deger1")

    def test_export_prefix(self):
        self.load(f"export {B}=gsk_abc123\n")
        self.assertEqual(os.environ[B], "gsk_abc123")

    def test_set_prefix(self):
        self.load(f"set {C}=deger3\n")
        self.assertEqual(os.environ[C], "deger3")

    def test_quoted_values(self):
        self.load(f'{A}="cift tirnak"\n{B}=\'tek tirnak\'\n')
        self.assertEqual(os.environ[A], "cift tirnak")
        self.assertEqual(os.environ[B], "tek tirnak")

    def test_comments_and_blank_lines_ignored(self):
        self.load(f"# yorum satiri\n\n   \n{A}=deger\n# {B}=asla\n")
        self.assertEqual(os.environ[A], "deger")
        self.assertNotIn(B, os.environ)

    def test_value_with_equals_sign_survives(self):
        self.load(f"{A}=abc=def==\n")
        self.assertEqual(os.environ[A], "abc=def==")

    def test_surrounding_whitespace_trimmed(self):
        self.load(f"   {A}  =  deger  \n")
        self.assertEqual(os.environ[A], "deger")

    def test_existing_env_var_wins(self):
        """Ortam degiskeni .env'i ezmemeli - ve kullaniciya hangisinin
        kullanildigi soylenmeli, yoksa 'anahtari degistirdim ama degismedi'
        sessiz hatasi cikiyor."""
        os.environ[A] = "ortamdan"
        self.load(f"{A}=dosyadan\n")
        self.assertEqual(os.environ[A], "ortamdan")
        self.assertIn("ortam degiskeni", config.ENV_SOURCE.get(A, ""))

    def test_source_tracking_for_file(self):
        self.load(f"{A}=dosyadan\n")
        self.assertEqual(config.ENV_SOURCE.get(A), ".env dosyasi")

    def test_missing_file_is_not_an_error(self):
        with mock.patch.object(config, "ENV_FILE", Path(self._tmp.name) / "yok.env"):
            config.load_env_file()  # patlamamali

    def test_template_last_line_is_the_gemini_key(self):
        # Sablonun son satiri bilerek bos GEMINI_API_KEY=: notepad acildiginda
        # imlec oraya dusuyor.
        self.assertTrue(config.ENV_TEMPLATE.rstrip("\n").endswith("GEMINI_API_KEY="))


class TestKeyValidation(unittest.TestCase):
    def test_new_auth_key_accepted(self):
        self.assertTrue(config.key_is_usable("GEMINI_API_KEY", "AQ.Ab1234567890"))
        self.assertEqual(config.key_looks_wrong("GEMINI_API_KEY", "AQ.Ab1234567890"), "")

    def test_legacy_key_usable_but_warned(self):
        self.assertTrue(config.key_is_usable("GEMINI_API_KEY", "AIzaSy123"))
        self.assertIn("2026", config.key_looks_wrong("GEMINI_API_KEY", "AIzaSy123"))

    def test_swapped_keys_are_caught(self):
        self.assertIn("GROQ", config.key_looks_wrong("GEMINI_API_KEY", "gsk_abc"))
        self.assertIn("GEMINI", config.key_looks_wrong("GROQ_API_KEY", "AQ.Ab123"))

    def test_empty_key_is_not_usable(self):
        self.assertFalse(config.key_is_usable("GEMINI_API_KEY", ""))
        self.assertEqual(config.key_looks_wrong("GEMINI_API_KEY", ""), "")

    def test_mask_never_leaks_whole_key(self):
        key = "AQ.Ab8RN6JmXk2pQwErTyUiOpAsDfGhJkLzXcVbNm"
        masked = config.mask_secret(key)
        self.assertNotIn(key, masked)
        self.assertIn(str(len(key)), masked)
        self.assertEqual(config.mask_secret(""), "(bos)")


# 2026-07'de gercek bir ucretsiz anahtarla olculdu: bunlar CALISMIYOR.
DEAD_MODELS = {
    "gemini-3-flash",      # boyle bir model hic olmadi
    "gemini-2.5-flash",    # yeni kullanicilara kapali
    "gemini-2.0-flash",    # ucretsiz kotasi sifir (429)
    "gemini-1.5-flash",    # emekli
    "gemini-pro",          # emekli
}


class TestModelChain(unittest.TestCase):
    def gemini(self, key: str) -> list[str]:
        return config.DEFAULTS["gemini"][key]

    def test_no_dead_models_in_chain(self):
        for key in ("models", "models_deep"):
            for m in self.gemini(key):
                self.assertNotIn(m, DEAD_MODELS, f"{key} icinde olu model: {m}")

    def test_fast_chain_is_lite(self):
        """Kademe 1-2 hiz ister. Buyuk flash modelleri ucretsiz katmanda sik
        503 veriyor; one konulunca her cagri 30-130 sn suruyordu."""
        for m in self.gemini("models"):
            self.assertIn("lite", m, f"hizli zincirde agir model var: {m}")

    def test_deep_chain_starts_heavy(self):
        self.assertNotIn("lite", self.gemini("models_deep")[0])

    def test_chains_have_fallbacks(self):
        self.assertGreaterEqual(len(self.gemini("models")), 2)
        self.assertGreaterEqual(len(self.gemini("models_deep")), 2)

    def test_latest_alias_present(self):
        """Google modelleri hizli emekliye ayiriyor; takma ad yeniden
        adlandirmayi sessizce atlatan tek sey."""
        both = self.gemini("models") + self.gemini("models_deep")
        self.assertTrue(any(m.endswith("-latest") for m in both))

    def test_redaction_on_by_default(self):
        self.assertIs(config.DEFAULTS["redact"], True)

    def test_provider_order(self):
        self.assertEqual(config.DEFAULTS["providers"][0], "gemini")
        self.assertIn("ollama", config.DEFAULTS["providers"])


class TestMerge(unittest.TestCase):
    def test_user_config_overrides_only_given_keys(self):
        merged = config._merge(config.DEFAULTS, {"detect": {"fail_streak": 9}})
        self.assertEqual(merged["detect"]["fail_streak"], 9)
        self.assertEqual(merged["detect"]["repeat_threshold"],
                         config.DEFAULTS["detect"]["repeat_threshold"])

    def test_defaults_not_mutated(self):
        before = config.DEFAULTS["detect"]["fail_streak"]
        config._merge(config.DEFAULTS, {"detect": {"fail_streak": 42}})
        self.assertEqual(config.DEFAULTS["detect"]["fail_streak"], before)


if __name__ == "__main__":
    unittest.main()
