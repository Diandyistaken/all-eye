"""Faz 5: siber guvenlik modu - saf mantik testleri.

En kritik iki davranis: (1) niyet algisi - kullanici tam cozum istedigini
belli edince kademe 3'e atlamak; (2) "neyi denemedin" - bulunan ama
dokunulmayan yuzeyleri gercekten yakalamak. Ikisi de saf fonksiyon, GUI/ag
gerekmez.
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alleye import box, store
from alleye.journal import Turn


def turn(cmd: str, out: str = "", ago_s: float = 0.0, exit_code: int = 0) -> Turn:
    return Turn(ts=time.time() - ago_s, cmd=cmd, out=out, exit=exit_code)


NMAP_OUT = """Starting Nmap 7.94
Nmap scan report for 10.10.11.42
PORT      STATE SERVICE       VERSION
22/tcp    open  ssh           OpenSSH 8.2p1 Ubuntu
80/tcp    open  http          nginx 1.18.0
5985/tcp  open  wsman         Microsoft HTTPAPI httpd 2.0
139/tcp   closed netbios-ssn
445/tcp   open  microsoft-ds  Windows Server 2019
"""

GOBUSTER_OUT = """===============================================================
/admin                (Status: 200) [Size: 1234]
/login                (Status: 302) [Size: 0]
/secret               (Status: 403) [Size: 12]
/nope                 (Status: 404) [Size: 9]
"""


class TestTargetDetection(unittest.TestCase):
    def test_finds_ip(self):
        self.assertEqual(box.find_target([turn("nmap -sV 10.10.11.42")]), "10.10.11.42")

    def test_finds_htb_host(self):
        self.assertEqual(box.find_target([turn("gobuster dir -u http://forest.htb")]),
                         "forest.htb")

    def test_ignores_loopback(self):
        self.assertIsNone(box.find_target([turn("curl http://127.0.0.1:8000")]))

    def test_latest_target_wins(self):
        turns = [turn("nmap 10.10.11.42"), turn("nmap 10.10.11.99")]
        self.assertEqual(box.find_target(turns), "10.10.11.99")


class TestPentestContext(unittest.TestCase):
    def test_aggressive_tool_alone_triggers(self):
        self.assertTrue(box.is_pentest_context([turn("nmap -p- 10.10.11.42")]))
        self.assertTrue(box.is_pentest_context([turn("gobuster dir -u http://x")]))

    def test_normal_shell_is_not_pentest(self):
        turns = [turn("git status"), turn("npm run build"), turn("ls -la")]
        self.assertFalse(box.is_pentest_context(turns))

    def test_curl_to_lab_target_triggers(self):
        self.assertTrue(box.is_pentest_context([turn("curl http://10.10.11.42:8080")]))

    def test_curl_to_random_site_alone_does_not(self):
        self.assertFalse(box.is_pentest_context([turn("curl https://example.com")]))

    def test_multiple_tools_trigger(self):
        turns = [turn("smbclient -L //x"), turn("nc -nv host 80")]
        self.assertTrue(box.is_pentest_context(turns))


class TestParseNmap(unittest.TestCase):
    def test_open_ports_extracted_with_version(self):
        f = box.parse_nmap(NMAP_OUT)
        vals = {x.value: x.detail for x in f}
        self.assertIn("22/tcp", vals)
        self.assertIn("OpenSSH 8.2p1 Ubuntu", vals["22/tcp"])
        self.assertIn("5985/tcp", vals)

    def test_closed_ports_skipped(self):
        vals = {x.value for x in box.parse_nmap(NMAP_OUT)}
        self.assertNotIn("139/tcp", vals)

    def test_all_are_port_kind(self):
        self.assertTrue(all(x.kind == "port" for x in box.parse_nmap(NMAP_OUT)))


class TestParseWebPaths(unittest.TestCase):
    def test_paths_extracted(self):
        vals = {x.value for x in box.parse_web_paths(GOBUSTER_OUT)}
        self.assertIn("/admin", vals)
        self.assertIn("/secret", vals)   # 403 ilginc, atlanmamali

    def test_404_skipped(self):
        vals = {x.value for x in box.parse_web_paths(GOBUSTER_OUT)}
        self.assertNotIn("/nope", vals)

    def test_ffuf_style(self):
        ffuf = "admin                   [Status: 200, Size: 100, Words: 1]"
        vals = {x.value for x in box.parse_web_paths(ffuf)}
        self.assertTrue(any("admin" in v for v in vals))


class TestUntouched(unittest.TestCase):
    def test_undiscovered_surface_flagged(self):
        turns = [turn("nmap 10.10.11.42", NMAP_OUT, ago_s=100)]
        found = box.collect_findings(turns)
        vals = {f.value for f in box.untouched(found, turns)}
        # Hicbirine dokunulmadi -> hepsi denenmemis listesinde olmali.
        self.assertIn("5985/tcp", vals)
        self.assertIn("22/tcp", vals)

    def test_touched_surface_not_flagged(self):
        turns = [
            turn("nmap 10.10.11.42", NMAP_OUT, ago_s=100),
            turn("curl http://10.10.11.42:80", ago_s=50),   # 80'e dokundu
        ]
        found = box.collect_findings(turns)
        untried_vals = {f.value for f in box.untouched(found, turns)}
        self.assertNotIn("80/tcp", untried_vals)   # dokunuldu
        self.assertIn("5985/tcp", untried_vals)    # hala dokunulmadi

    def test_path_touched(self):
        turns = [
            turn("gobuster dir -u http://10.10.11.42", GOBUSTER_OUT, ago_s=100),
            turn("curl http://10.10.11.42/admin", ago_s=50),
        ]
        found = box.collect_findings(turns)
        untried_vals = {f.value for f in box.untouched(found, turns)}
        self.assertNotIn("/admin", untried_vals)
        self.assertIn("/secret", untried_vals)

    def test_only_later_commands_count_as_touch(self):
        """Kesiften ONCEKI komut dokunma sayilmaz - siralama onemli."""
        turns = [
            turn("curl http://10.10.11.42:80", ago_s=100),      # kesiften ONCE
            turn("nmap 10.10.11.42", NMAP_OUT, ago_s=50),
        ]
        found = box.collect_findings(turns)
        untried_vals = {f.value for f in box.untouched(found, turns)}
        self.assertIn("80/tcp", untried_vals)   # once dokunuldu ama sonra degil


class TestInferLevel(unittest.TestCase):
    def test_full_solution_requests_jump_to_3(self):
        for q in ["tam cozum ver", "cozumu goster", "nasil root olurum",
                  "exploit'i ver", "just give me the answer", "reverse shell nasil",
                  "spoiler ver", "payload nedir"]:
            with self.subTest(q=q):
                self.assertEqual(box.infer_level(q), 3)

    def test_direction_requests_give_2(self):
        for q in ["hangi yontem", "nereden baslamaliyim", "next step ne"]:
            with self.subTest(q=q):
                self.assertEqual(box.infer_level(q), 2)

    def test_hint_and_default_is_1(self):
        self.assertEqual(box.infer_level("ipucu ver"), 1)
        self.assertEqual(box.infer_level("takildim"), 1)
        self.assertEqual(box.infer_level(""), 1)
        self.assertEqual(box.infer_level("burada neler oluyor"), 1)

    def test_full_beats_hint_when_both_present(self):
        self.assertEqual(box.infer_level("ipucu degil tam cozum ver"), 3)

    def test_custom_default(self):
        self.assertEqual(box.infer_level("belirsiz soru", default=2), 2)


class TestPhase(unittest.TestCase):
    def test_recon_before_findings(self):
        self.assertEqual(box.phase([], [turn("nmap 10.10.11.42")]), "kesif")

    def test_enumeration_with_findings(self):
        turns = [turn("nmap x", NMAP_OUT)]
        found = box.collect_findings(turns)
        self.assertEqual(box.phase(found, turns), "enumerasyon")

    def test_privesc_phase(self):
        turns = [turn("nmap x", NMAP_OUT), turn("evil-winrm -i 10.10.11.42 -u admin")]
        found = box.collect_findings(turns)
        self.assertEqual(box.phase(found, turns), "somuru/yetki-yukseltme")


class TestRenderBox(unittest.TestCase):
    def test_untouched_section_comes_first(self):
        turns = [turn("nmap x", NMAP_OUT)]
        found = box.collect_findings(turns)
        text = box.render_box("10.10.11.42", found, box.untouched(found, turns), "enumerasyon")
        self.assertIn("HENUZ DENENMEYEN", text)
        self.assertLess(text.index("DENENMEYEN"), text.index("ACIK PORTLAR"))


class TestBoxSession(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.con = store.connect(Path(self._tmp.name) / "eye.db")
        self.addCleanup(self.con.close)

    def test_start_and_active(self):
        store.box_start(self.con, "forest", target="10.10.11.42")
        active = store.box_active(self.con)
        self.assertEqual(active["name"], "forest")
        self.assertEqual(active["target"], "10.10.11.42")

    def test_only_one_active(self):
        store.box_start(self.con, "a")
        store.box_start(self.con, "b")
        self.assertEqual(store.box_active(self.con)["name"], "b")

    def test_findings_deduped(self):
        turns = [turn("nmap x", NMAP_OUT)]
        found = box.collect_findings(turns)
        store.box_start(self.con, "forest")
        n1 = store.box_record_findings(self.con, "forest", found)
        n2 = store.box_record_findings(self.con, "forest", found)   # tekrar
        self.assertGreater(n1, 0)
        self.assertEqual(n2, 0)   # ayni yuzeyler tekrar eklenmedi

    def test_notes_accumulate(self):
        store.box_start(self.con, "forest")
        store.box_add_note(self.con, "forest", "ilk not")
        store.box_add_note(self.con, "forest", "ikinci not")
        notes = store.box_active(self.con)["notes"]
        self.assertIn("ilk not", notes)
        self.assertIn("ikinci not", notes)


if __name__ == "__main__":
    unittest.main()
