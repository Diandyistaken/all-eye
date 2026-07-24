"""Arka plan izleyici: global kisayol + pasif zorlanma tespiti.

UX ilkesi: bu surec ASLA kendiliginden onune pencere acmaz. Zorlanma sezerse
sadece sessiz bir satir basar ve gorev cubugunda yanip soner. Araya giren bir
asistan ilk gun kapatilir; sabirla bekleyen kalir.
"""

from __future__ import annotations

import ctypes
import platform
import threading
import time

from alleye import config, detect, ui

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
       "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

_VK = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B,
    "escape": 0x1B, "backspace": 0x08, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
}


def parse_hotkey(spec: str) -> tuple[int, int]:
    mods, vk = 0, 0
    for part in (p.strip().lower() for p in spec.split("+") if p.strip()):
        if part in MOD:
            mods |= MOD[part]
        elif part in _VK:
            vk = _VK[part]
        elif len(part) == 1:
            vk = ord(part.upper())
        else:
            raise ValueError(f"anlasilmayan tus: {part}")
    if not vk:
        raise ValueError(f"kisayolda tus yok: {spec}")
    return mods | MOD_NOREPEAT, vk


# Tercih edilen kisayol doluysa sirayla bunlar denenir. Olculmus liste:
# ctrl+alt+space bu makinede baska bir uygulama tarafindan tutuluyordu ve
# hicbir yedek olmadigi icin watch tamamen olmustu.
FALLBACKS = ["ctrl+alt+e", "ctrl+shift+space", "ctrl+alt+a",
             "ctrl+shift+e", "ctrl+alt+f9", "ctrl+shift+f9"]


def try_register(spec: str, hotkey_id: int = 1) -> bool:
    """Kisayolu kaydetmeyi dene. Basarisizsa hicbir iz birakmaz."""
    try:
        mods, vk = parse_hotkey(spec)
    except ValueError:
        return False
    return bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, vk))


def probe_hotkeys(specs: list[str]) -> list[tuple[str, bool]]:
    """Hangi kisayollar bos - kaydet, hemen birak."""
    u32 = ctypes.windll.user32
    out = []
    for i, spec in enumerate(specs, start=900):
        try:
            mods, vk = parse_hotkey(spec)
        except ValueError:
            out.append((spec, False))
            continue
        ok = bool(u32.RegisterHotKey(None, i, mods, vk))
        if ok:
            u32.UnregisterHotKey(None, i)
        out.append((spec, ok))
    return out


def _console_hwnd() -> int:
    try:
        return ctypes.windll.kernel32.GetConsoleWindow()
    except Exception:
        return 0


def _flash() -> None:
    """Gorev cubugunda yanip son - odagi CALMADAN haber ver."""
    hwnd = _console_hwnd()
    if not hwnd:
        return
    try:
        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p),
                        ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint),
                        ("dwTimeout", ctypes.c_uint)]

        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x00000002 | 0x0000000C, 3, 0)
        ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
    except Exception:
        pass


def _to_front() -> None:
    hwnd = _console_hwnd()
    if hwnd:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def _answer(trigger: str) -> None:
    from alleye.cli import main as cli_main

    try:
        cli_main(["ask", "--once", "--trigger", trigger])
    except Exception as exc:  # noqa: BLE001 - daemon hicbir sekilde olmemeli
        ui.error(f"cevap uretilemedi: {exc}")


def _passive_loop(interval: float, stop: threading.Event) -> None:
    seen: set[str] = set()
    while not stop.wait(interval):
        try:
            signals, _ = detect.watch_tick(seen)
        except Exception:
            continue
        if signals and detect.is_stuck(signals):
            when = time.strftime("%H:%M")
            ui.warn(f"{when} · {detect.summarize(signals)}")
            ui.note(f"       hazir oldugunda {config.load()['hotkey']}")
            _flash()


def run(hotkey_only: bool = False, interval: float = 20.0,
        hotkey: str | None = None, probe: bool = False) -> int:
    cfg = config.load()
    ui.init()

    if platform.system() != "Windows":
        ui.error("watch su an sadece Windows'ta calisiyor; `alleye ask` her yerde calisir")
        return 1

    if probe:
        ui.banner("kisayol taramasi")
        seen: list[str] = []
        for s in [cfg["hotkey"], *FALLBACKS]:
            if s not in seen:
                seen.append(s)
        for spec, ok in probe_hotkeys(seen):
            (ui.ok if ok else ui.error)(f"{spec:20} {'bos' if ok else 'dolu'}")
        ui.rule()
        ui.note("secmek icin:  alleye watch --hotkey ctrl+alt+e")
        return 0

    # Sirayla dene: --hotkey > config > yedekler. Ilk kaydedilen kazanir.
    wanted = [hotkey] if hotkey else [cfg["hotkey"], *FALLBACKS]
    spec = ""
    for candidate in wanted:
        if candidate and try_register(candidate):
            spec = candidate
            break

    if not spec:
        ui.error("hicbir kisayol kaydedilemedi - hepsi baska uygulamalarda")
        ui.note("bos olanlari gormek icin:  alleye watch --probe")
        ui.note("`ae` komutu her zaman calisir, kisayol sart degil")
        return 1

    if not hotkey and spec != cfg["hotkey"]:
        ui.warn(f"{cfg['hotkey']} dolu, {spec} kullaniliyor")

    ui.banner(f"izliyor · {spec} ile cagir · Ctrl+C ile cik")
    if not hotkey_only:
        ui.note(f"pasif tespit acik ({interval:.0f}sn) — araya girmez, sadece haber verir")

    stop = threading.Event()
    if not hotkey_only:
        threading.Thread(target=_passive_loop, args=(interval, stop), daemon=True).start()

    class MSG(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                    ("wParam", ctypes.c_void_p), ("lParam", ctypes.c_void_p),
                    ("time", ctypes.c_uint), ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]

    msg = MSG()
    u32 = ctypes.windll.user32
    try:
        while True:
            # PeekMessage + kisa uyku: GetMessage bloklarsa Ctrl+C islenmiyor.
            if u32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message == WM_HOTKEY:
                    _to_front()
                    print()
                    _answer("hotkey")
            else:
                time.sleep(0.03)
    except KeyboardInterrupt:
        print()
    finally:
        stop.set()
        u32.UnregisterHotKey(None, 1)
    return 0
