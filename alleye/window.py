"""Cevap penceresi: cercevesiz, her zaman ustte, imlecin yaninda.

Bu pencere KONSOL yolunun yerine gecmez; ek bir sunum katmanidir. Kisayol ya da
tepsi ile cagrildiginda cevabi terminale bakmadan gormek icin. Felsefe geregi
kendiliginden acilmaz; sadece kullanici cagirinca. Odagi kalici olarak calmaz:
acilirken onceki on plan penceresi saklanir, kapaninca ona geri donulur.

Sifir bagimlilik kurali: sadece stdlib. tkinter (GUI) + ctypes (imlec/odak).
pywebview/pyqt/pillow YOK.
"""

from __future__ import annotations

import platform
import queue
import threading
import time

try:  # tkinter stdlib'de ama bazi minimal kurulumlarda eksik olabilir
    import tkinter as tk
except Exception:  # noqa: BLE001 - import'un patlamasi araci comertlestirmesin
    tk = None  # type: ignore[assignment]


# Varsayilan gorunum. show_answer bunlari config'ten okuyup ezebilir.
_DEF_WIDTH = 480
_DEF_HEIGHT = 320
_DEF_FONT_SIZE = 10
_OFFSET_X = 16   # imlecin biraz sagina
_OFFSET_Y = 18   # ve biraz altina ac

# Windows sanal tus / durum maskeleri
_CTRL_MASK = 0x0004
_ALLOW_CTRL = ("c", "a", "insert")
_NAV_KEYS = ("Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next",
             "Shift_L", "Shift_R", "Control_L", "Control_R")


def available() -> bool:
    """Pencere acilabilir mi: Windows + tkinter iceri alinabiliyor."""
    if platform.system() != "Windows":
        return False
    return tk is not None


def cursor_xy() -> tuple[int, int]:
    """Imlecin ekran konumu (GetCursorPos). Windows disinda (0, 0).

    ctypes cagrisi test edilebilir olsun diye ince bir sarim; hata olursa
    (0, 0) doner, cagiran taraf clamp_to_screen ile zaten guvende.
    """
    if platform.system() != "Windows":
        return (0, 0)
    try:
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            return (int(pt.x), int(pt.y))
    except Exception:  # noqa: BLE001
        pass
    return (0, 0)


def clamp_to_screen(x: int, y: int, w: int, h: int,
                    sw: int, sh: int) -> tuple[int, int]:
    """Pencereyi ekran icine sikistir. SAF fonksiyon - GUI'ye dokunmaz.

    Once sag/alt kenardan tasmayi geri it, sonra negatifi sifirla. Bu sira
    onemli: pencere ekrandan genisse sag duzeltmesi x'i negatife iter, ikinci
    adim onu 0'a ceker. Sonuc her zaman >= 0.
    """
    x = int(x)
    y = int(y)
    if x + w > sw:
        x = sw - w
    if y + h > sh:
        y = sh - h
    if x < 0:
        x = 0
    if y < 0:
        y = 0
    return (x, y)


def _foreground_hwnd() -> int:
    """Su an on plandaki pencerenin tanitici degeri (kapaninca geri verilecek)."""
    if platform.system() != "Windows":
        return 0
    try:
        import ctypes

        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:  # noqa: BLE001
        return 0


def _set_foreground(hwnd: int) -> None:
    if not hwnd or platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


class AnswerWindow:
    """Imlecin yaninda acilan salt-okunur, akitilabilir cevap penceresi.

    Thread modeli: pencere onu YARATAN thread'de calisir ve pump() de orada
    cagrilmali (Tk kurali). append/set_header/clear baska thread'den guvenli:
    islemi bir kuyruga koyar ve after(0, ...) ile ana thread'de uygulanir;
    after tetiklenmese bile pump() her turda kuyrugu bosaltir.
    """

    def __init__(self, *, on_deepen=None, on_close=None,
                 width: int = _DEF_WIDTH, height: int = _DEF_HEIGHT,
                 font_size: int = _DEF_FONT_SIZE,
                 offset_x: int = _OFFSET_X, offset_y: int = _OFFSET_Y) -> None:
        if tk is None:
            raise RuntimeError("tkinter yok - bu ortamda cevap penceresi acilamaz")
        self.on_deepen = on_deepen
        self.on_close = on_close
        self._width = int(width)
        self._height = int(height)
        self._offset_x = int(offset_x)
        self._offset_y = int(offset_y)
        self._alive = True
        self._prev_hwnd = 0
        self._queue: "queue.Queue[tuple[str, str]]" = queue.Queue()

        # Pencere ve parcalar. tk.Tk() basli ortamda TclError firlatir - cagiran
        # taraf (ve testler) bunu yakalar.
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        try:
            self._root.attributes("-alpha", 0.97)  # hafif saydam - ustune binmesin
        except Exception:  # noqa: BLE001 - bazi surumlerde desteklenmez
            pass

        bg = "#12151c"
        fg = "#d6dde6"
        accent = "#4aa3ff"
        dim = "#7c8794"

        border = tk.Frame(self._root, bg="#2a2f3a")
        border.pack(fill="both", expand=True)
        outer = tk.Frame(border, bg=bg)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        self._header = tk.Label(
            outer, text="all eye", anchor="w", justify="left",
            bg=bg, fg=accent, font=("Segoe UI", font_size, "bold"),
            padx=10, pady=6,
        )
        self._header.pack(fill="x")

        self._text = tk.Text(
            outer, wrap="word", bg=bg, fg=fg, insertwidth=0,
            relief="flat", highlightthickness=0, padx=10, pady=4,
            font=("Consolas", font_size), selectbackground="#2f4a6b",
        )
        self._text.pack(fill="both", expand=True)

        self._hint = tk.Label(
            outer, text="Enter = derinlestir   ·   Esc = kapat",
            anchor="w", bg=bg, fg=dim, font=("Segoe UI", max(8, font_size - 2)),
            padx=10, pady=5,
        )
        self._hint.pack(fill="x")

        # Salt-okunur ama secilebilir: kullanici tus vuruslari yutulur, program
        # yine de yazabilir (insert). Kopyala/sec/gezinme serbest birakilir.
        self._text.bind("<Key>", self._readonly_guard)
        for widget in (self._root, self._text):
            widget.bind("<Escape>", lambda e: self.close())
            widget.bind("<Return>", self._on_enter)
            widget.bind("<KP_Enter>", self._on_enter)

    # -- salt-okunur klavye ------------------------------------------------

    def _readonly_guard(self, event):
        ctrl = bool(event.state & _CTRL_MASK)
        if ctrl and event.keysym.lower() in _ALLOW_CTRL:
            return None  # kopyala / tumunu sec / kopyala(insert)
        if event.keysym in _NAV_KEYS:
            return None  # gezinme ve secim serbest
        return "break"   # geri kalan her tus vurusu yutulur

    def _on_enter(self, event=None):
        if self.on_deepen is not None:
            try:
                self.on_deepen()
            except Exception:  # noqa: BLE001 - callback pencereyi dusurmesin
                pass
        return "break"

    # -- kuyruk uygulama (ana thread'de) -----------------------------------

    def _drain(self) -> None:
        if self._root is None:
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "append":
                    self._text.insert("end", payload)
                    self._text.see("end")
                elif kind == "header":
                    self._header.configure(text=payload)
                elif kind == "clear":
                    self._text.delete("1.0", "end")
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001 - pencere yok edilmis olabilir
            pass

    def _schedule_drain(self) -> None:
        if self._root is None:
            return
        try:
            self._root.after(0, self._drain)
        except Exception:  # noqa: BLE001 - pump() yine de bosaltir
            pass

    # -- genel API ---------------------------------------------------------

    def show_near_cursor(self) -> None:
        """Imlecin yaninda ac. Onceki on plan penceresini sakla."""
        if self._root is None:
            return
        self._prev_hwnd = _foreground_hwnd()
        cx, cy = cursor_xy()
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        x, y = clamp_to_screen(cx + self._offset_x, cy + self._offset_y,
                               self._width, self._height, sw, sh)
        self._root.geometry(f"{self._width}x{self._height}+{x}+{y}")
        self._root.deiconify()
        self._root.lift()
        self._root.attributes("-topmost", True)
        self._root.update_idletasks()
        # Esc/Enter ve kopyalama icin klavye odagi lazim; kapaninca geri verilir.
        try:
            self._root.focus_force()
            self._text.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def set_header(self, text: str) -> None:
        if not self._alive:
            return
        self._queue.put(("header", text))
        self._schedule_drain()

    def append(self, text: str) -> None:
        """Akis parcasi ekle. Baska thread'den guvenli (kuyruk + after)."""
        if not self._alive:
            return
        self._queue.put(("append", text))
        self._schedule_drain()

    def clear(self) -> None:
        if not self._alive:
            return
        self._queue.put(("clear", ""))
        self._schedule_drain()

    def pump(self) -> None:
        """Bekleyen olaylari isle - BLOKLAMAZ. Daemon dongusune girebilir."""
        if not self._alive or self._root is None:
            return
        self._drain()
        try:
            self._root.update()
        except Exception:  # noqa: BLE001 - pencere disaridan kapatilmis olabilir
            self._alive = False

    def alive(self) -> bool:
        return self._alive

    def close(self) -> None:
        """Gizle/yok et, on_close cagir, odagi eski pencereye geri ver."""
        if not self._alive:
            return
        self._alive = False
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:  # noqa: BLE001
                pass
        root, self._root = self._root, None
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
        _set_foreground(self._prev_hwnd)


def show_answer(chunks_iterable, header: str = "", on_deepen=None) -> bool:
    """Cevabi bir pencerede akit. Kapanana kadar bloklar; kapaninca True doner.

    chunks_iterable : model cevabini parca parca veren yinelenebilir (Router.stream).
    header          : ust satir (mentor.header ciktisi).
    on_deepen       : Enter'a basilinca cagrilan, BIR SONRAKI kademenin
                      parcalarini veren cagrilabilir; None ya da bos donerse
                      derinlestirilecek kademe kalmamis demektir.

    Konsol yolunu BOZMAZ: bu fonksiyon ayri bir sunum katmanidir. Koordinator
    kisayol/tepsi tetiklerinde bunu cagirir, terminal `ask` akisi eskisi gibi
    stream_out ile calismaya devam eder.
    """
    if not available():
        return False

    # Pencere ayarlarini config'ten al (yoksa varsayilan). Import tembel:
    # window.py'yi config olmadan da test edebilelim.
    fs, w, h = _DEF_FONT_SIZE, _DEF_WIDTH, _DEF_HEIGHT
    try:
        from alleye import config

        wc = config.load().get("window", {})
        fs = int(wc.get("font_size", fs))
        w = int(wc.get("width", w))
        h = int(wc.get("height", h))
    except Exception:  # noqa: BLE001 - config yoksa varsayilanla devam
        pass

    try:
        win = AnswerWindow(width=w, height=h, font_size=fs)
    except Exception:  # noqa: BLE001 - Tk acilamadi, sessizce konsola birak
        return False

    state = {"busy": False}

    def _stream_into(source) -> None:
        try:
            for ch in source:
                win.append(ch)
        except Exception as exc:  # noqa: BLE001
            win.append(f"\n[akis hatasi: {exc}]")
        finally:
            state["busy"] = False

    def _deepen() -> None:
        # Enter: bir sonraki kademeyi getir. Zaten akiyorsa yok say.
        if state["busy"] or on_deepen is None:
            return
        try:
            nxt = on_deepen()
        except Exception as exc:  # noqa: BLE001
            win.append(f"\n[derinlestirilemedi: {exc}]")
            return
        if nxt is None:
            return
        state["busy"] = True
        win.append("\n\n" + "-" * 46 + "\n")
        threading.Thread(target=_stream_into, args=(nxt,), daemon=True).start()

    win.on_deepen = _deepen
    win.show_near_cursor()
    if header:
        win.set_header(header)

    state["busy"] = True
    threading.Thread(target=_stream_into, args=(chunks_iterable,), daemon=True).start()

    while win.alive():
        win.pump()
        time.sleep(0.02)
    return True
