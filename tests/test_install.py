"""Hook kurulumu: alintilama, idempotanlik ve "config.json yazma" kurali.

Ters bolu tuzagi: profile yol yazarken json.dumps kullanilirsa
C:\\Users\\... -> "C:\\\\Users\\\\..." olur. PowerShell'de ters bolu kacis
karakteri DEGIL, dolayisiyla profildeki yol bozulur ve hook hic yuklenmez.
Sessiz hata: kullanici "kurdum" der, hicbir komut kaydedilmez.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from alleye import cli, config, install

REAL_PATH = r"C:\Users\mo_ma\AppData\Local\AllEye\hooks\alleye.ps1"


class TestPsQuote(unittest.TestCase):
    def test_backslashes_not_doubled(self):
        quoted = install._ps_quote(REAL_PATH)
        self.assertEqual(quoted, f"'{REAL_PATH}'")
        self.assertNotIn("\\\\", quoted)

    def test_differs_from_json_dumps(self):
        """json.dumps'a geri donulurse bu test kirmiziya duser."""
        self.assertNotEqual(install._ps_quote(REAL_PATH), json.dumps(REAL_PATH))

    def test_single_quote_escaped_powershell_style(self):
        self.assertEqual(install._ps_quote("C:\\it's here"), "'C:\\it''s here'")

    def test_spaces_survive(self):
        p = r"C:\dev\Projeler\All Eye\.venv\Scripts\alleye.exe"
        self.assertEqual(install._ps_quote(p), f"'{p}'")

    def test_ps_array(self):
        out = install._ps_array([r"C:\py\python.exe", "-m", "alleye"])
        self.assertEqual(out, r"@('C:\py\python.exe', '-m', 'alleye')")
        self.assertNotIn("\\\\", out)

    def test_dot_source_line_is_usable(self):
        line = install.dot_source_line()
        self.assertTrue(line.startswith(". '"))
        self.assertNotIn("\\\\", line)
        self.assertIn("alleye.ps1", line)

    def test_sh_cmd_quoting(self):
        self.assertEqual(install._sh_cmd(["/usr/bin/py", "-m", "alleye"]),
                         '"/usr/bin/py" "-m" "alleye"')


class TestSplice(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.profile = Path(self._tmp.name) / "profile.ps1"
        self.block = f"{install.BEGIN}\n. 'C:\\AllEye\\hooks\\alleye.ps1'\n{install.END}\n"

    def test_creates_profile(self):
        self.assertTrue(install._splice(self.profile, self.block, force=False))
        self.assertIn(install.BEGIN, self.profile.read_text(encoding="utf-8"))

    def test_idempotent(self):
        install._splice(self.profile, self.block, force=False)
        self.assertFalse(install._splice(self.profile, self.block, force=False),
                         "ikinci kurulum degisiklik yapmis - blok cogaliyor olabilir")
        self.assertEqual(self.profile.read_text(encoding="utf-8").count(install.BEGIN), 1)

    def test_existing_content_preserved(self):
        self.profile.write_text("Import-Module posh-git\nSet-Alias ll Get-ChildItem\n",
                                encoding="utf-8")
        install._splice(self.profile, self.block, force=False)
        text = self.profile.read_text(encoding="utf-8")
        self.assertIn("Import-Module posh-git", text)
        self.assertIn(install.BEGIN, text)

    def test_backup_written_once(self):
        self.profile.write_text("orijinal\n", encoding="utf-8")
        install._splice(self.profile, self.block, force=False)
        backup = self.profile.with_suffix(".ps1.alleye-bak")
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), "orijinal\n")
        install._splice(self.profile, self.block + "\n# degisti\n", force=True)
        self.assertEqual(backup.read_text(encoding="utf-8"), "orijinal\n",
                         "yedek ezilmis - orijinal profil kaybolur")

    def test_block_updated_not_duplicated(self):
        install._splice(self.profile, self.block, force=False)
        new_block = f"{install.BEGIN}\n. 'D:\\Yeni\\alleye.ps1'\n{install.END}\n"
        self.assertTrue(install._splice(self.profile, new_block, force=False))
        text = self.profile.read_text(encoding="utf-8")
        self.assertEqual(text.count(install.BEGIN), 1)
        self.assertIn("D:\\Yeni", text)
        self.assertNotIn("C:\\AllEye", text)

    def test_bom_profile_is_read(self):
        self.profile.write_text("Import-Module posh-git\n", encoding="utf-8-sig")
        install._splice(self.profile, self.block, force=False)
        text = self.profile.read_text(encoding="utf-8")
        self.assertIn("Import-Module posh-git", text)
        self.assertFalse(text.startswith("﻿"))

    def test_uninstall_removes_block(self):
        self.profile.write_text("onceki\n", encoding="utf-8")
        install._splice(self.profile, self.block, force=False)
        self.assertTrue(install.uninstall(self.profile))
        text = self.profile.read_text(encoding="utf-8")
        self.assertNotIn(install.BEGIN, text)
        self.assertIn("onceki", text)
        self.assertFalse(install.uninstall(self.profile), "ikinci kaldirma True dondu")


class TestMaterialize(unittest.TestCase):
    """Hook sablonu diske yazilirken placeholder gercek komutla degismeli."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_powershell_hook_placeholder_replaced(self):
        with mock.patch.object(config, "HOME", self.home):
            dest = install._materialize("alleye.ps1", "@@ALLEYE_CMD@@",
                                        install._ps_array([r"C:\dev\alleye.exe"]))
        text = dest.read_text(encoding="utf-8")
        self.assertNotIn("@@ALLEYE_CMD@@", text)
        self.assertIn(r"@('C:\dev\alleye.exe')", text)
        self.assertNotIn("\\\\", text.splitlines()[9])

    def test_bash_hook_placeholder_replaced(self):
        with mock.patch.object(config, "HOME", self.home):
            dest = install._materialize("alleye.bash", "@@ALLEYE_CMD_SH@@",
                                        install._sh_cmd(["/usr/bin/alleye"]))
        self.assertNotIn("@@ALLEYE_CMD_SH@@", dest.read_text(encoding="utf-8"))

    def test_install_does_not_write_config_json(self):
        """`alleye install` config.json YAZMAMALI. Varsayilanlari diske
        dondurmak, sonraki surumlerdeki duzeltmelerin (olu model adlari gibi)
        kullaniciya hic ulasmamasina yol aciyor."""
        with mock.patch.object(config, "HOME", self.home), \
             mock.patch.object(config, "CONFIG_FILE", self.home / "config.json"):
            install._materialize("alleye.ps1", "@@ALLEYE_CMD@@", "@('alleye')")
            install._materialize("alleye.bash", "@@ALLEYE_CMD_SH@@", '"alleye"')
            self.assertFalse((self.home / "config.json").exists())

    def test_nobody_calls_write_default_config(self):
        """Statik ag: biri tekrar cagirirsa burada yakalanir."""
        pkg = Path(install.__file__).parent
        offenders = []
        for py in pkg.rglob("*.py"):
            if py.name == "config.py":
                continue
            if "write_default_config(" in py.read_text(encoding="utf-8"):
                offenders.append(py.name)
        self.assertEqual(offenders, [], f"config.json yaziliyor: {offenders}")


class TestHookLiveDetection(unittest.TestCase):
    """Bazi terminaller PowerShell'i -NoProfile ile aciyor; o zaman hook hic
    yuklenmez ve hicbir komut kaydedilmez. Tek isaret bu ortam degiskeni."""

    def setUp(self):
        self._old = os.environ.get("ALLEYE_HOOK_LOADED")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old is None:
            os.environ.pop("ALLEYE_HOOK_LOADED", None)
        else:
            os.environ["ALLEYE_HOOK_LOADED"] = self._old

    def test_detected_when_set(self):
        os.environ["ALLEYE_HOOK_LOADED"] = "1"
        self.assertTrue(cli._hook_live())

    def test_not_detected_when_absent(self):
        os.environ.pop("ALLEYE_HOOK_LOADED", None)
        self.assertFalse(cli._hook_live())

    def test_hook_scripts_set_the_flag(self):
        hooks = Path(install.HOOK_SRC)
        self.assertIn("ALLEYE_HOOK_LOADED",
                      (hooks / "alleye.ps1").read_text(encoding="utf-8"))
        self.assertIn("ALLEYE_HOOK_LOADED",
                      (hooks / "alleye.bash").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
