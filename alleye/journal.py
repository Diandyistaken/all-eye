"""Shell gunlugu okuyucu.

Kayitlari hook'lar yaziyor (hooks/alleye.ps1, hooks/alleye.bash). Her satir
bir komut turu: ne calistirdin, hangi dizinde, kac saniye surdu, cikis kodu ne,
ve -PowerShell'de- ciktisi neydi.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from alleye import config

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass
class Turn:
    ts: float
    cmd: str
    cwd: str = ""
    exit: int = 0
    dur_ms: int = 0
    out: str = ""
    shell: str = "powershell"
    session: str = ""
    truncated: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def failed(self) -> bool:
        return self.exit != 0

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.ts)


def _clean(text: str) -> str:
    return _ANSI.sub("", text or "").replace("\r\n", "\n").strip()


def _parse(line: str) -> Turn | None:
    try:
        d = json.loads(line)
    except json.JSONDecodeError:
        return None
    cmd = _clean(d.get("cmd", ""))
    if not cmd:
        return None
    return Turn(
        ts=float(d.get("ts") or 0),
        cmd=cmd,
        cwd=d.get("cwd", ""),
        exit=int(d.get("exit") or 0),
        dur_ms=int(d.get("dur_ms") or 0),
        out=_clean(d.get("out", "")),
        shell=d.get("shell", "powershell"),
        session=d.get("session", ""),
        truncated=bool(d.get("truncated")),
        raw=d,
    )


def read(limit: int = 50, session: str | None = None, path: Path | None = None) -> list[Turn]:
    """Son `limit` komutu, en eskiden yeniye sirali dondurur."""
    path = path or config.JOURNAL
    if not path.exists():
        return []
    # Dosyanin sonundan geriye oku; gunluk buyudukce tamamini yuklemeyelim.
    tail = _tail_lines(path, limit * 3 + 40)
    turns: list[Turn] = []
    for line in tail:
        t = _parse(line)
        if t is None:
            continue
        if session and t.session != session:
            continue
        if t.cmd.lower().startswith(("alleye", "python -m alleye", "py -m alleye")):
            continue  # kendi cagrilarimiz geri besleme yapmasin
        turns.append(t)
    return turns[-limit:]


def _tail_lines(path: Path, n: int, block: int = 65536) -> list[str]:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        data = b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(block, size)
            size -= step
            fh.seek(size)
            data = fh.read(step) + data
    return data.decode("utf-8", "replace").splitlines()


def current_session(turns: list[Turn]) -> str:
    return turns[-1].session if turns else ""


def fingerprint(turn: Turn) -> str:
    """Hatanin kimligi: yol/sayi/hex gurultusu temizlenmis imza.

    Ayni duvara tekrar tekrar carptigini bu sayede anlariz.
    """
    base = turn.cmd.split()[0] if turn.cmd.split() else turn.cmd
    err = ""
    for line in turn.out.splitlines():
        # PowerShell'in gurultu satirlari: "At C:\...", "+ ~~~~", "+ CategoryInfo"
        stripped = line.strip()
        if not stripped or stripped.startswith(("+", "At ")):
            continue
        low = stripped.lower()
        if any(k in low for k in ("error", "exception", "not found", "denied", "refused",
                                  "failed", "fatal", "cannot", "no such", "traceback",
                                  "hata", "bulunamadi", "unable")):
            err = stripped
            break
    if not err and turn.out:
        err = turn.out.splitlines()[0]
    if not err:
        err = f"exit{turn.exit}"  # sessiz basarisizlik da bir imzadir
    err = re.sub(r"[A-Za-z]:\\[^\s\"']+|/[^\s\"']{4,}", "<path>", err)
    err = re.sub(r"\b0x[0-9a-fA-F]+\b|\b\d{2,}\b", "<n>", err)
    err = re.sub(r"\s+", " ", err).strip().lower()[:160]
    return f"{base}::{err}"
