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


def export_json(con: sqlite3.Connection) -> str:
    rows = [dict(r) for r in con.execute("SELECT * FROM walls ORDER BY hits DESC")]
    return json.dumps(rows, indent=2, ensure_ascii=False)
