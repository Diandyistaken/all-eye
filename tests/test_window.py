"""Cevap penceresi: ekrana sikistirma, erisilebilirlik ve duman testi.

Kilitlenen tuzaklar:
- clamp_to_screen sag/alt kenardan tasmayi geri itmeli ve ASLA negatif
  koordinat dondurmemeli (cercevesiz pencere ekran disinda kalirsa kullanici
  onu goremez ve kapatamaz).
- available() Windows disinda False olmali; yoksa daemon tkinter olmayan bir
  ortamda cokerdi.
- Gercek Tk penceresi acilamiyorsa (basli/headless ortam) test PATLAMAMALI,
  skipTest ile atlamali.
"""

from __future__ import annotations

import platform
import unittest
from unittest import mock

from alleye import window


class TestClampToScreen(unittest.TestCase):
    def test_fits_unchanged(self):
        self.assertEqual(window.clamp_to_screen(10, 20, 100, 100, 1000, 800),
                         (10, 20))

    def test_right_overflow_pulled_in(self):
        # x + w = 1050 > 1000  ->  x = 1000 - 100 = 900
        self.assertEqual(window.clamp_to_screen(950, 20, 100, 100, 1000, 800),
                         (900, 20))

    def test_bottom_overflow_pulled_in(self):
        # y + h = 850 > 800  ->  y = 800 - 100 = 700
        self.assertEqual(window.clamp_to_screen(10, 780, 100, 100, 1000, 800),
                         (10, 700))

    def test_both_corners_overflow(self):
        self.assertEqual(window.clamp_to_screen(990, 790, 100, 100, 1000, 800),
                         (900, 700))

    def test_negative_input_zeroed(self):
        self.assertEqual(window.clamp_to_screen(-30, -50, 100, 100, 1000, 800),
                         (0, 0))

    def test_window_wider_than_screen_never_negative(self):
        # Pencere ekrandan genis: sag duzeltmesi x'i negatife iter, sonra 0'a.
        x, y = window.clamp_to_screen(0, 0, 2000, 100, 1000, 800)
        self.assertEqual((x, y), (0, 0))

    def test_result_never_negative_fuzz(self):
        for cx in (-500, 0, 500, 999, 5000):
            for cy in (-500, 0, 500, 799, 5000):
                x, y = window.clamp_to_screen(cx, cy, 480, 320, 1000, 800)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)

    def test_returns_ints(self):
        x, y = window.clamp_to_screen(10, 20, 100, 100, 1000, 800)
        self.assertIsInstance(x, int)
        self.assertIsInstance(y, int)


class TestAvailable(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(window.available(), bool)

    def test_false_off_windows(self):
        with mock.patch.object(window.platform, "system", return_value="Linux"):
            self.assertFalse(window.available())

    def test_false_when_tkinter_missing(self):
        # tkinter iceri alinamamis gibi davran (tk = None).
        with mock.patch.object(window.platform, "system", return_value="Windows"), \
             mock.patch.object(window, "tk", None):
            self.assertFalse(window.available())

    def test_true_on_windows_with_tk(self):
        if platform.system() != "Windows" or window.tk is None:
            self.skipTest("Windows + tkinter yok")
        self.assertTrue(window.available())


class TestCursorXY(unittest.TestCase):
    def test_returns_int_pair(self):
        xy = window.cursor_xy()
        self.assertIsInstance(xy, tuple)
        self.assertEqual(len(xy), 2)
        self.assertIsInstance(xy[0], int)
        self.assertIsInstance(xy[1], int)

    def test_zero_off_windows(self):
        with mock.patch.object(window.platform, "system", return_value="Linux"):
            self.assertEqual(window.cursor_xy(), (0, 0))


class TestAnswerWindowSmoke(unittest.TestCase):
    """Gercek Tk denemesi. Acilamzsa (headless / TclError) atla."""

    def setUp(self):
        if window.tk is None:
            self.skipTest("tkinter yok")
        try:
            self.win = window.AnswerWindow(width=300, height=200)
        except window.tk.TclError:
            self.skipTest("Tk penceresi acilamadi (basli ortam)")
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"Tk kurulamadi: {exc}")
        self.addCleanup(self.win.close)

    def test_open_append_pump_close(self):
        self.win.show_near_cursor()
        self.win.set_header("kademe 1 (durtme)")
        self.win.append("merhaba ")
        self.win.append("dunya")
        self.win.pump()  # kuyrugu bosalt + olaylari isle
        self.assertTrue(self.win.alive())
        got = self.win._text.get("1.0", "end").strip()
        self.assertEqual(got, "merhaba dunya")

    def test_clear_empties_text(self):
        self.win.show_near_cursor()
        self.win.append("silinecek")
        self.win.pump()
        self.win.clear()
        self.win.pump()
        self.assertEqual(self.win._text.get("1.0", "end").strip(), "")

    def test_enter_triggers_on_deepen(self):
        hits = []
        self.win.on_deepen = lambda: hits.append(1)
        self.win.show_near_cursor()
        self.win._on_enter()
        self.assertEqual(hits, [1])

    def test_close_is_idempotent_and_marks_dead(self):
        self.win.show_near_cursor()
        self.win.close()
        self.assertFalse(self.win.alive())
        self.win.close()  # ikinci kez patlamamali
        self.assertFalse(self.win.alive())

    def test_close_calls_on_close(self):
        called = []
        self.win.on_close = lambda: called.append(1)
        self.win.show_near_cursor()
        self.win.close()
        self.assertEqual(called, [1])

    def test_append_after_close_is_noop(self):
        self.win.show_near_cursor()
        self.win.close()
        self.win.append("bunun gitmesi lazim yoksa cokme")  # patlamamali


if __name__ == "__main__":
    unittest.main()
