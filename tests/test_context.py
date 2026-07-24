"""Baglam toplama: son dokunulan dosyalar ve butce kirpma.

recent_files ana klasorde ya da surucu kokunde CALISMAMALI. Orada os.walk
saniyeler suruyor ve `ae` cagrisi kilitleniyor - sinyalden once gelen sessiz
bir gecikme, kullanicinin araci kapatma sebebi.
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from alleye import context


class RecentFilesCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def touch(self, rel: str, ago_min: float = 0.0) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        when = time.time() - ago_min * 60
        os.utime(p, (when, when))
        return p


class TestGuards(RecentFilesCase):
    def test_home_directory_returns_empty(self):
        self.assertEqual(context.recent_files(os.path.expanduser("~")), "")

    def test_drive_root_returns_empty(self):
        root = Path(os.path.abspath(os.sep)).anchor
        self.assertEqual(context.recent_files(root), "")

    def test_is_home_or_root_helper(self):
        self.assertTrue(context._is_home_or_root(Path(os.path.expanduser("~"))))
        self.assertTrue(context._is_home_or_root(Path(os.path.abspath(os.sep))))
        self.assertFalse(context._is_home_or_root(self.root))

    def test_nonexistent_dir_does_not_crash(self):
        self.assertEqual(context.recent_files(str(self.root / "yok")), "")

    def test_home_guard_actually_skips_walk(self):
        """Ana klasor korumasinin GERCEKTEN taramayi kestigini deterministik
        dogrula: gecici dizine taze bir dosya koy, _is_home_or_root'u True'ya
        zorla -> koruma devreye girer ve bos doner. Koruma kalkarsa (mutasyon
        `if False`) taze dosya listelenir ve bu test kirmiziya duser. Gercek home
        dizininin anlik icerigine bagli DEGIL - o yuzden guvenilir bir kilit."""
        self.touch("app.py", ago_min=1)
        # koruma olmasa app.py kesin listelenirdi:
        self.assertIn("app.py", context.recent_files(str(self.root)))
        with mock.patch.object(context, "_is_home_or_root", return_value=True):
            self.assertEqual(context.recent_files(str(self.root)), "")


class TestTimeWindow(RecentFilesCase):
    def test_recent_file_listed(self):
        self.touch("app.py", ago_min=2)
        self.assertIn("app.py", context.recent_files(str(self.root), minutes=45))

    def test_old_file_excluded(self):
        self.touch("eski.py", ago_min=120)
        self.touch("yeni.py", ago_min=1)
        out = context.recent_files(str(self.root), minutes=45)
        self.assertIn("yeni.py", out)
        self.assertNotIn("eski.py", out)

    def test_window_is_configurable(self):
        self.touch("orta.py", ago_min=30)
        self.assertNotIn("orta.py", context.recent_files(str(self.root), minutes=10))
        self.assertIn("orta.py", context.recent_files(str(self.root), minutes=60))

    def test_newest_first(self):
        self.touch("ucuncu.py", ago_min=30)
        self.touch("ikinci.py", ago_min=10)
        self.touch("birinci.py", ago_min=1)
        lines = context.recent_files(str(self.root)).splitlines()
        self.assertEqual(lines, ["birinci.py", "ikinci.py", "ucuncu.py"])

    def test_limit_respected(self):
        for i in range(20):
            self.touch(f"f{i:02d}.py", ago_min=i * 0.1)
        self.assertEqual(len(context.recent_files(str(self.root), limit=5).splitlines()), 5)


class TestSkipping(RecentFilesCase):
    def test_noise_directories_skipped(self):
        self.touch("node_modules/lodash/index.js", ago_min=1)
        self.touch("__pycache__/app.cpython-312.pyc", ago_min=1)
        self.touch(".venv/Lib/site.py", ago_min=1)
        self.touch("src/app.py", ago_min=1)
        out = context.recent_files(str(self.root))
        self.assertNotIn("node_modules", out)
        self.assertNotIn("__pycache__", out)
        self.assertNotIn(".venv", out)
        self.assertIn("app.py", out)

    def test_hidden_directories_skipped(self):
        self.touch(".git/COMMIT_EDITMSG", ago_min=1)
        self.touch("main.py", ago_min=1)
        out = context.recent_files(str(self.root))
        self.assertNotIn("COMMIT_EDITMSG", out)
        self.assertIn("main.py", out)

    def test_paths_are_relative(self):
        self.touch("src/deep/mod.py", ago_min=1)
        out = context.recent_files(str(self.root))
        self.assertNotIn(str(self.root), out)
        self.assertIn("mod.py", out)

    def test_time_budget_stops_the_walk(self):
        """Butce sifir olursa tarama hemen kesilmeli - kilitlenme yok."""
        for i in range(30):
            self.touch(f"d{i}/f.py", ago_min=1)
        start = time.monotonic()
        context.recent_files(str(self.root), budget_s=0.0)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_dir_cap_stops_the_walk(self):
        for i in range(10):
            self.touch(f"d{i}/f.py", ago_min=1)
        out = context.recent_files(str(self.root), max_dirs=1)
        self.assertEqual(out, "", "klasor siniri uygulanmadi")


class TestGitContext(unittest.TestCase):
    def test_non_repo_returns_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(context.git_context(tmp), "")


if __name__ == "__main__":
    unittest.main()
