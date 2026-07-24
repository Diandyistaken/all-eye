"""PowerShell hook'unun canli davranisi - gercek powershell.exe ile.

Bu dosya TEK bir tuzak icin var ve o tuzak bu projeyi bir kez sessizce bozdu:

    $LASTEXITCODE cmdlet'ler tarafindan GUNCELLENMEZ.

Yani bir cmdlet hata verdiginde $LASTEXITCODE hala onceki NATIVE komuttan
kalma bayat degeri tasir. Hook bunu iki testle cozuyor: deger degisti mi, ve
komut gercekten harici bir program mi. Bu mantik kaldirilirsa `git status`in
128'i sonraki her cmdlet hatasina yapisir ve mentor yanlis hatayi analiz eder.

`prompt` fonksiyonu ancak interaktif kabukta calisir, o yuzden Get-History
sahtelenip AllEye-Record dogrudan cagriliyor.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from alleye import config, install

DRIVER = r"""
$ErrorActionPreference = 'Continue'
$env:ALLEYE_HOME = $env:ALLEYE_TEST_HOME
. $env:ALLEYE_TEST_HOOK

# Get-History interaktif olmayan kabukta bos doner; sahtesini koyuyoruz.
$global:FakeId  = 100
$global:FakeCmd = ''
function global:Get-History {
    param([int]$Count)
    [pscustomobject]@{
        Id                 = $global:FakeId
        CommandLine        = $global:FakeCmd
        StartExecutionTime = (Get-Date).AddMilliseconds(-42)
        EndExecutionTime   = (Get-Date)
    }
}

function Step([string]$cmd, [bool]$ok, $lec) {
    $global:FakeId++
    $global:FakeCmd = $cmd
    AllEye-Record $ok $lec
}

# 1) Harici program hata verdi. Transcript'e once komut yankisi, sonra hata.
Write-Output 'git status'
Write-Output 'fatal: not a git repository (or any of the parent directories): .git'
Step 'git status' $false 128

# 2) Hemen ardindan bir CMDLET hatasi. $LASTEXITCODE hala 128 - BAYAT.
Step 'Get-Item C:\yok-boyle-bir-dosya' $false 128

# 3) Basarili komut.
Step 'Write-Output merhaba' $true 128

# 4-5) Kendi cagrilarimiz: geri besleme dongusu olmasin diye kaydedilmemeli.
Step 'ae neden olmadi' $false 1
Step 'alleye status' $false 1

# 6) Tek satirlik hata: komut yankisi korlemesine atilirsa bu satir kaybolur.
Write-Output 'curl: (7) Failed to connect to localhost port 8080'
Step 'curl http://localhost:8080' $false 7

Stop-Transcript *> $null
"""


@unittest.skipUnless(platform.system() == "Windows", "sadece Windows")
class TestPowerShellHook(unittest.TestCase):
    records: list[dict] = []

    @classmethod
    def setUpClass(cls):
        exe = shutil.which("powershell") or shutil.which("pwsh")
        if not exe:
            raise unittest.SkipTest("powershell bulunamadi")

        cls._tmp = TemporaryDirectory()
        home = Path(cls._tmp.name)
        with mock.patch.object(config, "HOME", home):
            hook = install._materialize(
                "alleye.ps1", "@@ALLEYE_CMD@@", install._ps_array(["alleye"]))

        driver = home / "driver.ps1"
        driver.write_text(DRIVER, encoding="utf-8", newline="\r\n")

        env = dict(os.environ)
        env.pop("ALLEYE_HOOK_LOADED", None)  # yuklu gorunurse hook hemen return eder
        env["ALLEYE_TEST_HOME"] = str(home)
        env["ALLEYE_TEST_HOOK"] = str(hook)

        proc = subprocess.run(
            [exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
            capture_output=True, text=True, timeout=120, env=env,
            encoding="utf-8", errors="replace")

        journal = home / "journal.jsonl"
        if not journal.exists():
            raise AssertionError(
                f"hook journal yazmadi.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        cls.records = [json.loads(line) for line in
                       journal.read_text(encoding="utf-8").splitlines() if line.strip()]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def rec(self, cmd_starts_with: str) -> dict:
        for r in self.records:
            if r["cmd"].startswith(cmd_starts_with):
                return r
        self.fail(f"kayit yok: {cmd_starts_with} · var olanlar: "
                  f"{[r['cmd'] for r in self.records]}")

    # --- cikis kodu ------------------------------------------------------

    def test_native_exit_code_captured(self):
        self.assertEqual(self.rec("git status")["exit"], 128)

    def test_stale_exit_code_does_not_leak_into_cmdlet_error(self):
        """TUZAK: cmdlet hatasindan sonra onceki native komutun 128'i okunur."""
        rec = self.rec("Get-Item")
        self.assertEqual(rec["exit"], 1,
                         "bayat $LASTEXITCODE sizdi - cmdlet hatasi 128 olarak kaydedilmis")

    def test_success_is_zero(self):
        self.assertEqual(self.rec("Write-Output merhaba")["exit"], 0)

    def test_fresh_native_exit_code_trusted(self):
        self.assertEqual(self.rec("curl")["exit"], 7)

    # --- geri besleme filtresi -------------------------------------------

    def test_own_calls_not_recorded(self):
        cmds = [r["cmd"] for r in self.records]
        self.assertNotIn("ae neden olmadi", cmds)
        self.assertNotIn("alleye status", cmds)

    def test_only_expected_records_written(self):
        self.assertEqual(len(self.records), 4, [r["cmd"] for r in self.records])

    # --- cikti dilimleme -------------------------------------------------

    def test_output_captured(self):
        self.assertIn("not a git repository", self.rec("git status")["out"])

    def test_command_echo_stripped(self):
        out = self.rec("git status")["out"]
        self.assertFalse(out.startswith("git status"), f"komut yankisi kalmis: {out!r}")

    def test_single_line_error_survives(self):
        """Yanki satiri korlemesine atilirsa tek satirlik hatalar - en degerli
        sey - tamamen kaybolur."""
        self.assertIn("Failed to connect", self.rec("curl")["out"])

    # --- kayit bicimi ----------------------------------------------------

    def test_record_shape(self):
        rec = self.rec("git status")
        for field in ("ts", "session", "shell", "cwd", "cmd", "exit", "dur_ms",
                      "out", "truncated"):
            self.assertIn(field, rec)
        self.assertEqual(rec["shell"], "powershell")
        self.assertGreater(rec["ts"], 1_700_000_000)
        self.assertFalse(rec["truncated"])

    def test_session_id_shared(self):
        sessions = {r["session"] for r in self.records}
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions.pop()), 12)

    def test_journal_is_utf8_without_bom(self):
        raw = (Path(self._tmp.name) / "journal.jsonl").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "journal BOM ile yazilmis")

    def test_parsed_by_journal_module(self):
        """Hook'un yazdigini okuyucu gercekten anlamali - iki uc birbirini tutsun."""
        from alleye import journal as journal_mod
        turns = journal_mod.read(path=Path(self._tmp.name) / "journal.jsonl")
        self.assertEqual([t.cmd for t in turns][0], "git status")
        self.assertTrue(turns[0].failed)
        self.assertEqual(turns[0].exit, 128)


if __name__ == "__main__":
    unittest.main()
