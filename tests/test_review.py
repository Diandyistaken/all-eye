"""Faz 4: ogrenen hafiza - konu kumeleme, EQ, kademe aynasi, export/import.

En kritik test: EQ uyarlamamizin Jadud'un ORIJINAL puanlama semasina sadik
kalmasi. Makalenin kendi ornegi (2+3+3=8 -> 8/9=0.88 -> 3 cift -> 0.29)
burada birebir yeniden uretiliyor; puan agirliklari kayarsa test kirmiziya
duser ve metrik sessizce anlamini yitirmez.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alleye import review, store
from alleye.journal import Turn


def turn(cmd: str, exit_code: int = 1, out: str = "", cwd: str = "C:\\p",
         ago_s: float = 0.0) -> Turn:
    return Turn(ts=time.time() - ago_s, cmd=cmd, out=out, exit=exit_code, cwd=cwd)


class TestTopicOf(unittest.TestCase):
    def test_known_topics(self):
        cases = [
            ("git::fatal: not a git repository", "git"),
            ("curl::connection refused", "ag/port"),
            ("ssh::permission denied (publickey)", "izin/kimlik"),
            ("python::modulenotfounderror: no module named 'requests'", "bagimlilik/paket"),
            ("python::syntaxerror: invalid syntax", "sozdizimi/tip"),
            ("docker::image not found", "docker/konteyner"),
            ("make::undefined reference to main", "derleme/yapi"),
        ]
        for sig, expected in cases:
            with self.subTest(sig=sig):
                self.assertEqual(review.topic_of(sig), expected)

    def test_unknown_falls_back(self):
        self.assertEqual(review.topic_of("foo::bir sey oldu"), review.UNKNOWN_TOPIC)
        self.assertEqual(review.topic_of(""), review.UNKNOWN_TOPIC)

    def test_is_pure_and_stable(self):
        sig = "git::fatal: not a git repository"
        self.assertEqual(review.topic_of(sig), review.topic_of(sig))


class TestErrorQuotient(unittest.TestCase):
    """Jadud EQ uyarlamasi - agirliklar kaymasin."""

    def test_pair_score_matches_jadud_weights(self):
        """Ayni komut + ayni hata + ayni dizin = 2+3+3+1 = 9 (tam ceza)."""
        a = turn("git push", 1, "fatal: rejected")
        b = turn("git push", 1, "fatal: rejected")
        self.assertEqual(review.pair_score(a, b), 9)

    def test_no_penalty_when_not_both_failed(self):
        self.assertEqual(review.pair_score(turn("ls", 0), turn("git push", 1, "x")), 0)
        self.assertEqual(review.pair_score(turn("git push", 1, "x"), turn("ls", 0)), 0)

    def test_partial_penalty_different_errors(self):
        """Ikisi de hata ama farkli imza/komut: sadece +2 (ve ayni dizin +1)."""
        a = turn("git push", 1, "fatal: authentication failed")
        b = turn("npm install", 1, "error: no such package")
        self.assertEqual(review.pair_score(a, b), 3)   # 2 + 1 (ayni cwd)

    def test_paper_worked_example(self):
        """Makalenin ornegi: 4 olay, cift skorlari 0, 0, 8 -> EQ 0.29.

        Orijinal ornekte ucuncu cift ayni hata TIPI + ayni hata KONUMU aliyor
        ama ayni duzenleme konumu almiyor (8/9). Bizim karsiligimiz: ayni imza
        (+3) ve ayni komut (+3) ama FARKLI dizin (+0) -> 2+3+3 = 8.
        """
        e1 = turn("gcc a.c", 1, "error: expected ';'", cwd="C:\\a")
        e2 = turn("ls", 0, "", cwd="C:\\a")                      # hatasiz
        e3 = turn("gcc a.c", 1, "error: class expected", cwd="C:\\a")
        e4 = turn("gcc a.c", 1, "error: class expected", cwd="C:\\b")
        self.assertEqual(review.pair_score(e1, e2), 0)
        self.assertEqual(review.pair_score(e2, e3), 0)
        self.assertEqual(review.pair_score(e3, e4), 8)
        eq = review.error_quotient([e1, e2, e3, e4])
        self.assertAlmostEqual(eq, (8 / 9) / 3, places=4)
        self.assertAlmostEqual(eq, 0.296, places=2)

    def test_range_is_zero_to_one(self):
        clean = [turn(f"cmd{i}", 0) for i in range(6)]
        self.assertEqual(review.error_quotient(clean), 0.0)
        stuck = [turn("make", 1, "error: build failed") for _ in range(6)]
        self.assertAlmostEqual(review.error_quotient(stuck), 1.0, places=6)

    def test_short_session_is_zero(self):
        self.assertEqual(review.error_quotient([]), 0.0)
        self.assertEqual(review.error_quotient([turn("x", 1, "error")]), 0.0)

    def test_clean_pairs_dilute_score(self):
        """Ceza vermeyen ciftler de paydaya girer (Jadud boyle) - aksi halde
        tek kotu cift tum oturumu 1.0 gosterirdi."""
        turns = [turn("make", 1, "error: x"), turn("make", 1, "error: x")]
        yuksek = review.error_quotient(turns)
        seyreltilmis = review.error_quotient(turns + [turn(f"ok{i}", 0) for i in range(8)])
        self.assertGreater(yuksek, seyreltilmis)


class TestPracticeHint(unittest.TestCase):
    """Faz 4.3: acik duvar icin kendine-soru. Model cagrisi olmamali."""

    def test_topic_specific_question(self):
        git = review.practice_hint("git::rejected non-fast-forward")
        net = review.practice_hint("curl::connection refused")
        self.assertNotEqual(git, net)
        self.assertIn("?", git)

    def test_unknown_topic_still_gets_question(self):
        h = review.practice_hint("bilinmeyen::sey")
        self.assertTrue(h and h.endswith(("?", ".")))

    def test_never_contains_a_command_answer(self):
        """Kademe kurali: soru duşundurur, cozumu VERMEZ."""
        for sig in ("git::rejected", "pip::no module named x", "ssh::permission denied"):
            h = review.practice_hint(sig)
            self.assertNotIn("$ ", h)
            self.assertNotIn("sudo ", h)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "eye.db"
        self.con = store.connect(self.path)
        self.addCleanup(self.con.close)


class TestStageStats(StoreCase):
    def _ask(self, level: int, sig: str = "git::x"):
        store.record_ask(self.con, cwd="C:\\p", level=level, trigger="manual",
                         signature=sig, question="q", answer="a",
                         provider="gemini", model="m")

    def test_not_enough_data_is_silent(self):
        self._ask(3)
        st = review.stage_stats(self.con)
        self.assertFalse(st["enough"])
        self.assertEqual(review.stage_sentences(st), [])

    def test_bottom_out_ratio_detected(self):
        for _ in range(9):
            self._ask(3)
        self._ask(1)
        st = review.stage_stats(self.con)
        self.assertTrue(st["enough"])
        self.assertAlmostEqual(st["bottom_out"], 0.9, places=6)
        metin = " ".join(review.stage_sentences(st)).lower()
        self.assertIn("tam cozum", metin)
        self.assertIn("2/3", metin)   # arastirma bulgusu kaynakla birlikte

    def test_healthy_usage_gets_positive_note(self):
        for _ in range(12):
            self._ask(1)
        st = review.stage_stats(self.con)
        self.assertLess(st["bottom_out"], 0.25)
        self.assertTrue(any("durtme" in s for s in review.stage_sentences(st)))

    def test_no_connection_is_safe(self):
        st = review.stage_stats(None)
        self.assertEqual(st["total"], 0)
        self.assertFalse(st["enough"])


class TestSummarize(StoreCase):
    def test_empty_says_not_enough_instead_of_inventing(self):
        stats = review.summarize(self.con, [], days=7)
        self.assertFalse(stats["enough"])
        self.assertIn("yeterli veri yok", " ".join(review.sentences(stats)))

    def test_topics_ranked_and_eq_computed(self):
        for _ in range(6):
            store.touch_wall(self.con, "curl::connection refused", "curl x")
        store.touch_wall(self.con, "git::fatal: not a git repository", "git log")
        for _ in range(4):
            store.touch_wall(self.con, "pip::no module named requests", "pip install")
        turns = [turn("curl x", 1, "connection refused") for _ in range(40)]
        stats = review.summarize(self.con, turns, days=7)
        self.assertTrue(stats["enough"])
        self.assertEqual(stats["topics"][0]["topic"], "ag/port")
        self.assertGreater(stats["eq"], 0.5)   # ayni komut+ayni hata tekrari

    def test_old_turns_excluded_from_window(self):
        eski = [turn("make", 1, "error: x", ago_s=40 * 86400) for _ in range(10)]
        stats = review.summarize(self.con, eski, days=7)
        self.assertEqual(stats["commands"], 0)


class TestMemoryPortability(StoreCase):
    def test_export_redacts_notes_by_default(self):
        store.touch_wall(self.con, "db::auth failed", "psql")
        store.teach_wall(self.con, "db::auth failed",
                         "cozum: DB_PASSWORD=SuperGizli123 kullan")
        out = store.export_json(self.con)
        self.assertNotIn("SuperGizli123", out)
        self.assertIn("redacted", out)

    def test_export_raw_keeps_note(self):
        store.touch_wall(self.con, "db::auth failed", "psql")
        store.teach_wall(self.con, "db::auth failed", "parola: SuperGizli123")
        self.assertIn("SuperGizli123", store.export_json(self.con, redact_notes=False))

    def test_import_merges_without_losing_data(self):
        """Makine degistirince gecmis kaybolmamali: hits toplanir, not korunur."""
        store.touch_wall(self.con, "git::rejected", "git push")
        store.teach_wall(self.con, "git::rejected", "fetch + rebase")
        gelen = ('[{"signature": "git::rejected", "first_ts": 1, "last_ts": 2,'
                 ' "hits": 4, "cmd": "git push", "resolved": 0, "note": "baska not"},'
                 ' {"signature": "yeni::hata", "first_ts": 1, "last_ts": 2,'
                 ' "hits": 2, "cmd": "x", "resolved": 0, "note": null}]')
        res = store.import_json(self.con, gelen)
        self.assertEqual(res["eklenen"], 1)
        self.assertEqual(res["birlesen"], 1)
        row = self.con.execute(
            "SELECT hits, note, resolved FROM walls WHERE signature='git::rejected'"
        ).fetchone()
        self.assertEqual(row["hits"], 5)            # 1 + 4 toplandi
        self.assertEqual(row["note"], "fetch + rebase")  # MEVCUT not korundu
        self.assertEqual(row["resolved"], 1)        # cozulmus bayragi kaybolmadi

    def test_import_rejects_garbage(self):
        with self.assertRaises(ValueError):
            store.import_json(self.con, "bu json degil")
        with self.assertRaises(ValueError):
            store.import_json(self.con, '{"tek": "nesne"}')

    def test_roundtrip(self):
        store.touch_wall(self.con, "a::b", "cmd")
        text = store.export_json(self.con)
        with TemporaryDirectory() as t2:
            con2 = store.connect(Path(t2) / "b.db")
            store.import_json(con2, text)
            self.assertEqual(store.stats(con2)["walls"], 1)
            con2.close()


if __name__ == "__main__":
    unittest.main()
