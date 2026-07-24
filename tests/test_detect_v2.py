"""Pasif tespit v2 - yavaslama ve dongu sinyalleri.

Faz 2 sozlesmesi geregi minimal testler: sadece ELZEM davranisi kilitler.
Mevcut sinyalleri de (tests/test_detect.py) bozmadigimizi burada da kisaca
teyit ederiz.
"""

from __future__ import annotations

import time
import unittest

from alleye import detect
from alleye.journal import Turn

CFG = {"detect": {"repeat_threshold": 3, "fail_streak": 3, "stagnation_minutes": 20,
                   "slowdown_factor": 2.5, "loop_window_s": 90}}


def turn(cmd: str, exit_code: int = 0, out: str = "", ago_s: float = 0.0) -> Turn:
    return Turn(ts=time.time() - ago_s, cmd=cmd, out=out, exit=exit_code, dur_ms=10)


def kinds(turns: list[Turn], cfg: dict = CFG) -> list[str]:
    return [s.kind for s in detect.analyze(turns, cfg)]


class TestSlowdown(unittest.TestCase):
    def test_growing_interval_triggers(self):
        # eski araliklar ~5sn, yeni araliklar ~20sn -> ~4x yavaslama
        ago = [75, 70, 65, 60, 40, 20, 0]
        turns = [turn("git status", ago_s=a) for a in ago]
        self.assertIn("yavaslama", kinds(turns))

    def test_constant_interval_silent(self):
        # sabit 10sn aralik - yavaslama yok
        ago = [60, 50, 40, 30, 20, 10, 0]
        turns = [turn("git status", ago_s=a) for a in ago]
        self.assertNotIn("yavaslama", kinds(turns))

    def test_too_few_turns_silent(self):
        # pencereyi ikiye bolecek kadar veri yok (< 6 tur)
        turns = [turn("git status", ago_s=a) for a in [20, 10, 0]]
        self.assertNotIn("yavaslama", kinds(turns))

    def test_slowdown_factor_from_config(self):
        # ayni veri, ama esik cok yuksek tutulursa tetiklenmemeli
        ago = [75, 70, 65, 60, 40, 20, 0]
        turns = [turn("git status", ago_s=a) for a in ago]
        loose = {"detect": {**CFG["detect"], "slowdown_factor": 50}}
        self.assertNotIn("yavaslama", kinds(turns, loose))


class TestLoop(unittest.TestCase):
    def test_same_cmd_same_error_short_gap_triggers(self):
        err = "ModuleNotFoundError: No module named 'requests'"
        turns = [turn("python app.py", 1, err, ago_s=a) for a in [80, 40, 0]]
        self.assertIn("dongu", kinds(turns))

    def test_different_errors_no_loop_signal(self):
        turns = [turn("python app.py", 1, "TypeError: x", ago_s=80),
                 turn("python app.py", 1, "ValueError: y", ago_s=40),
                 turn("python app.py", 1, "KeyError: z", ago_s=0)]
        self.assertNotIn("dongu", kinds(turns))

    def test_wide_gap_no_loop_signal(self):
        # ayni hata ama araliklar loop_window_s'in cok uzerinde - klasik dongu degil
        err = "error: build failed"
        turns = [turn("make", 2, err, ago_s=a) for a in [1000, 500, 0]]
        self.assertNotIn("dongu", kinds(turns))

    def test_loop_window_from_config(self):
        err = "error: build failed"
        turns = [turn("make", 2, err, ago_s=a) for a in [80, 40, 0]]
        tight = {"detect": {**CFG["detect"], "loop_window_s": 10}}
        self.assertNotIn("dongu", kinds(turns, tight))


class TestExistingSignalsStillWork(unittest.TestCase):
    def test_repeat_signal_unaffected(self):
        turns = [turn("npm run build") for _ in range(3)]
        self.assertIn("tekrar", kinds(turns))

    def test_fail_streak_and_loop_can_coexist(self):
        turns = [turn("go build", 1, "error: x", ago_s=a) for a in [80, 40, 0]]
        k = kinds(turns)
        self.assertIn("hata-serisi", k)
        self.assertIn("dongu", k)


if __name__ == "__main__":
    unittest.main()
