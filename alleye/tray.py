"""Sistem tepsisi ikonu: konsolu gizle, tepsiye tasi.

Saf ctypes + Shell_NotifyIcon. Sifir pip bagimliligi (pystray/pillow/win32 YOK).
Ikon dis dosyadan degil, bellekte renkli bir bitmap'ten uretiliyor; renk
daemon'un durumunu gosteriyor: sakin=gri, sinyal=turuncu, hazir=yesil.

pump() BLOKLAMAZ: daemon'un PeekMessage dongusune her turda girecek sekilde
tasarlandi. Sadece kendi penceresine gelen mesajlari ceker/isler, sag tik
menusunun secimlerini bir kuyruga koyar ve o kuyrugu mesaj isledikten sonra
bosaltir - boylece uzun suren bir callback (orn. cevap uretmek) WndProc'un
icinde takilip kalmaz.
"""

from __future__ import annotations

import ctypes
import platform
from ctypes import (
    c_int,
    c_long,
    c_size_t,
    c_ssize_t,
    c_ubyte,
    c_uint,
    c_uint32,
    c_ushort,
    c_void_p,
    c_wchar,
    c_wchar_p,
)

# --------------------------------------------------------------- sabitler ---

STATES = ("sakin", "sinyal", "hazir")

# Renkler ui.py'deki paletle ayni ruhta: gri notr, turuncu uyari, yesil hazir.
# state_color SAF bir fonksiyon - test dogrudan bunu kilitliyor.
_STATE_RGB = {
    "sakin": (130, 130, 130),   # notr gri: hicbir sey olmuyor
    "sinyal": (255, 150, 20),   # turuncu: zorlanma sezildi
    "hazir": (60, 200, 90),     # yesil: cevap hazir
}

# Win32 mesaj/bayrak sabitleri
_WM_NULL = 0x0000
_WM_DESTROY = 0x0002
_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_WM_APP = 0x8000
_CBMSG = _WM_APP + 1          # tepsi ikonunun bize gonderecegi callback mesaji

_NIM_ADD = 0
_NIM_MODIFY = 1
_NIM_DELETE = 2
_NIF_MESSAGE = 0x01
_NIF_ICON = 0x02
_NIF_TIP = 0x04

_MF_STRING = 0x0000
_MF_SEPARATOR = 0x0800
_TPM_RIGHTBUTTON = 0x0002
_TPM_NONOTIFY = 0x0080
_TPM_RETURNCMD = 0x0100

_WS_OVERLAPPED = 0x00000000
_WS_EX_TOOLWINDOW = 0x00000080

_SW_HIDE = 0
_SW_SHOW = 5

# Sag tik menusu komut kimlikleri
_ID_ASK = 1
_ID_STATUS = 2
_ID_PAUSE = 3
_ID_QUIT = 4


# --------------------------------------------------------------- yapilar ---
# Handle'lar 64-bit'te pointer boyutunda; c_void_p kullaniyoruz. Boylece
# ctypes.wintypes'a hic dokunmadan modul her platformda import edilebiliyor.


class _POINT(ctypes.Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", c_void_p), ("message", c_uint),
        ("wParam", c_size_t), ("lParam", c_ssize_t),
        ("time", c_uint), ("pt_x", c_long), ("pt_y", c_long),
    ]


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", c_uint),
        ("lpfnWndProc", c_void_p),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", c_void_p),
        ("hIcon", c_void_p),
        ("hCursor", c_void_p),
        ("hbrBackground", c_void_p),
        ("lpszMenuName", c_wchar_p),
        ("lpszClassName", c_wchar_p),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", c_int),
        ("xHotspot", c_uint),
        ("yHotspot", c_uint),
        ("hbmMask", c_void_p),
        ("hbmColor", c_void_p),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_uint), ("Data2", c_ushort), ("Data3", c_ushort),
        ("Data4", c_ubyte * 8),
    ]


class _NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", c_uint),
        ("hWnd", c_void_p),
        ("uID", c_uint),
        ("uFlags", c_uint),
        ("uCallbackMessage", c_uint),
        ("hIcon", c_void_p),
        ("szTip", c_wchar * 128),
        ("dwState", c_uint),
        ("dwStateMask", c_uint),
        ("szInfo", c_wchar * 256),
        ("uVersion", c_uint),
        ("szInfoTitle", c_wchar * 64),
        ("dwInfoFlags", c_uint),
        ("guidItem", _GUID),
        ("hBalloonIcon", c_void_p),
    ]


# ---------------------------------------------------- win32 tembel yukleme ---
# ctypes.windll sadece Windows'ta var; bu yuzden hicbir windll erisimi modul
# yuklenirken degil, ihtiyac aninda (create/hide/show) yapiliyor.

_W = None
_CLASS_SEQ = 0


def _load():
    """user32/gdi32/shell32/kernel32 fonksiyonlarini bir kez yapilandir, onbellekle."""
    global _W
    if _W is not None:
        return _W
    import types

    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    s = ctypes.windll.shell32
    k = ctypes.windll.kernel32

    # 64-bit'te pointer/LRESULT donuslerinin kesilmemesi icin restype sart.
    u.CreateWindowExW.restype = c_void_p
    u.CreateWindowExW.argtypes = [
        c_uint, c_wchar_p, c_wchar_p, c_uint,
        c_int, c_int, c_int, c_int,
        c_void_p, c_void_p, c_void_p, c_void_p,
    ]
    u.DefWindowProcW.restype = c_ssize_t
    u.DefWindowProcW.argtypes = [c_void_p, c_uint, c_size_t, c_ssize_t]
    u.RegisterClassW.restype = c_ushort
    u.RegisterClassW.argtypes = [c_void_p]
    u.UnregisterClassW.restype = c_int
    u.UnregisterClassW.argtypes = [c_wchar_p, c_void_p]
    u.DestroyWindow.restype = c_int
    u.DestroyWindow.argtypes = [c_void_p]
    u.CreatePopupMenu.restype = c_void_p
    u.CreatePopupMenu.argtypes = []
    u.AppendMenuW.restype = c_int
    u.AppendMenuW.argtypes = [c_void_p, c_uint, c_size_t, c_wchar_p]
    u.TrackPopupMenu.restype = c_int
    u.TrackPopupMenu.argtypes = [
        c_void_p, c_uint, c_int, c_int, c_int, c_void_p, c_void_p]
    u.DestroyMenu.restype = c_int
    u.DestroyMenu.argtypes = [c_void_p]
    u.GetCursorPos.argtypes = [c_void_p]
    u.SetForegroundWindow.argtypes = [c_void_p]
    u.PostMessageW.argtypes = [c_void_p, c_uint, c_size_t, c_ssize_t]
    u.PeekMessageW.restype = c_int
    u.PeekMessageW.argtypes = [c_void_p, c_void_p, c_uint, c_uint, c_uint]
    u.TranslateMessage.argtypes = [c_void_p]
    u.DispatchMessageW.restype = c_ssize_t
    u.DispatchMessageW.argtypes = [c_void_p]
    u.CreateIconIndirect.restype = c_void_p
    u.CreateIconIndirect.argtypes = [c_void_p]
    u.DestroyIcon.argtypes = [c_void_p]

    k.GetModuleHandleW.restype = c_void_p
    k.GetModuleHandleW.argtypes = [c_wchar_p]

    g.CreateBitmap.restype = c_void_p
    g.CreateBitmap.argtypes = [c_int, c_int, c_uint, c_uint, c_void_p]
    g.DeleteObject.restype = c_int
    g.DeleteObject.argtypes = [c_void_p]

    s.Shell_NotifyIconW.restype = c_int
    s.Shell_NotifyIconW.argtypes = [c_uint, c_void_p]

    _W = types.SimpleNamespace(
        CreateWindowExW=u.CreateWindowExW,
        DefWindowProcW=u.DefWindowProcW,
        RegisterClassW=u.RegisterClassW,
        UnregisterClassW=u.UnregisterClassW,
        DestroyWindow=u.DestroyWindow,
        CreatePopupMenu=u.CreatePopupMenu,
        AppendMenuW=u.AppendMenuW,
        TrackPopupMenu=u.TrackPopupMenu,
        DestroyMenu=u.DestroyMenu,
        GetCursorPos=u.GetCursorPos,
        SetForegroundWindow=u.SetForegroundWindow,
        PostMessageW=u.PostMessageW,
        PeekMessageW=u.PeekMessageW,
        TranslateMessage=u.TranslateMessage,
        DispatchMessageW=u.DispatchMessageW,
        CreateIconIndirect=u.CreateIconIndirect,
        DestroyIcon=u.DestroyIcon,
        GetModuleHandleW=k.GetModuleHandleW,
        CreateBitmap=g.CreateBitmap,
        DeleteObject=g.DeleteObject,
        Shell_NotifyIconW=s.Shell_NotifyIconW,
    )
    return _W


# --------------------------------------------------------------- public ---


def available() -> bool:
    """Windows'ta ve user32/shell32 erisilebilir mi?"""
    if platform.system() != "Windows":
        return False
    try:
        ctypes.windll.user32
        ctypes.windll.shell32
        return True
    except Exception:
        return False


def hide_console() -> None:
    """Konsol penceresini gizle (SW_HIDE). Windows disinda sessizce hicbir sey yapma."""
    if platform.system() != "Windows":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, _SW_HIDE)
    except Exception:
        pass


def show_console() -> None:
    """Gizlenen konsolu geri goster (SW_SHOW)."""
    if platform.system() != "Windows":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, _SW_SHOW)
    except Exception:
        pass


def state_color(state: str) -> tuple[int, int, int]:
    """Durum adini RGB rengine cevir. Bilinmeyen durum -> sakin (gri).

    SAF fonksiyon; yan etkisi yok, test dogrudan bunu kilitliyor.
    """
    return _STATE_RGB.get(state, _STATE_RGB["sakin"])


class Tray:
    """Sistem tepsisi ikonu ve sag tik menusu.

    Kullanim: t = Tray(...); t.create(); [her turda t.pump()]; ...; t.destroy().
    Windows disinda create() nazik bir RuntimeError firlatir.
    """

    STATES = STATES

    def __init__(self, *, on_ask=None, on_status=None, on_pause=None,
                 on_quit=None, tooltip: str = "all eye") -> None:
        self._on_ask = on_ask
        self._on_status = on_status
        self._on_pause = on_pause
        self._on_quit = on_quit
        self._tooltip = tooltip

        self._state = "sakin"
        self._created = False
        self._w = None                 # yapilandirilmis win32 fonksiyonlari
        self._wndproc = None           # WNDPROC referansi - GC edilmemeli
        self._hwnd = None
        self._hinst = None
        self._hicon = None
        self._nid = None               # _NOTIFYICONDATA (canli tutulmali)
        self._class_name = ""
        self._msg = None               # pump() icin tekrar kullanilan MSG
        self._pending: list = []       # menu/tiklama sonrasi calisacak callback'ler

    # -- ikon uretimi -----------------------------------------------------

    def _make_icon(self, rgb: tuple[int, int, int]):
        """Bellekte 16x16 dolu renkli bir ikon uret. Dis dosya yok."""
        w = self._w
        r, g, b = rgb
        n = 16 * 16
        # 32bpp BGRA; alfa=0xFF (opak). Alfa 0 olsaydi ikon gorunmez olurdu.
        val = (0xFF << 24) | (r << 16) | (g << 8) | b
        color = (c_uint32 * n)()
        for i in range(n):
            color[i] = val
        hbm_color = w.CreateBitmap(16, 16, 1, 32, color)
        # AND maskesi (1bpp): sifir = her yerde opak. 16 satir x 2 bayt.
        mask = (c_ubyte * (16 * 2))()
        hbm_mask = w.CreateBitmap(16, 16, 1, 1, mask)
        ii = _ICONINFO(1, 0, 0, hbm_mask, hbm_color)
        hicon = w.CreateIconIndirect(ctypes.byref(ii))
        w.DeleteObject(hbm_color)
        w.DeleteObject(hbm_mask)
        return hicon

    # -- yasam dongusu ----------------------------------------------------

    def create(self) -> None:
        """Gizli message pencereyi ac ve tepsi ikonunu ekle."""
        global _CLASS_SEQ
        if self._created:
            return
        if not available():
            raise RuntimeError(
                "tepsi ikonu bu sistemde kullanilamaz (yalniz Windows)")

        w = self._w = _load()

        # WNDPROC tipi Windows'a ozel (ctypes.WINFUNCTYPE); create icinde uret.
        WNDPROC = ctypes.WINFUNCTYPE(
            c_ssize_t, c_void_p, c_uint, c_size_t, c_ssize_t)
        self._wndproc = WNDPROC(self._on_message)

        self._hinst = w.GetModuleHandleW(None)
        _CLASS_SEQ += 1
        self._class_name = f"AllEyeTray_{_CLASS_SEQ}"

        wc = _WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, c_void_p)
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._hinst
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name
        w.RegisterClassW(ctypes.byref(wc))  # ayni ad tekrar edilmiyor (seq)

        self._hwnd = w.CreateWindowExW(
            _WS_EX_TOOLWINDOW, self._class_name, "all eye tray",
            _WS_OVERLAPPED, 0, 0, 0, 0, None, None, self._hinst, None)
        if not self._hwnd:
            raise RuntimeError("tepsi penceresi olusturulamadi")

        self._hicon = self._make_icon(state_color(self._state))

        nid = _NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _CBMSG
        nid.hIcon = self._hicon
        nid.szTip = f"{self._tooltip} - {self._state}"
        self._nid = nid

        if not w.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid)):
            raise RuntimeError("tepsi ikonu eklenemedi (Shell_NotifyIcon)")

        self._msg = _MSG()
        self._created = True

    def set_state(self, state: str) -> None:
        """Ikon rengini ve tooltip'i durum'a gore degistir.

        create()'den once cagrilirsa sadece hedef durum saklanir, create()
        onu uygular.
        """
        self._state = state
        if not self._created:
            return
        w = self._w
        new_icon = self._make_icon(state_color(state))
        old_icon = self._hicon
        self._nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        self._nid.hIcon = new_icon
        self._nid.szTip = f"{self._tooltip} - {state}"
        w.Shell_NotifyIconW(_NIM_MODIFY, ctypes.byref(self._nid))
        self._hicon = new_icon
        if old_icon:
            w.DestroyIcon(old_icon)

    def pump(self) -> None:
        """BLOKLAMAYAN: bekleyen tray mesajlarini isle, kuyruktaki callback'leri cagir.

        Sadece kendi penceresine gelen mesajlari ceker (hwnd filtreli
        PeekMessage). Boylece daemon'un kisayol (WM_HOTKEY, hwnd=NULL)
        mesajlarina dokunmaz. Callback'ler mesaj isleme bittikten SONRA
        calisir; uzun surse bile WndProc icinde takilmaz.
        """
        if not self._created:
            return
        w = self._w
        msg = self._msg
        while w.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, 1):
            w.TranslateMessage(ctypes.byref(msg))
            w.DispatchMessageW(ctypes.byref(msg))
        while self._pending:
            cb = self._pending.pop(0)
            try:
                cb()
            except Exception:
                pass

    def destroy(self) -> None:
        """Ikonu kaldir, pencereyi yok et, sinifi kaydini sil. Idempotent."""
        w = self._w
        if w is None:
            self._created = False
            return
        try:
            if self._nid is not None:
                w.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        try:
            if self._hicon:
                w.DestroyIcon(self._hicon)
        except Exception:
            pass
        try:
            if self._hwnd:
                w.DestroyWindow(self._hwnd)
        except Exception:
            pass
        try:
            if self._class_name:
                w.UnregisterClassW(self._class_name, self._hinst)
        except Exception:
            pass
        self._hicon = None
        self._hwnd = None
        self._nid = None
        self._created = False

    # -- ic isleyis --------------------------------------------------------

    def _queue(self, cb) -> None:
        if cb is not None:
            self._pending.append(cb)

    def _on_message(self, hwnd, msg, wparam, lparam):
        """Pencere proseduru. Tray callback mesajini ve sag tik menusunu isler."""
        try:
            if msg == _CBMSG:
                mouse = lparam & 0xFFFF
                if mouse in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                    self._queue(self._on_ask)
                elif mouse == _WM_RBUTTONUP:
                    self._popup(hwnd)
                return 0
            if msg == _WM_DESTROY:
                return 0
        except Exception:
            pass
        return self._w.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _popup(self, hwnd) -> None:
        """Sag tik menusunu goster; secilen komutu callback kuyruguna koy."""
        w = self._w
        menu = w.CreatePopupMenu()
        if not menu:
            return
        w.AppendMenuW(menu, _MF_STRING, _ID_ASK, "Sor")
        w.AppendMenuW(menu, _MF_STRING, _ID_STATUS, "Durum")
        w.AppendMenuW(menu, _MF_STRING, _ID_PAUSE, "Duraklat")
        w.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
        w.AppendMenuW(menu, _MF_STRING, _ID_QUIT, "Cik")

        pt = _POINT()
        w.GetCursorPos(ctypes.byref(pt))
        # Menunun disari tiklaninca kapanabilmesi icin klasik on-plan hilesi.
        w.SetForegroundWindow(hwnd)
        cmd = w.TrackPopupMenu(
            menu, _TPM_RIGHTBUTTON | _TPM_NONOTIFY | _TPM_RETURNCMD,
            pt.x, pt.y, 0, hwnd, None)
        w.PostMessageW(hwnd, _WM_NULL, 0, 0)
        w.DestroyMenu(menu)

        cb = {
            _ID_ASK: self._on_ask,
            _ID_STATUS: self._on_status,
            _ID_PAUSE: self._on_pause,
            _ID_QUIT: self._on_quit,
        }.get(cmd)
        self._queue(cb)
