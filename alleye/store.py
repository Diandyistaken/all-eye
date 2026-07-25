"""Kalici hafiza.

Bu, All Eye'i mevcut projelerden ayiran kisim: her takilma olayi imzasiyla
kaydedilir. Ayni duvara dorduncu kez carptiginda mentor bunu bilir ve
"gecen sefer sunu yapmistin" diyebilir.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from alleye import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS asks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    cwd       TEXT,
    level     INTEGER NOT NULL,
    trigger   TEXT,
    signature TEXT,
    question  TEXT,
    answer    TEXT,
    provider  TEXT,
    model     TEXT
);
CREATE TABLE IF NOT EXISTS walls (
    signature TEXT PRIMARY KEY,
    first_ts  REAL NOT NULL,
    last_ts   REAL NOT NULL,
    hits      INTEGER NOT NULL DEFAULT 1,
    cmd       TEXT,
    resolved  INTEGER NOT NULL DEFAULT 0,
    note      TEXT
);
CREATE INDEX IF NOT EXISTS asks_sig ON asks(signature);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or config.DB
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def record_ask(con: sqlite3.Connection, *, cwd: str, level: int, trigger: str,
               signature: str, question: str, answer: str,
               provider: str, model: str) -> int:
    cur = con.execute(
        "INSERT INTO asks (ts, cwd, level, trigger, signature, question, answer, provider, model)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (time.time(), cwd, level, trigger, signature, question, answer, provider, model),
    )
    con.commit()
    return int(cur.lastrowid or 0)


def touch_wall(con: sqlite3.Connection, signature: str, cmd: str) -> int:
    """Imzayi kaydet/say. Bu duvara kacinci carpis oldugunu dondurur."""
    if not signature:
        return 0
    now = time.time()
    row = con.execute("SELECT hits FROM walls WHERE signature=?", (signature,)).fetchone()
    if row:
        hits = int(row["hits"]) + 1
        con.execute("UPDATE walls SET last_ts=?, hits=?, resolved=0 WHERE signature=?",
                    (now, hits, signature))
    else:
        hits = 1
        con.execute("INSERT INTO walls (signature, first_ts, last_ts, hits, cmd) VALUES (?,?,?,?,?)",
                    (signature, now, now, 1, cmd))
    con.commit()
    return hits


def wall_history(con: sqlite3.Connection, signature: str, limit: int = 2) -> list[sqlite3.Row]:
    """Ayni imzayla daha once verilmis cevaplar - mentorun 'gecen sefer' hafizasi."""
    if not signature:
        return []
    return con.execute(
        "SELECT ts, level, answer FROM asks WHERE signature=? ORDER BY ts DESC LIMIT ?",
        (signature, limit),
    ).fetchall()


def resolve_wall(con: sqlite3.Connection, signature: str, note: str = "") -> None:
    con.execute("UPDATE walls SET resolved=1, note=? WHERE signature=?", (note, signature))
    con.commit()


def last_wall(con: sqlite3.Connection) -> sqlite3.Row | None:
    """En son carpilan duvar (last_ts en yeni). `teach` bunu hedefler.

    Siralama last_ts'e gore olmali; hits'e gore olsa 'en cok carptigin' duvari
    dondurur ve kullanici az once takildigi duvara not birakamaz.
    """
    return con.execute(
        "SELECT * FROM walls ORDER BY last_ts DESC LIMIT 1"
    ).fetchone()


def get_note(con: sqlite3.Connection, signature: str) -> str:
    """Bu imza icin daha once birakilmis kullanici notu; yoksa "".

    resolved bayragina bakmaz: duvara yeniden carpilinca touch_wall resolved'i
    0'a ceker ama notu silmez; asil deger de o tekrar aninda notu gostermek.
    """
    if not signature:
        return ""
    row = con.execute("SELECT note FROM walls WHERE signature=?", (signature,)).fetchone()
    if row is None:
        return ""
    return row["note"] or ""


def teach_wall(con: sqlite3.Connection, signature: str, note: str) -> bool:
    """Duvari cozulmus isaretle ve notu yaz. Bir satir guncellendiyse True.

    Imza bilinmiyorsa (henuz hic carpilmamis) False doner - cagiran taraf
    'once bir hataya takil' diyebilsin.
    """
    if not signature:
        return False
    cur = con.execute(
        "UPDATE walls SET resolved=1, note=? WHERE signature=?", (note, signature)
    )
    con.commit()
    return cur.rowcount > 0


def top_walls(con: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT signature, hits, cmd, first_ts, last_ts, resolved FROM walls"
        " ORDER BY hits DESC, last_ts DESC LIMIT ?", (limit,),
    ).fetchall()


def stats(con: sqlite3.Connection) -> dict:
    a = con.execute("SELECT COUNT(*) c FROM asks").fetchone()["c"]
    w = con.execute("SELECT COUNT(*) c FROM walls").fetchone()["c"]
    r = con.execute("SELECT COUNT(*) c FROM walls WHERE resolved=1").fetchone()["c"]
    return {"asks": a, "walls": w, "resolved": r}


def export_json(con: sqlite3.Connection, redact_notes: bool = True) -> str:
    """Duvarlari disa aktar (Faz 4.4). Notlar kullanicinin yazdigi SERBEST
    METIN - sir icerebilir, o yuzden varsayilan olarak redaksiyondan gecer."""
    rows = [dict(r) for r in con.execute("SELECT * FROM walls ORDER BY hits DESC")]
    if redact_notes:
        from alleye import redact as _redact
        for r in rows:
            if r.get("note"):
                r["note"] = _redact.redact(r["note"])[0]
    return json.dumps(rows, indent=2, ensure_ascii=False)


def import_json(con: sqlite3.Connection, text: str) -> dict:
    """Disa aktarilmis duvarlari ice al. VERI KAYBI YOK.

    Cakisma kurallari (makine degistirince gecmis kaybolmasin):
      - ayni imza varsa `hits` TOPLANIR (iki makinede de carpmissin)
      - mevcut not doluysa KORUNUR; bossa gelen not yazilir
      - `resolved` OR'lanir (bir yerde cozduysen cozulmustur)
      - `first_ts` en eski, `last_ts` en yeni kazanir
    Don: {"eklenen": N, "birlesen": M, "atlanan": K}
    """
    try:
        rows = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"gecersiz JSON: {exc}") from None
    if not isinstance(rows, list):
        raise ValueError("beklenen bicim: duvar listesi (JSON dizisi)")

    added = merged = skipped = 0
    for r in rows:
        if not isinstance(r, dict):
            skipped += 1
            continue
        sig = (r.get("signature") or "").strip()
        if not sig:
            skipped += 1
            continue
        hits = int(r.get("hits") or 1)
        first_ts = float(r.get("first_ts") or time.time())
        last_ts = float(r.get("last_ts") or first_ts)
        cmd = r.get("cmd") or ""
        note = r.get("note") or ""
        resolved = 1 if r.get("resolved") else 0

        cur = con.execute(
            "SELECT hits, first_ts, last_ts, note, resolved FROM walls WHERE signature=?",
            (sig,)).fetchone()
        if cur is None:
            con.execute(
                "INSERT INTO walls (signature, first_ts, last_ts, hits, cmd, resolved, note)"
                " VALUES (?,?,?,?,?,?,?)",
                (sig, first_ts, last_ts, hits, cmd, resolved, note or None))
            added += 1
        else:
            con.execute(
                "UPDATE walls SET hits=?, first_ts=?, last_ts=?, resolved=?, note=?"
                " WHERE signature=?",
                (int(cur["hits"]) + hits,
                 min(float(cur["first_ts"]), first_ts),
                 max(float(cur["last_ts"]), last_ts),
                 1 if (cur["resolved"] or resolved) else 0,
                 cur["note"] or note or None,
                 sig))
            merged += 1
    con.commit()
    return {"eklenen": added, "birlesen": merged, "atlanan": skipped}
