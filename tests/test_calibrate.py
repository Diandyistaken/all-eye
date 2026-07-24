"""alleye calibrate icin kilit testler.

Kapsam: analyze_history gecici bir tur listesinde sinyal/takilma/kendi-cozmus
sayimini dogru mu yapiyor; suggest_thresholds yuksek yanlis alarmda esikleri
yukseltiyor mu, dusuk/az veride dokunmuyor ya da sikilastiriyor mu.
"""

from __future__ import annotations

import time
import unittest

from alleye import calibrate
from alleye.journal import Turn

CFG = {"detect": {"repeat_threshold": 3, "fail_streak": 3, "stagnation_minutes": 20}}


def turn(cmd: str, exit_code: int = 0, out: str = "", ago_s: float = 0.0) -> Turn:
    return Turn(ts=time.time() - ago_s, cmd=cmd, out=out, exit=exit_code, dur_ms=10)


class TestAnalyzeHistory(unittest.TestCase):
    def test_empty_journal(self):
        stats = calibrate.analyze_history([], CFG)
        self.assertEqual(stats, {"windows": 0, "signals": 0, "stuck": 0,
                                  "self_resolved": 0, "rate": 0.0})

    def test_no_failures_no_signal(self):
        # Farkli komutlar - "ls" gibi tek komutu 3+ kez tekrarlamak basli
        # basina "tekrar" sinyali dogurur, bu test onu istemiyor.
        cmds = ["ls", "cd x", "git status", "npm test", "echo hi", "pwd"]
        turns = [turn(c, ago_s=30 - i * 5) for i, c in enumerate(cmds)]
        stats = calibrate.analyze_history(turns, CFG)
        self.assertEqual(stats["signals"], 0)
        self.assertEqual(stats["stuck"], 0)
        self.assertEqual(stats["rate"], 0.0)

    def test_stuck_episode_counted_once_and_self_resolved(self):
        # 3 ardisik FARKLI hata -> tam esikte (fail_streak=3) "takildin" olusur;
        # hemen ardindan basarili bir komut gelir -> kendi cozmus sayilmali.
        turns = [
            turn("go build", 1, "error: a", ago_s=300),
            turn("go build", 1, "error: b", ago_s=200),
            turn("go build", 1, "error: c", ago_s=100),
            turn("go build", 0, "ok", ago_s=10),
        ]
        stats = calibrate.analyze_history(turns, CFG)
        self.assertEqual(stats["stuck"], 1, "takilma olayi bir kez sayilmali (gecis)")
        self.assertEqual(stats["self_resolved"], 1)
        self.assertEqual(stats["rate"], 1.0)

    def test_stuck_without_resolution(self):
        turns = [
            turn("go build", 1, "error: a", ago_s=300),
            turn("go build", 1, "error: b", ago_s=200),
            turn("go build", 1, "error: c", ago_s=100),
        ]
        stats = calibrate.analyze_history(turns, CFG)
        self.assertEqual(stats["stuck"], 1)
        self.assertEqual(stats["self_resolved"], 0)
        self.assertEqual(stats["rate"], 0.0)


class TestSuggestThresholds(unittest.TestCase):
    def test_no_data_returns_empty(self):
        stats = {"windows": 5, "signals": 0, "stuck": 0, "self_resolved": 0, "rate": 0.0}
        self.assertEqual(calibrate.suggest_thresholds(stats, CFG), {})

    def test_high_false_alarm_raises_thresholds(self):
        stats = {"windows": 10, "signals": 5, "stuck": 4, "self_resolved": 3, "rate": 0.75}
        out = calibrate.suggest_thresholds(stats, CFG)
        self.assertEqual(out, {
            "repeat_threshold": 4,
            "fail_streak": 4,
            "stagnation_minutes": 30,
        })

    def test_low_false_alarm_with_enough_data_lowers_thresholds(self):
        stats = {"windows": 20, "signals": 6, "stuck": 5, "self_resolved": 0, "rate": 0.0}
        out = calibrate.suggest_thresholds(stats, CFG)
        self.assertEqual(out, {"fail_streak": 2, "stagnation_minutes": 15})
        self.assertNotIn("repeat_threshold", out, "sadece degisen anahtar donmeli")

    def test_moderate_rate_touches_nothing(self):
        stats = {"windows": 10, "signals": 3, "stuck": 3, "self_resolved": 1,
                  "rate": 1 / 3}
        self.assertEqual(calibrate.suggest_thresholds(stats, CFG), {})

    def test_only_changed_keys_returned_when_already_at_range_limit(self):
        cfg = {"detect": {"repeat_threshold": 6, "fail_streak": 6, "stagnation_minutes": 60}}
        stats = {"windows": 10, "signals": 4, "stuck": 4, "self_resolved": 4, "rate": 1.0}
        out = calibrate.suggest_thresholds(stats, cfg)
        self.assertEqual(out, {}, "zaten tavandaysa oneri uretmemeli")


if __name__ == "__main__":
    unittest.main()
