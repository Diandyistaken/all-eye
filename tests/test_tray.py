"""Tepsi ikonu: saf mantik (state_color/available) ve nazik davranis testleri.

GUI olusturma (create/destroy) yalniz Windows'ta duman testi olarak denenir;
tepsi/oturum yoksa skipTest ile atlanir - testin kendisi patlamamali.
"""

from __future__ import annotations

import platform
import unittest
from unittest import mock

from alleye import tray


class TestStateColor(unittest.TestCase):
    """state_color SAF harita: 3 durum + bilinmeyen -> sakin."""

    def test_three_states_have_distinct_colors(self):
        colors = {s: tray.state_color(s) for s in tray.STATES}
        self.assertEqual(len(set(colors.values())), 3, "her durum ayri renk olmali")

    def test_all_channels_are_valid_bytes(self):
        for s in tray.STATES:
            rgb = tray.state_color(s)
            self.assertEqual(len(rgb), 3)
            for ch in rgb:
                self.assertIsInstance(ch, int)
                self.assertGreaterEqual(ch, 0)
                self.assertLessEqual(ch, 255)

    def test_sinyal_is_warm(self):
        """Sinyal turuncu olmali: kirmizi kanal maviden belirgin buyuk."""
        r, _g, b = tray.state_color("sinyal")
        self.assertGreater(r, b)

    def test_hazir_is_green(self):
        """Hazir yesil olmali: yesil kanal baskin."""
        r, g, b = tray.state_color("hazir")
        self.assertGreater(g, r)
        self.assertGreater(g, b)

    def test_sakin_is_gray(self):
        """Sakin gri olmali: kanallar birbirine yakin."""
        r, g, b = tray.state_color("sakin")
        self.assertLessEqual(max(r, g, b) - min(r, g, b), 30)

    def test_unknown_state_falls_back_to_sakin(self):
        self.assertEqual(tray.state_color("bilinmeyen"), tray.state_color("sakin"))
        self.assertEqual(tray.state_color(""), tray.state_color("sakin"))

    def test_states_constant_matches_class(self):
        self.assertEqual(tray.STATES, ("sakin", "sinyal", "hazir"))
        self.assertEqual(tray.Tray.STATES, tray.STATES)


class TestAvailable(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(tray.available(), bool)

    def test_matches_platform(self):
        """Windows'ta True beklenir (ctypes hazir); baska yerde False."""
        if platform.system() == "Windows":
            self.assertTrue(tray.available())
        else:
            self.assertFalse(tray.available())

    def test_false_when_not_windows(self):
        with mock.patch.object(tray.platform, "system", return_value="Linux"):
            self.assertFalse(tray.available())


class TestGraceful(unittest.TestCase):
    """Windows disinda / erisim yokken nazik davranis."""

    def test_create_raises_when_unavailable(self):
        t = tray.Tray(on_ask=lambda: None)
        with mock.patch.object(tray, "available", return_value=False):
            with self.assertRaises(RuntimeError):
                t.create()

    def test_hide_show_console_are_noop_off_windows(self):
        with mock.patch.object(tray.platform, "system", return_value="Linux"):
            # Hicbir istisna cikmamali.
            self.assertIsNone(tray.hide_console())
            self.assertIsNone(tray.show_console())

    def test_pump_before_create_is_safe(self):
        t = tray.Tray()
        self.assertIsNone(t.pump())  # olusturulmadan pump -> sessiz no-op

    def test_destroy_before_create_is_safe(self):
        t = tray.Tray()
        self.assertIsNone(t.destroy())  # idempotent / no-op

    def test_set_state_before_create_only_stores(self):
        t = tray.Tray()
        t.set_state("sinyal")  # patlamamali; sadece hedef durum saklanir
        self.assertEqual(t._state, "sinyal")


class TestQueue(unittest.TestCase):
    """Callback kuyrugu: yalniz None olmayanlar sokulur."""

    def test_queue_skips_none(self):
        t = tray.Tray()
        t._queue(None)
        self.assertEqual(t._pending, [])

    def test_queue_appends_callable(self):
        t = tray.Tray()
        marker = lambda: None
        t._queue(marker)
        self.assertEqual(t._pending, [marker])


@unittest.skipUnless(platform.system() == "Windows", "tepsi yalniz Windows'ta")
class TestSmoke(unittest.TestCase):
    """Gercek create()/set_state/pump/destroy dumani. Tepsi yoksa skip."""

    def test_lifecycle(self):
        if not tray.available():
            self.skipTest("tepsi erisilebilir degil")
        t = tray.Tray(on_ask=lambda: None, tooltip="all eye test")
        try:
            t.create()
        except (RuntimeError, OSError) as exc:
            self.skipTest(f"tepsi ikonu olusturulamadi (bassiz ortam?): {exc}")
        try:
            for state in tray.STATES:
                t.set_state(state)
            t.pump()  # bloklamamali, aninda donmeli
        finally:
            t.destroy()
            t.destroy()  # ikinci destroy da guvenli olmali


if __name__ == "__main__":
    unittest.main()
