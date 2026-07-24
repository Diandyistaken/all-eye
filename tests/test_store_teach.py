"""teach + walls: kullanicinin kendi cozumunu hatirlama.

Duvar hafizasi bu faza kadar sadece sayiyordu. Simdi kullanici bir duvari
cozunce notunu birakabiliyor ve ayni imza tekrar edince mentor once o notu
gosteriyor. Bu testler asil tuzagi kilitler: `last_wall` yanlis duvari
hedeflerse teach notu baska bir hataya yapisir; `get_note` resolved bayragina
takilirsa tekrar aninda not kaybolur.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from alleye import context, store


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.con = store.connect(Path(self._tmp.name) / "eye.db")
        self.addCleanup(self.con.close)


class TestLastWall(StoreCase):
    def test_empty_db_returns_none(self):
        """Hic duvar yokken last_wall None; teach 'once hataya takil' diyebilsin."""
        self.assertIsNone(store.last_wall(self.con))

    def test_returns_most_recently_hit(self):
        """En yeni last_ts kazanmali - hits'e gore siralanirsa yanlis duvar doner.

        sig-a daha cok carpilmis ama sig-b daha yakinda carpilmis; kullanici az
        once takildigi (sig-b) duvara not birakmak ister.
        """
        store.touch_wall(self.con, "sig-a", "git push")
        store.touch_wall(self.con, "sig-a", "git push")  # hits=2
        store.touch_wall(self.con, "sig-b", "docker up")  # hits=1, en yeni
        # Zaman damgalarini deterministik yap: sig-a eski, sig-b yeni.
        self.con.execute("UPDATE walls SET last_ts=? WHERE signature=?", (1000.0, "sig-a"))
        self.con.execute("UPDATE walls SET last_ts=? WHERE signature=?", (2000.0, "sig-b"))
        self.con.commit()
        last = store.last_wall(self.con)
        self.assertIsNotNone(last)
        self.assertEqual(last["signature"], "sig-b")


class TestTeachWall(StoreCase):
    def test_sets_resolved_and_note(self):
        store.touch_wall(self.con, "sig-x", "make")
        ok = store.teach_wall(self.con, "sig-x", "PATH'e node ekle")
        self.assertTrue(ok)
        row = self.con.execute(
            "SELECT resolved, note FROM walls WHERE signature=?", ("sig-x",)
        ).fetchone()
        self.assertEqual(row["resolved"], 1)
        self.assertEqual(row["note"], "PATH'e node ekle")

    def test_unknown_signature_returns_false(self):
        """Hic carpilmamis imzaya teach basarisiz - satir yok, guncelleme yok."""
        self.assertFalse(store.teach_wall(self.con, "yok-boyle-imza", "not"))

    def test_empty_signature_returns_false(self):
        self.assertFalse(store.teach_wall(self.con, "", "not"))


class TestGetNote(StoreCase):
    def test_returns_taught_note(self):
        store.touch_wall(self.con, "sig-n", "curl")
        store.teach_wall(self.con, "sig-n", "sunucuyu once baslat")
        self.assertEqual(store.get_note(self.con, "sig-n"), "sunucuyu once baslat")

    def test_unknown_signature_returns_empty(self):
        self.assertEqual(store.get_note(self.con, "hic-yok"), "")

    def test_untaught_wall_returns_empty(self):
        """Carpilmis ama ogretilmemis duvarin notu None - "" olarak gelmeli."""
        store.touch_wall(self.con, "sig-bos", "ls")
        self.assertEqual(store.get_note(self.con, "sig-bos"), "")

    def test_empty_signature_returns_empty(self):
        self.assertEqual(store.get_note(self.con, ""), "")

    def test_note_survives_rehit(self):
        """Duvara yeniden carpilinca (resolved 0'a doner) not gene gelmeli.

        Asil ozellik bu: tekrar carpma aninda kullanicinin eski notunu
        hatirlatmak. get_note resolved=1 sartina baglanirsa not kaybolur.
        """
        store.touch_wall(self.con, "sig-r", "pytest")
        store.teach_wall(self.con, "sig-r", "sanal ortami aktive et")
        hits = store.touch_wall(self.con, "sig-r", "pytest")  # resolved -> 0
        self.assertEqual(hits, 2)
        resolved = self.con.execute(
            "SELECT resolved FROM walls WHERE signature=?", ("sig-r",)
        ).fetchone()["resolved"]
        self.assertEqual(resolved, 0)
        self.assertEqual(store.get_note(self.con, "sig-r"), "sanal ortami aktive et")


class TestExistingApiIntact(StoreCase):
    def test_resolve_wall_still_works(self):
        store.touch_wall(self.con, "sig-res", "npm i")
        store.resolve_wall(self.con, "sig-res", "kilit dosyasini sil")
        row = self.con.execute(
            "SELECT resolved, note FROM walls WHERE signature=?", ("sig-res",)
        ).fetchone()
        self.assertEqual(row["resolved"], 1)
        self.assertEqual(row["note"], "kilit dosyasini sil")

    def test_top_walls_still_works(self):
        store.touch_wall(self.con, "sig-1", "a")
        store.touch_wall(self.con, "sig-2", "b")
        store.touch_wall(self.con, "sig-2", "b")  # hits=2, en tepede olmali
        rows = store.top_walls(self.con, limit=10)
        self.assertEqual(rows[0]["signature"], "sig-2")
        self.assertEqual(rows[0]["hits"], 2)


class TestBundleField(unittest.TestCase):
    def test_bundle_has_user_note(self):
        """Bundle'a user_note alani eklendi (varsayilan bos)."""
        b = context.Bundle(cwd=".", system="x", signals=[], turns=[], focus=None)
        self.assertEqual(b.user_note, "")


class TestThreadedRecord(StoreCase):
    """daemon._answer_window kalibi: baglam ana thread'de kurulur, ama cevap
    window.show_answer tarafindan AYRI worker thread'de akitilir ve record_ask
    o thread'de cagrilir.

    Senior lead denetiminin yakaladigi KRITIK tuzak: bir sqlite baglantisi
    olusturuldugu thread'e baglidir. Ana thread'de acilan baglanti worker
    thread'den kullanilirsa sqlite3.ProgrammingError firlar ve duvar hafizasi
    sessizce yazilamaz. Dogru kalip: her thread kendi taze baglantisini acar.
    """

    def _db(self) -> Path:
        return Path(self._tmp.name) / "eye.db"

    def test_main_thread_connection_fails_in_worker(self):
        """Tuzagi belgele: ana thread baglantisi worker'dan kullanilinca patlar.
        Bu gercek dogru degilse _answer_window'daki iki-baglanti kalibi gereksiz."""
        import sqlite3
        import threading

        errors: list[str] = []

        def work():
            try:
                store.record_ask(self.con, cwd="x", level=1, trigger="tray",
                                 signature="s", question="q", answer="a",
                                 provider="p", model="m")
            except sqlite3.ProgrammingError:
                errors.append("programming")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"other:{exc!r}")

        t = threading.Thread(target=work)
        t.start()
        t.join()
        self.assertEqual(errors, ["programming"],
                         "ana thread baglantisi worker'dan sorunsuz kullanildi - "
                         "iki-baglanti kalibinin gerekcesi degisti")

    def test_fresh_connection_in_worker_records(self):
        """Dogru kalip: worker thread kendi baglantisini acar -> kayit gecer."""
        import threading

        errors: list[str] = []
        path = self._db()

        def work():
            try:
                wcon = store.connect(path)
                try:
                    store.record_ask(wcon, cwd="C:\\x", level=1, trigger="tray",
                                     signature="git::x", question="(oto)",
                                     answer="cevap", provider="gemini", model="m")
                finally:
                    wcon.close()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        t = threading.Thread(target=work)
        t.start()
        t.join()
        self.assertEqual(errors, [], f"worker thread kaydi patladi: {errors}")
        con = store.connect(path)
        self.addCleanup(con.close)
        self.assertEqual(store.stats(con)["asks"], 1)


if __name__ == "__main__":
    unittest.main()
