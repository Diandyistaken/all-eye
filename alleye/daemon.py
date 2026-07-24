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

from alleye import clipboard, config, detect, ui

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


def _answer_window(trigger: str) -> bool:
    """Cevabi imlecin yanindaki pencerede goster (Faz 1.3, alleye/window.py).

    Konsol yolu (_answer) aynen durur; bu ek bir sunum katmani. Pencere yoksa
    ya da bir sey ters giderse False doner, cagiran konsol yoluna duser.
    Kademeyi kullanici pencerede Enter ile acar - tikanikligi hazir cevaba
    cevirme kurali burada da gecerli.
    """
    try:
        from alleye import context, mentor, store, window
        from alleye.brain import Router

        if not window.available():
            return False
        cfg = config.load()
        # Baglam ana thread'de kurulur; bu baglantiyi hemen kapatiyoruz. Kayit
        # (record_ask) ayri bir worker thread'de yapilacagi icin (bkz. _gen)
        # oraya kendi taze baglantisini acar - sqlite baglantisi olusturuldugu
        # thread'e baglidir, paylasilirsa sqlite3.ProgrammingError firlatir.
        con = store.connect()
        try:
            b = context.build(con=con)
        finally:
            con.close()
        if not b.turns:
            return False  # gunluk bos - konsol _answer uyariyi zaten basar
        rendered = context.render(b, "")
        level = {"n": 1}

        def _stream_for(lvl: int):
            router = Router(cfg, deep=lvl >= 3)
            sys_p = mentor.system_prompt(lvl, cfg["language"])
            usr_p = mentor.user_prompt(rendered, lvl, "")

            def _gen():
                if lvl > 1:  # header sabit kaldigindan kademeyi metinde belirt
                    yield f"KADEME {lvl} ({ {2: 'yon', 3: 'tam cozum'}[lvl] })\n"
                for chunk in router.stream(sys_p, usr_p):
                    yield chunk
                u = router.used
                # KRITIK: bu generator show_answer tarafindan AYRI worker
                # thread'de tuketiliyor. Kaydi burada acilan taze baglantiyla yap;
                # ana thread'in baglantisini kullanmak ProgrammingError firlatir
                # ve duvar hafizasi sessizce yazilamaz.
                wcon = store.connect()
                try:
                    store.record_ask(wcon, cwd=b.cwd, level=lvl, trigger=trigger,
                                     signature=b.signature, question="(oto)",
                                     answer=u.text, provider=u.provider, model=u.model)
                finally:
                    wcon.close()
            return _gen()

        def _on_deepen():
            if level["n"] >= 3:
                return None  # kademe bitti - Enter artik bir sey yapmaz
            level["n"] += 1
            return _stream_for(level["n"])

        return window.show_answer(_stream_for(1), header=mentor.header(b, 1),
                                  on_deepen=_on_deepen)
    except Exception as exc:  # noqa: BLE001 - daemon asla olmemeli, konsola dus
        ui.error(f"cevap penceresi acilamadi ({exc}); konsol yoluna dusuluyor")
        return False


def _announce(text: str, on_signal) -> None:
    """Pasif sinyali bildir: konsola yaz, gorev cubugunda yanip son, tray'e isaret."""
    when = time.strftime("%H:%M")
    ui.warn(f"{when} · {text}")
    ui.note(f"       hazir oldugunda {config.load()['hotkey']}")
    _flash()
    if on_signal is not None:
        # Tray thread'ine degil, ana dongude islensin diye sadece isaret birak
        # (Shell_NotifyIcon'u olusturan thread'de cagirmak guvenli).
        try:
            on_signal()
        except Exception:
            pass


def _passive_loop(interval: float, stop: threading.Event, on_signal=None) -> None:
    seen: set[str] = set()
    last_clip = ""
    # Pano izleyici varsayilan acik ama config'ten kapatilabilir (gizlilik).
    clip_ready = clipboard.available() and config.load().get("clipboard_watch", True)
    while not stop.wait(interval):
        try:
            signals, turns = detect.watch_tick(seen)
        except Exception:
            continue
        if signals and detect.is_stuck(signals):
            _announce(detect.summarize(signals), on_signal)

        # Pano izleyici (Faz 2, alleye/clipboard.py): ses tetikleyicisinin
        # bagimliliksiz alternatifi. Kullanici bir hatayi panoya kopyaladiysa
        # buyuk olasilikla onu aramaya gidiyor = dolayli takilma sinyali.
        if clip_ready:
            try:
                clip = clipboard.read_text()
            except Exception:
                clip = ""
            if clip and clip != last_clip:  # bir oncekiyle ayniysa tekrar sinyal verme
                last_clip = clip
                try:
                    sig = clipboard.clipboard_signal(clip, turns)
                except Exception:
                    sig = None
                if sig is not None:
                    _announce(str(sig), on_signal)
            elif not clip:
                last_clip = ""


def run(hotkey_only: bool = False, interval: float = 20.0,
        hotkey: str | None = None, probe: bool = False, tray: bool = False) -> int:
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

    stop = threading.Event()

    # Tepsi ikonu (Faz 1.1). --tray verilmisse konsolu gizle, sistem tepsisine
    # tas. tray_obj None ise klasik konsol modu (davranis aynen korunur).
    tray_mod = None
    tray_obj = None
    paused = {"on": False}
    quit_flag = {"on": False}
    signal_pending = {"on": False}

    def _invoke(trigger: str) -> None:
        """Kisayol veya tepsi 'Sor' tetikledi. Once pencere yolu (Faz 1.3),
        o yoksa konsol yolu. Cevap uretilirken ikon sinyal, bitince sakin.

        Not: "hazir" (yesil) durumu bilerek atlaniyor - cevap uretimi senkron
        (pencere/konsol acikken dongu blokta), yani "hazir" gorunur bir an
        bulamaz. state_color'da tanimli; cevap on-uretimi eklenince kullanilacak.
        """
        if paused["on"]:
            return
        if tray_obj is not None:
            tray_obj.set_state("sinyal")
        if not _answer_window(trigger):
            if tray_obj is not None:
                tray_mod.show_console()  # konsol gizliyse cevabi gorunur yap
            _to_front()
            print()
            _answer(trigger)
        if tray_obj is not None:
            tray_obj.set_state("sakin")

    def _show_status() -> None:
        if tray_mod is not None:
            tray_mod.show_console()
        from alleye.cli import main as cli_main
        cli_main(["status"])

    if tray:
        from alleye import tray as _tray_import
        tray_mod = _tray_import
        if tray_mod.available():
            # hide_console + create tek blokta: create patlarsa konsol gizli ve
            # kisayol kayitli kalmasin diye konsolu geri acip konsol moduna dus.
            try:
                tray_mod.hide_console()
                tray_obj = tray_mod.Tray(
                    on_ask=lambda: _invoke("tray"),
                    on_status=_show_status,
                    on_pause=lambda: paused.__setitem__("on", not paused["on"]),
                    on_quit=lambda: quit_flag.__setitem__("on", True),
                    tooltip="all eye",
                )
                tray_obj.create()
                tray_obj.set_state("sakin")
            except Exception as exc:  # noqa: BLE001 - tepsi sart degil, konsola dus
                if tray_obj is not None:
                    try:
                        tray_obj.destroy()
                    except Exception:
                        pass
                    tray_obj = None
                tray_mod.show_console()
                tray_mod = None
                ui.warn(f"tepsi ikonu kurulamadi ({exc}); konsol modunda devam")
        else:
            tray_mod = None
            ui.warn("tepsi ikonu bu sistemde kullanilamiyor; konsol modunda devam")

    if tray_obj is None:
        ui.banner(f"izliyor · {spec} ile cagir · Ctrl+C ile cik")
        if not hotkey_only:
            ui.note(f"pasif tespit acik ({interval:.0f}sn) — araya girmez, sadece haber verir")

    if not hotkey_only:
        # Tray modunda sinyali tray thread'inden degil ana dongude isle: sadece
        # bayrak birak, Shell_NotifyIcon'u olusturan thread rengi degistirsin.
        # Duraklat aciksa pasif sinyal ikonu turuncuya cevirmesin.
        on_sig = (lambda: None if paused["on"]
                  else signal_pending.__setitem__("on", True)) if tray_obj else None
        threading.Thread(target=_passive_loop, args=(interval, stop, on_sig),
                         daemon=True).start()

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
                    _invoke("hotkey")
                elif tray_obj is not None:
                    # Tepsi penceresine gelen mesajlar (WM_HOTKEY degil) WndProc'a.
                    u32.TranslateMessage(ctypes.byref(msg))
                    u32.DispatchMessageW(ctypes.byref(msg))
            else:
                if tray_obj is not None:
                    if signal_pending["on"]:
                        tray_obj.set_state("sinyal")
                        # Konsol gizliyken kullanicinin tek gorunur ipucu bu balon.
                        # Sessiz (NIIF_NOSOUND) - araya girmez, sadece haber verir.
                        tray_obj.notify_balloon("takildin gibi gorunuyor",
                                                f"{spec} ile sor")
                        signal_pending["on"] = False
                    tray_obj.pump()
                time.sleep(0.03)
            if quit_flag["on"]:
                break
    except KeyboardInterrupt:
        print()
    finally:
        stop.set()
        u32.UnregisterHotKey(None, 1)
        if tray_obj is not None:
            tray_obj.destroy()
            tray_mod.show_console()
    return 0
