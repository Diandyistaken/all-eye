"""Gunluk okuma ve hata imzasi.

Imza, duvar hafizasinin temeli: "bu duvara N. kez carpiyorsun" iddiasi
imzanin kararli olmasina bagli. Dosya yolu ya da bir port numarasi degisince
imza degisirse sayac hep 1'de kalir ve ozellik sessizce olur.
"""

from __future__ import annotations

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alleye import journal
from alleye.journal import Turn


def turn(cmd: str, out: str = "", exit_code: int = 1) -> Turn:
    return Turn(ts=time.time(), cmd=cmd, out=out, exit=exit_code)


# Gercek bir PowerShell hata blogu: ilk satirlar gurultu, is gorecek satir sonda.
PS_ERROR = (
    "At line:1 char:1\n"
    "+ Get-Item C:\\dev\\Projeler\\yok\\a.txt\n"
    "+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
    "    + CategoryInfo          : ObjectNotFound: (C:\\dev\\yok:String) "
    "[Get-Item], ItemNotFoundException\n"
    "    + FullyQualifiedErrorId : PathNotFound,Microsoft.PowerShell.Commands.GetItemCommand\n"
    "Get-Item : Cannot find path 'C:\\dev\\Projeler\\yok\\a.txt' because it does not exist."
)


class TestFingerprint(unittest.TestCase):
    def test_powershell_noise_lines_skipped(self):
        """'At ...' ve '+ ...' satirlari imzaya girmemeli.

        '+ CategoryInfo ... ItemNotFoundException' satiri 'exception' anahtar
        kelimesini icerir; gurultu filtresi kalkarsa imza O satirdan uretilir
        ve gercek hata mesaji kaybolur.
        """
        fp = journal.fingerprint(turn("Get-Item C:\\dev\\Projeler\\yok\\a.txt", PS_ERROR))
        self.assertIn("cannot find path", fp)
        self.assertNotIn("categoryinfo", fp)
        self.assertNotIn("fullyqualifiederrorid", fp)
        self.assertNotIn("at line", fp)
        self.assertNotIn("~", fp)

    def test_stable_across_different_paths(self):
        other = PS_ERROR.replace("a.txt", "bambaska.txt").replace(
            "C:\\dev\\Projeler\\yok", "D:\\baska\\klasor")
        a = journal.fingerprint(turn("Get-Item C:\\dev\\Projeler\\yok\\a.txt", PS_ERROR))
        b = journal.fingerprint(turn("Get-Item D:\\baska\\klasor\\bambaska.txt", other))
        self.assertEqual(a, b, "yol degisince imza degisti - duvar sayaci calismaz")

    def test_stable_across_numbers(self):
        a = journal.fingerprint(turn("curl localhost:8080", "curl: (7) Failed to connect to port 8080"))
        b = journal.fingerprint(turn("curl localhost:3000", "curl: (7) Failed to connect to port 3000"))
        self.assertEqual(a, b)
        self.assertIn("<n>", a)

    def test_different_errors_differ(self):
        a = journal.fingerprint(turn("git push", "fatal: Authentication failed"))
        b = journal.fingerprint(turn("git push", "error: failed to push some refs"))
        self.assertNotEqual(a, b)

    def test_command_is_part_of_signature(self):
        a = journal.fingerprint(turn("git push", "fatal: Authentication failed"))
        b = journal.fingerprint(turn("docker push", "fatal: Authentication failed"))
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("git::"))
        self.assertTrue(b.startswith("docker::"))

    def test_silent_failure_still_gets_signature(self):
        """Cikti yoksa bile imza uretilmeli - sessiz basarisizlik da bir duvardir."""
        fp = journal.fingerprint(turn("./build.sh", "", exit_code=2))
        self.assertEqual(fp, "./build.sh::exit2")

    def test_signature_length_capped(self):
        long_err = "error: " + "x" * 900
        fp = journal.fingerprint(turn("make", long_err))
        self.assertLessEqual(len(fp), 160 + len("make::"))

    def test_empty_command_does_not_crash(self):
        self.assertTrue(journal.fingerprint(Turn(ts=0, cmd="", out="", exit=1)))


class TestRead(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "journal.jsonl"
        self.addCleanup(self._tmp.cleanup)

    def write(self, records: list[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def rec(self, cmd: str, **kw) -> dict:
        d = {"ts": time.time(), "session": "s1", "shell": "powershell",
             "cwd": "C:\\dev", "cmd": cmd, "exit": 0, "dur_ms": 5, "out": ""}
        d.update(kw)
        return d

    def test_missing_file_returns_empty(self):
        self.assertEqual(journal.read(path=Path(self._tmp.name) / "yok.jsonl"), [])

    def test_own_calls_are_filtered(self):
        """Kendi cagrilarimiz gunluge girerse geri besleme dongusu olusur."""
        self.write([self.rec("git status"), self.rec("alleye status"),
                    self.rec("python -m alleye ask"), self.rec("ls")])
        cmds = [t.cmd for t in journal.read(path=self.path)]
        self.assertEqual(cmds, ["git status", "ls"])

    def test_broken_line_skipped(self):
        with self.path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(self.rec("git status")) + "\n")
            fh.write("{bozuk json\n")
            fh.write(json.dumps(self.rec("ls")) + "\n")
        self.assertEqual([t.cmd for t in journal.read(path=self.path)], ["git status", "ls"])

    def test_limit_keeps_newest(self):
        self.write([self.rec(f"cmd{i}") for i in range(30)])
        turns = journal.read(limit=5, path=self.path)
        self.assertEqual([t.cmd for t in turns], [f"cmd{i}" for i in range(25, 30)])

    def test_session_filter(self):
        self.write([self.rec("a", session="s1"), self.rec("b", session="s2")])
        self.assertEqual([t.cmd for t in journal.read(session="s2", path=self.path)], ["b"])

    def test_ansi_codes_stripped(self):
        self.write([self.rec("ls", out="\x1b[31mkirmizi\x1b[0m hata")])
        self.assertEqual(journal.read(path=self.path)[0].out, "kirmizi hata")

    def test_failed_property(self):
        self.write([self.rec("git status", exit=128)])
        t = journal.read(path=self.path)[0]
        self.assertTrue(t.failed)
        self.assertEqual(t.exit, 128)


if __name__ == "__main__":
    unittest.main()
