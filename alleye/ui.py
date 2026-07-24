"""Terminal HUD. Windows konsolunda ANSI'yi acar, renkleri sade tutar."""

from __future__ import annotations

import os
import platform
import sys
import threading
import time

_ENABLED = True


def init() -> None:
    global _ENABLED
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _ENABLED = False
        return
    if platform.system() == "Windows":
        try:
            import ctypes

            k32 = ctypes.windll.kernel32
            handle = k32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
        except Exception:
            _ENABLED = False


_C = {
    "dim": "\x1b[2m", "b": "\x1b[1m", "r": "\x1b[0m",
    "eye": "\x1b[38;5;39m", "warn": "\x1b[38;5;214m",
    "bad": "\x1b[38;5;203m", "ok": "\x1b[38;5;114m",
}


def c(style: str, text: str) -> str:
    if not _ENABLED:
        return text
    return f"{_C.get(style, '')}{text}{_C['r']}"


def banner(subtitle: str) -> None:
    print(f"\n{c('eye', '◉ all eye')}  {c('dim', subtitle)}")
    print(c("dim", "─" * 62))


def rule() -> None:
    print(c("dim", "─" * 62))


def note(text: str) -> None:
    print(c("dim", f"  {text}"))


def warn(text: str) -> None:
    print(c("warn", f"  ! {text}"))


def error(text: str) -> None:
    print(c("bad", f"  x {text}"))


def ok(text: str) -> None:
    print(c("ok", f"  + {text}"))


class Progress:
    """Ilk token gelene kadar ne oldugunu goster.

    Model dusunurken 30 saniye bos ekran kullaniciya 'dondu' dedirtiyor.
    Ayrica zincirdeki bir model dustugunde bunu sessizce yutmak yerine
    yaziyoruz - hangi modelin neden atlandigi tek gorunur yer burasi.
    """

    FRAMES = "-\\|/"

    def __init__(self) -> None:
        self._text = ""
        self._t0 = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._drawn = False
        self._live = _ENABLED and sys.stdout.isatty()

    def start(self) -> None:
        if not self._live:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def set(self, text: str) -> None:
        self._text = text
        if not self._live:
            note(text)

    def _loop(self) -> None:
        i = 0
        while not self._stop.wait(0.12):
            elapsed = time.monotonic() - self._t0
            line = f"  {self.FRAMES[i % 4]} {self._text}  {elapsed:.0f}sn"
            sys.stdout.write("\r" + line.ljust(72)[:72])
            sys.stdout.flush()
            self._drawn = True
            i += 1

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.3)
            self._thread = None
        if self._drawn:
            sys.stdout.write("\r" + " " * 72 + "\r")
            sys.stdout.flush()
            self._drawn = False


def stream_out(chunks, on_first=None) -> str:
    """Akisi yazdirirken metni de biriktirir. Ilk parcada on_first cagrilir."""
    buf: list[str] = []
    for ch in chunks:
        if not buf and on_first is not None:
            on_first()
        buf.append(ch)
        sys.stdout.write(ch)
        sys.stdout.flush()
    if buf and not buf[-1].endswith("\n"):
        sys.stdout.write("\n")
    return "".join(buf)


_AGAIN = {"ae", "alleye", "devam", "daha", "more", "e", "evet"}


def prompt_more(level: int) -> str:
    """Kademe kontrolu. Bos = derinlestir, q = cik, metin = takip sorusu."""
    if level >= 3:
        hint = "Enter = bitir   ·   ya da takip sorusu yaz"
    else:
        names = {1: "yon gosterir", 2: "tam cozumu verir"}
        hint = (f"Enter = KADEME {level + 1} ({names[level]})"
                f"   ·   q = bitir   ·   ya da soru yaz")
    try:
        reply = input(c("dim", f"\n  {hint}\n  › ")).strip()
    except (EOFError, KeyboardInterrupt):
        return "q"
    # `ae` yazmak cok guclu bir refleks - bunu soru sanip ayni kademede
    # takilmak kullaniciyi dongude birakiyor. Derinlesme komutu say.
    if reply.lower() in _AGAIN:
        return ""
    return reply
