"""Otomatik baslatma testleri.

Kilitlenen tuzaklar:
- Idempotanlik: `enable` iki kez cagrilinca tek .lnk kalmali, cogalmamali.
- Konsol parlamasi: launch_target hedefi pythonw.exe olmali (varsa), boylece
  her acilista bir konsol penceresi cakmasin.
- Yol cozumu: Startup klasoru %APPDATA%\\...\\Startup altinda.
- Windows disinda nazik davranis: is_enabled False, enable nazik hata.

Gercek PowerShell olmadan dosya mantigini test etmek icin _create_shortcut
mock'lanir (sahte bir dosya yazar). Gercek .lnk uretimi ayri bir testte,
Windows/PowerShell yoksa skipTest ile atlanir.
"""

from __future__ import annotations

import platform
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from alleye import autostart


def _fake_create(path: Path, target):
    """Gercek WScript.Shell yerine dosya yonetimi testleri icin sahte kisayol."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fake-lnk\n" + " ".join(target), encoding="utf-8")


class TestPaths(unittest.TestCase):
    def test_startup_dir_under_appdata(self):
        with mock.patch.dict("os.environ", {"APPDATA": r"C:\Users\x\AppData\Roaming"}):
            d = autostart.startup_dir()
        parts = d.parts
        self.assertIn("Startup", parts)
        self.assertIn("Start Menu", parts)
        self.assertIn("Programs", parts)
        self.assertTrue(str(d).replace("\\", "/").endswith(
            "Microsoft/Windows/Start Menu/Programs/Startup"))

    def test_shortcut_path_uses_injected_directory(self):
        with TemporaryDirectory() as d:
            p = autostart.shortcut_path(Path(d))
            self.assertEqual(p, Path(d) / autostart.SHORTCUT_NAME)
            self.assertEqual(p.suffix, ".lnk")

    def test_shortcut_path_defaults_to_startup_dir(self):
        self.assertEqual(autostart.shortcut_path(),
                         autostart.startup_dir() / autostart.SHORTCUT_NAME)


class TestLaunchTarget(unittest.TestCase):
    def test_prefers_pythonw(self):
        """Konsol parlamasini onlemek icin pythonw.exe one gelmeli."""
        with mock.patch.object(autostart, "_pythonw", return_value=r"C:\py\pythonw.exe"):
            cmd = autostart.launch_target()
        self.assertEqual(cmd[0], r"C:\py\pythonw.exe")
        self.assertEqual(cmd[1:], ["-m", "alleye", "watch", "--tray"])

    def test_exe_fallback_when_no_pythonw(self):
        with mock.patch.object(autostart, "_pythonw", return_value=None), \
             mock.patch("shutil.which", return_value=r"C:\bin\alleye.exe"):
            cmd = autostart.launch_target()
        self.assertEqual(cmd, [r"C:\bin\alleye.exe", "watch", "--tray"])

    def test_python_fallback_when_nothing(self):
        with mock.patch.object(autostart, "_pythonw", return_value=None), \
             mock.patch("shutil.which", return_value=None):
            cmd = autostart.launch_target()
        self.assertEqual(cmd[-4:], ["-m", "alleye", "watch", "--tray"])
        self.assertTrue(cmd[0])  # sys.executable

    def test_always_targets_watch_tray(self):
        """Hangi dala girerse girsin komut 'watch --tray' ile bitmeli."""
        for pyw, which in ((r"C:\py\pythonw.exe", None),
                           (None, r"C:\bin\alleye.exe"),
                           (None, None)):
            with mock.patch.object(autostart, "_pythonw", return_value=pyw), \
                 mock.patch("shutil.which", return_value=which):
                self.assertEqual(autostart.launch_target()[-2:], ["watch", "--tray"])


class TestEnableDisable(unittest.TestCase):
    """Dosya yonetimi mantigi - gercek PowerShell yerine sahte kisayol."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        patcher = mock.patch.object(autostart, "_create_shortcut", _fake_create)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enable_then_is_enabled(self):
        self.assertFalse(autostart.is_enabled(self.dir))
        path = autostart.enable(self.dir)
        self.assertTrue(path.exists())
        self.assertTrue(autostart.is_enabled(self.dir))

    def test_disable_removes(self):
        autostart.enable(self.dir)
        self.assertTrue(autostart.disable(self.dir))
        self.assertFalse(autostart.is_enabled(self.dir))

    def test_disable_when_absent_returns_false(self):
        self.assertFalse(autostart.disable(self.dir))

    def test_enable_is_idempotent(self):
        """Iki kez enable = tek .lnk. Sabit ad cogaltmayi engeller."""
        autostart.enable(self.dir)
        autostart.enable(self.dir)
        lnks = list(self.dir.glob("*.lnk"))
        self.assertEqual(len(lnks), 1, f"kisayol cogaldi: {lnks}")

    def test_status_reflects_state(self):
        self.assertIn("kapali", autostart.status(self.dir))
        autostart.enable(self.dir)
        self.assertIn("acik", autostart.status(self.dir))


class TestNonWindows(unittest.TestCase):
    """Windows disinda: is_enabled False, enable nazik hata (traceback degil)."""

    def test_is_enabled_false_off_windows(self):
        with mock.patch.object(autostart.platform, "system", return_value="Linux"):
            self.assertFalse(autostart.is_enabled())

    def test_enable_raises_friendly_off_windows(self):
        with mock.patch.object(autostart.platform, "system", return_value="Linux"):
            with self.assertRaises(OSError):
                autostart.enable()

    def test_status_off_windows(self):
        with mock.patch.object(autostart.platform, "system", return_value="Linux"):
            self.assertIn("Windows", autostart.status())


class TestRealShortcut(unittest.TestCase):
    """Gercek .lnk uretimi. Windows + PowerShell yoksa atla."""

    def test_real_lnk_roundtrip(self):
        if not autostart._is_windows() or autostart._powershell_exe() is None:
            self.skipTest("Windows + PowerShell gerekli")
        with TemporaryDirectory() as d:
            path = autostart.enable(Path(d))
            self.assertTrue(path.exists(), "PowerShell .lnk uretmedi")
            self.assertTrue(autostart.is_enabled(Path(d)))
            # Ikinci kez: hala tek dosya (idempotan, gercek uretimle de).
            autostart.enable(Path(d))
            self.assertEqual(len(list(Path(d).glob("*.lnk"))), 1)
            self.assertTrue(autostart.disable(Path(d)))
            self.assertFalse(autostart.is_enabled(Path(d)))


if __name__ == "__main__":
    unittest.main()
