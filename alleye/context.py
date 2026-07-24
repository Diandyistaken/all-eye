"""Baglam toplayici.

Tasarim ilkesi: zeka modelde degil baglamda. Ucuzdan pahaliya sirayla toplariz
ve butceyi asmadan modele en bilgilendirici kesiti veririz. Ekran goruntusu
burada YOK - terminal odakli cekirdekte ihtiyac duyulmuyor.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from alleye import config, detect, journal, redact
from alleye.detect import Signal
from alleye.journal import Turn


@dataclass
class Bundle:
    cwd: str
    system: str
    signals: list[Signal]
    turns: list[Turn]
    focus: Turn | None
    git: str = ""
    files: str = ""
    signature: str = ""
    wall_hits: int = 0
    history: list[str] = field(default_factory=list)
    user_note: str = ""
    redacted: list[str] = field(default_factory=list)


def _run(args: list[str], cwd: str, timeout: float = 3.0) -> str:
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        return (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def git_context(cwd: str) -> str:
    if not _run(["git", "rev-parse", "--is-inside-work-tree"], cwd).startswith("true"):
        return ""
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    status = _run(["git", "status", "--porcelain=v1", "--branch"], cwd)
    stat = _run(["git", "diff", "--stat", "HEAD"], cwd)
    last = _run(["git", "log", "-3", "--oneline"], cwd)
    parts = [f"branch: {branch}"]
    if status:
        parts.append("status:\n" + "\n".join(status.splitlines()[:25]))
    if stat:
        parts.append("degisiklikler:\n" + "\n".join(stat.splitlines()[:20]))
    if last:
        parts.append("son commitler:\n" + last)
    return "\n".join(parts)


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", ".next", "target", ".mypy_cache", ".pytest_cache",
             "OneDrive", "AppData", "Downloads", "Videos", "Music", "Pictures"}


def _is_home_or_root(path: Path) -> bool:
    """Ana klasor veya surucu koku: burayi taramak hem yavas hem anlamsiz."""
    return path == Path(os.path.expanduser("~")) or path == path.parent


def recent_files(cwd: str, minutes: int = 45, limit: int = 12,
                 budget_s: float = 1.5, max_dirs: int = 600) -> str:
    """Son X dakikada dokundugun dosyalar - uzerinde calistigin sey bu.

    Sure ve klasor sayisi siniri sart: kullanici ana klasorunde ya da devasa
    bir agacta `ae` cagirdiginda tarama tum deneyimi kilitler.
    """
    root = Path(cwd)
    if _is_home_or_root(root):
        return ""

    cutoff = time.time() - minutes * 60
    deadline = time.monotonic() + budget_s
    found: list[tuple[float, str]] = []
    seen_dirs = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
            seen_dirs += 1
            if seen_dirs > max_dirs or time.monotonic() > deadline or len(found) > 400:
                break
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m >= cutoff:
                    found.append((m, str(p.relative_to(root))))
    except OSError:
        return ""
    found.sort(reverse=True)
    return "\n".join(n for _, n in found[:limit])


def active_window() -> str:
    """Windows'ta on plandaki pencerenin basligi. Daemon yolunda ise yarar."""
    if platform.system() != "Windows":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.windll.user32
        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return ""
        n = u32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u32.GetWindowTextW(hwnd, buf, n + 1)
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return f"{buf.value} (pid {pid.value})"
    except Exception:
        return ""


def build(cwd: str | None = None, con=None) -> Bundle:
    cfg = config.load()
    cwd = cwd or os.getcwd()
    turns = journal.read(limit=cfg["context"]["turns"])
    signals = detect.analyze(turns, cfg)
    focus = detect.focus_turn(turns)

    b = Bundle(
        cwd=cwd,
        system=f"{platform.system()} {platform.release()} · python {platform.python_version()}",
        signals=signals,
        turns=turns,
        focus=focus,
        git=git_context(cwd),
        files=recent_files(cwd),
    )
    if focus:
        b.signature = journal.fingerprint(focus)
    if con is not None and b.signature:
        from alleye import store
        b.wall_hits = store.touch_wall(con, b.signature, focus.cmd if focus else "")
        b.user_note = store.get_note(con, b.signature)
        for row in store.wall_history(con, b.signature, limit=2):
            when = time.strftime("%d.%m %H:%M", time.localtime(row["ts"]))
            b.history.append(f"({when}, seviye {row['level']}) {row['answer'][:400]}")
    return b


def render(b: Bundle, question: str = "") -> str:
    """Bundle'i modele gidecek metne cevirir. Butce asilirsa eskiden keser."""
    cfg = config.load()
    cx = cfg["context"]
    max_out = cx["max_output_chars"]

    head = [
        "## ORTAM",
        f"sistem: {b.system}",
        f"dizin: {b.cwd}",
    ]
    if b.git:
        head += ["", "## GIT", b.git]
    if b.files:
        head += ["", "## SON DOKUNULAN DOSYALAR", b.files]
    if b.signals:
        head += ["", "## ZORLANMA SINYALLERI"] + [f"- {s}" for s in b.signals]
    if b.wall_hits >= 2:
        head += ["", f"## TEKRAR UYARISI\nBu ayni duvara {b.wall_hits}. kez carpiyor."]
    if b.user_note:
        head += ["", "## SENIN NOTUN",
                 "Kullanici bu duvari daha once cozup kendi notunu birakti:",
                 b.user_note]
    if b.history:
        head += ["", "## GECEN SEFER NE SOYLENMISTI"] + [f"- {h}" for h in b.history]

    body = ["", "## TERMINAL GECMISI (eskiden yeniye)"]
    for t in b.turns:
        when = time.strftime("%H:%M:%S", time.localtime(t.ts))
        mark = "X" if t.failed else "ok"
        body.append(f"\n$ {t.cmd}    # {when} [{mark} exit={t.exit} {t.dur_ms}ms] {t.cwd}")
        if t.out:
            out = t.out
            if len(out) > max_out:
                out = out[: max_out // 2] + "\n...[kesildi]...\n" + out[-max_out // 2:]
            body.append(out)

    if b.focus:
        body += ["", "## ODAK - burada takildi",
                 f"$ {b.focus.cmd}", f"exit={b.focus.exit}",
                 (b.focus.out or "(cikti yok)")[:max_out]]

    if question:
        body += ["", "## KULLANICININ SORUSU", question]

    text = "\n".join(head + body)

    # Butce asimi: gecmisin bas tarafindan kirp, odak ve basliklar hep kalsin.
    budget = cx["budget_chars"]
    if len(text) > budget:
        keep_head = "\n".join(head)
        rest = "\n".join(body)
        allow = max(2000, budget - len(keep_head) - 200)
        rest = "...[eski gecmis kirpildi]...\n" + rest[-allow:]
        text = keep_head + "\n" + rest

    if cfg["redact"]:
        text, hits = redact.redact(text)
        b.redacted = hits
    return text
