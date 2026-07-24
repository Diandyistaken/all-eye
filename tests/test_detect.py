"""Zorlanma esikleri.

Bu katman modele hic sormadan "takildin mi" diyor. Esikler kayarsa arac ya
hic konusmaz ya da surekli araya girer - ikisi de kullanicinin araci ilk gun
kapatmasi demek.
"""

from __future__ import annotations

import time
import unittest

from alleye import detect
from alleye.journal import Turn

CFG = {"detect": {"repeat_threshold": 3, "fail_streak": 3, "stagnation_minutes": 20}}


def turn(cmd: str, exit_code: int = 0, out: str = "", ago_s: float = 0.0) -> Turn:
    return Turn(ts=time.time() - ago_s, cmd=cmd, out=out, exit=exit_code, dur_ms=10)


def kinds(turns: list[Turn]) -> list[str]:
    return [s.kind for s in detect.analyze(turns, CFG)]


class TestRepeat(unittest.TestCase):
    def test_threshold_reached(self):
        turns = [turn("npm run build") for _ in range(3)]
        self.assertIn("tekrar", kinds(turns))

    def test_below_threshold_silent(self):
        turns = [turn("npm run build") for _ in range(2)]
        self.assertNotIn("tekrar", kinds(turns))

    def test_whitespace_and_case_normalized(self):
        turns = [turn("npm run build"), turn("NPM   run    build"), turn("npm run build")]
        self.assertIn("tekrar", kinds(turns))

    def test_only_last_15_turns_counted(self):
        old = [turn("docker build .") for _ in range(3)]
        filler = [turn(f"echo {i}") for i in range(15)]
        self.assertNotIn("tekrar", kinds(old + filler))


class TestFailStreak(unittest.TestCase):
    def test_streak_reached(self):
        turns = [turn("go build", 1, "error: x") for _ in range(3)]
        self.assertIn("hata-serisi", kinds(turns))

    def test_single_failure_is_weak_signal(self):
        k = kinds([turn("ls"), turn("go build", 1, "error: x")])
        self.assertIn("hata", k)
        self.assertNotIn("hata-serisi", k)

    def test_streak_broken_by_success(self):
        turns = [turn("go build", 1, "error: a"), turn("go build", 1, "error: b"),
                 turn("ls")]
        self.assertNotIn("hata-serisi", kinds(turns))

    def test_all_green_is_silent(self):
        self.assertEqual(kinds([turn("ls"), turn("cd x"), turn("git status")]), [])


class TestSameError(unittest.TestCase):
    def test_same_signature_twice(self):
        err = "fatal: not a git repository (or any of the parent directories): .git"
        turns = [turn("git log", 128, err), turn("ls"), turn("git status", 128, err)]
        self.assertIn("ayni-hata", kinds(turns))

    def test_different_errors_no_signal(self):
        turns = [turn("git log", 128, "fatal: not a git repository"),
                 turn("git push", 1, "error: failed to push some refs")]
        self.assertNotIn("ayni-hata", kinds(turns))

    def test_same_error_is_strong(self):
        err = "ModuleNotFoundError: No module named 'requests'"
        sigs = detect.analyze([turn("python a.py", 1, err), turn("python b.py", 1, err)], CFG)
        same = [s for s in sigs if s.kind == "ayni-hata"]
        self.assertEqual(same[0].weight, 3)


class TestStagnation(unittest.TestCase):
    def test_long_span_without_success(self):
        turns = [turn("make", 2, "error: build failed", ago_s=1500 - i * 200)
                 for i in range(7)]
        turns[-1] = turn("make", 2, "error: build failed", ago_s=0)
        self.assertIn("durgunluk", kinds(turns))

    def test_recent_success_clears_it(self):
        turns = [turn("make", 2, "error", ago_s=1500 - i * 200) for i in range(7)]
        turns[-1] = turn("make", 0, "ok", ago_s=0)
        self.assertNotIn("durgunluk", kinds(turns))

    def test_short_span_no_signal(self):
        turns = [turn("make", 2, "error", ago_s=60 - i * 10) for i in range(6)]
        self.assertNotIn("durgunluk", kinds(turns))


class TestLeftHanging(unittest.TestCase):
    def test_old_failure_flagged(self):
        self.assertIn("asili-kalmis", kinds([turn("pytest", 1, "error: x", ago_s=3600)]))

    def test_fresh_failure_not_flagged(self):
        self.assertNotIn("asili-kalmis", kinds([turn("pytest", 1, "error: x", ago_s=10)]))


class TestScoring(unittest.TestCase):
    def test_empty_journal(self):
        self.assertEqual(detect.analyze([], CFG), [])
        self.assertFalse(detect.is_stuck([]))
        self.assertEqual(detect.summarize([]), "belirgin bir zorlanma sinyali yok")

    def test_single_failure_below_stuck_threshold(self):
        sigs = detect.analyze([turn("ls"), turn("go build", 1, "error: x")], CFG)
        self.assertFalse(detect.is_stuck(sigs), "tek hata 'takildi' sayilmamali")

    def test_fail_streak_is_stuck(self):
        sigs = detect.analyze([turn("go build", 1, "error: x") for _ in range(3)], CFG)
        self.assertTrue(detect.is_stuck(sigs))

    def test_sorted_by_weight(self):
        turns = [turn("go build", 1, "error: same") for _ in range(3)]
        weights = [s.weight for s in detect.analyze(turns, CFG)]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_config_thresholds_are_honoured(self):
        """Esikler config'ten okunmali - sabit kodlanmis olmamali."""
        loose = {"detect": {"repeat_threshold": 9, "fail_streak": 9,
                            "stagnation_minutes": 999}}
        turns = [turn("go build", 1, "error: x") for _ in range(3)]
        k = [s.kind for s in detect.analyze(turns, loose)]
        self.assertNotIn("hata-serisi", k)
        self.assertNotIn("tekrar", k)


class TestFocusTurn(unittest.TestCase):
    def test_picks_last_failure(self):
        turns = [turn("git log", 128, "fatal"), turn("ls"), turn("cd x")]
        self.assertEqual(detect.focus_turn(turns).cmd, "git log")

    def test_falls_back_to_last_turn(self):
        turns = [turn("ls"), turn("cd x")]
        self.assertEqual(detect.focus_turn(turns).cmd, "cd x")

    def test_empty(self):
        self.assertIsNone(detect.focus_turn([]))


if __name__ == "__main__":
    unittest.main()
