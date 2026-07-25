"""Ekran goruntusu yakalama + PNG + onizleme/onay (Faz 3).

GIZLILIK DEMIR KURALI: bu modul hicbir yere ag cagrisi YAPMAZ. Sadece yakalar,
PNG'ye cevirir ve kullaniciya gosterir. Bir goruntu ancak kullanici onizleyip
ACIKCA onaylarsa (preview_and_confirm True donerse) disari cikabilir. Her hata
durumunda guvenli taraf secilir: False / None.

Sifir pip bagimliligi: yalniz stdlib + ctypes + tkinter. pillow/mss/pyautogui/
win32 YOK. windll erisimi hep fonksiyon icinde (tembel), boylece modul her
platformda sorunsuz import edilir.

--- Olculmus tasarim kararlari (2026-07-25, bu makinede) ---

1) PrintWindow'un DONUS DEGERI GUVENILIR DEGIL. Olcum: bes farkli pencerede
   (Chromium/Chrome_WidgetWin_1, UWP CoreWindow, Progman) PrintWindow(0x2),
   PrintWindow(0) ve BitBlt'in ucu de 1 (basari) dondu ama uretilen bitmap
   TAMAMEN SIYAHTI (sifir olmayan bayt orani %0.00). Ayni olcum araciyla DIB'e
   kendimiz beyaz cizince %100 okundu - yani olcum dogru, kaynak gercekten
   siyah. Sonuc: donus degerine guvenen bir zincir modele siyah kare gonderir.
   Bu yuzden HER denemeden sonra GERCEK PIKSELLERE bakiyoruz (_dib_blank).
   Hicbiri icerik vermezse durustce None doneriz - siyah kare gondermek hem
   kotayi harcar hem kullaniciyi yaniltir.

2) 24bpp DIB kesiti (CreateCompatibleBitmap DEGIL). Iki sebep: (a) ekranla
   uyumlu 32bpp bitmap'te alfa kanali tanimsiz kalir, GDI+ bunu seffaf PNG'ye
   cevirebilir - goruntu bombos gorunur; 24bpp'de alfa yok, PNG hep opak.
   (b) DIB kesitinin ham piksel isaretcisine dogrudan erisebildigimiz icin (1)
   maddesindeki icerik yoklamasi decode gerektirmez, O(ornek) ucuzluktadir.

3) PNG kodlama GDI+ ile BELLEK USTU IStream'e; gecici dosya YOK. Ham ekran
   goruntusu bir an bile diske dusmez (gizlilik) ve I/O maliyeti yoktur.
   Uzunlugu Seek(CUR) ile aliriz: GlobalSize tahsis edilen blogu verir, sismis
   olabilir ve sonuna cop bayt eklenir.

4) GDI+'a vermeden once bitmap DC'den cikarilir ve GdiFlush cagrilir; aksi
   halde GDI+ islenmemis bitmap'i okur ve siyah PNG cikar.
"""

from __future__ import annotations

import base64
import ctypes
import platform
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_int,
    c_long,
    c_longlong,
    c_ubyte,
    c_uint,
    c_uint32,
    c_ulong,
    c_ulonglong,
    c_ushort,
    c_void_p,
    c_wchar_p,
    create_unicode_buffer,
)

try:  # tkinter stdlib'de ama bazi minimal kurulumlarda eksik olabilir
    import tkinter as tk
except Exception:  # noqa: BLE001 - import patlamasi araci comertlestirmesin
    tk = None  # type: ignore[assignment]


# --------------------------------------------------------------- sabitler ---

_PW_RENDERFULLCONTENT = 0x00000002   # DWM/GPU pencereleri icin (Win 8.1+)
_SRCCOPY = 0x00CC0020
_DIB_RGB_COLORS = 0
_BI_RGB = 0
_STREAM_SEEK_SET = 0
_STREAM_SEEK_CUR = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DPI_AWARENESS_PER_MONITOR_V2 = -4

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_MAX_DIM = 30000            # akil disi boyutlara karsi emniyet supabi
_MAX_PNG = 200 * 1024 * 1024

# GDI+ dahili PNG encoder CLSID: {557CF406-1A04-11D3-9A73-0000F81EF32E}
# Belgelenmis ve degismez; GdipGetImageEncoders ile enumerate etmeye gerek yok
# (daha az ara nesne = daha az sizinti yuzeyi).
_PNG_CLSID_PARTS = (0x557CF406, 0x1A04, 0x11D3,
                    (0x9A, 0x73, 0x00, 0x00, 0xF8, 0x1E, 0xF3, 0x2E))

# Onizleme penceresi ust sinirlari (ekrana gore ayrica kisitlanir).
_PREVIEW_MAX_W = 900
_PREVIEW_MAX_H = 640


# --------------------------------------------------------------- yapilar ---
# Handle'lar 64-bit'te pointer boyutunda; c_void_p kullaniyoruz (tray.py ruhu).


class _RECT(Structure):
    _fields_ = [("left", c_long), ("top", c_long),
                ("right", c_long), ("bottom", c_long)]


class _BITMAPINFOHEADER(Structure):
    _fields_ = [
        ("biSize", c_uint32),
        ("biWidth", c_long),
        ("biHeight", c_long),
        ("biPlanes", c_ushort),
        ("biBitCount", c_ushort),
        ("biCompression", c_uint32),
        ("biSizeImage", c_uint32),
        ("biXPelsPerMeter", c_long),
        ("biYPelsPerMeter", c_long),
        ("biClrUsed", c_uint32),
        ("biClrImportant", c_uint32),
    ]


class _GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", c_ubyte * 8)]


class _GdiplusStartupInput(Structure):
    _fields_ = [
        ("GdiplusVersion", c_uint32),
        ("DebugEventCallback", c_void_p),
        ("SuppressBackgroundThread", c_int),
        ("SuppressExternalCodecs", c_int),
    ]


def _png_clsid() -> _GUID:
    d1, d2, d3, d4 = _PNG_CLSID_PARTS
    return _GUID(d1, d2, d3, (c_ubyte * 8)(*d4))


# ---------------------------------------------------- win32 tembel yukleme ---

_W = None


def _load():
    """user32/gdi32/gdiplus/ole32/kernel32 fonksiyonlarini yapilandir, onbellekle."""
    global _W
    if _W is not None:
        return _W
    import types

    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    gp = ctypes.windll.gdiplus
    o = ctypes.windll.ole32
    k = ctypes.windll.kernel32

    # 64-bit'te pointer/handle donuslerinin kesilmemesi icin restype sart.
    u.GetForegroundWindow.restype = c_void_p
    u.GetForegroundWindow.argtypes = []
    u.IsWindow.restype = c_int
    u.IsWindow.argtypes = [c_void_p]
    u.IsIconic.restype = c_int
    u.IsIconic.argtypes = [c_void_p]
    u.GetWindowRect.restype = c_int
    u.GetWindowRect.argtypes = [c_void_p, POINTER(_RECT)]
    u.GetDC.restype = c_void_p
    u.GetDC.argtypes = [c_void_p]
    u.ReleaseDC.restype = c_int
    u.ReleaseDC.argtypes = [c_void_p, c_void_p]
    u.PrintWindow.restype = c_int
    u.PrintWindow.argtypes = [c_void_p, c_void_p, c_uint]
    u.GetWindowTextLengthW.restype = c_int
    u.GetWindowTextLengthW.argtypes = [c_void_p]
    u.GetWindowTextW.restype = c_int
    u.GetWindowTextW.argtypes = [c_void_p, c_wchar_p, c_int]
    u.GetWindowThreadProcessId.restype = c_uint
    u.GetWindowThreadProcessId.argtypes = [c_void_p, c_void_p]

    g.CreateCompatibleDC.restype = c_void_p
    g.CreateCompatibleDC.argtypes = [c_void_p]
    g.CreateDIBSection.restype = c_void_p
    g.CreateDIBSection.argtypes = [
        c_void_p, c_void_p, c_uint, POINTER(c_void_p), c_void_p, c_uint]
    g.SelectObject.restype = c_void_p
    g.SelectObject.argtypes = [c_void_p, c_void_p]
    g.BitBlt.restype = c_int
    g.BitBlt.argtypes = [c_void_p, c_int, c_int, c_int, c_int,
                         c_void_p, c_int, c_int, c_uint]
    g.DeleteObject.restype = c_int
    g.DeleteObject.argtypes = [c_void_p]
    g.DeleteDC.restype = c_int
    g.DeleteDC.argtypes = [c_void_p]
    g.GdiFlush.restype = c_int
    g.GdiFlush.argtypes = []

    gp.GdiplusStartup.restype = c_int
    gp.GdiplusStartup.argtypes = [POINTER(c_void_p), c_void_p, c_void_p]
    gp.GdiplusShutdown.restype = None
    gp.GdiplusShutdown.argtypes = [c_void_p]
    gp.GdipCreateBitmapFromHBITMAP.restype = c_int
    gp.GdipCreateBitmapFromHBITMAP.argtypes = [
        c_void_p, c_void_p, POINTER(c_void_p)]
    gp.GdipSaveImageToStream.restype = c_int
    gp.GdipSaveImageToStream.argtypes = [
        c_void_p, c_void_p, POINTER(_GUID), c_void_p]
    gp.GdipDisposeImage.restype = c_int
    gp.GdipDisposeImage.argtypes = [c_void_p]

    o.CreateStreamOnHGlobal.restype = c_long   # HRESULT (S_OK=0)
    o.CreateStreamOnHGlobal.argtypes = [c_void_p, c_int, POINTER(c_void_p)]

    k.OpenProcess.restype = c_void_p
    k.OpenProcess.argtypes = [c_uint, c_int, c_uint]
    k.CloseHandle.restype = c_int
    k.CloseHandle.argtypes = [c_void_p]
    qn = getattr(k, "QueryFullProcessImageNameW", None)
    if qn is not None:
        qn.restype = c_int
        qn.argtypes = [c_void_p, c_uint, c_wchar_p, POINTER(c_uint)]

    # SetThreadDpiAwarenessContext Win10 1607+ ile geldi; yoksa None.
    set_dpi = getattr(u, "SetThreadDpiAwarenessContext", None)
    if set_dpi is not None:
        set_dpi.restype = c_void_p
        set_dpi.argtypes = [c_void_p]

    _W = types.SimpleNamespace(
        GetForegroundWindow=u.GetForegroundWindow,
        IsWindow=u.IsWindow,
        IsIconic=u.IsIconic,
        GetWindowRect=u.GetWindowRect,
        GetDC=u.GetDC,
        ReleaseDC=u.ReleaseDC,
        PrintWindow=u.PrintWindow,
        GetWindowTextLengthW=u.GetWindowTextLengthW,
        GetWindowTextW=u.GetWindowTextW,
        GetWindowThreadProcessId=u.GetWindowThreadProcessId,
        SetThreadDpiAwarenessContext=set_dpi,
        CreateCompatibleDC=g.CreateCompatibleDC,
        CreateDIBSection=g.CreateDIBSection,
        SelectObject=g.SelectObject,
        BitBlt=g.BitBlt,
        DeleteObject=g.DeleteObject,
        DeleteDC=g.DeleteDC,
        GdiFlush=g.GdiFlush,
        GdiplusStartup=gp.GdiplusStartup,
        GdiplusShutdown=gp.GdiplusShutdown,
        GdipCreateBitmapFromHBITMAP=gp.GdipCreateBitmapFromHBITMAP,
        GdipSaveImageToStream=gp.GdipSaveImageToStream,
        GdipDisposeImage=gp.GdipDisposeImage,
        CreateStreamOnHGlobal=o.CreateStreamOnHGlobal,
        OpenProcess=k.OpenProcess,
        CloseHandle=k.CloseHandle,
        QueryFullProcessImageNameW=qn,
    )
    return _W


# ----------------------------------------------------------- COM yardimcisi ---
# IStream metotlarini vtable uzerinden cagiririz (COM sarici paketi olmadan).
# IUnknown: QueryInterface=0, AddRef=1, Release=2 | ISequentialStream: Read=3
# IStream: Seek=5


def _vtbl_fn(pobj: c_void_p, index: int, restype, *argtypes):
    """pobj arayuzunun vtable'indaki index. metodunu cagrilabilir hale getir."""
    vtbl = ctypes.cast(pobj, POINTER(c_void_p)).contents.value
    fn_addr = (c_void_p * (index + 1)).from_address(vtbl)[index]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(fn_addr)


def _stream_read_all(stream: c_void_p) -> bytes | None:
    """IStream'deki tum baytlari oku. Uzunlugu Seek(CUR) ile al.

    GdipSaveImageToStream yazdiktan sonra imlec sonda kalir; Seek(0, CUR) tam
    veri uzunlugunu verir. GlobalSize tahsis edilen blogu verdigi icin sismis
    olabilir ve sonuna cop bayt ekler.
    """
    try:
        seek = _vtbl_fn(stream, 5, c_long, c_longlong, c_ulong,
                        POINTER(c_ulonglong))
        read = _vtbl_fn(stream, 3, c_long, c_void_p, c_ulong, POINTER(c_ulong))
        pos = c_ulonglong(0)
        if seek(stream, 0, _STREAM_SEEK_CUR, byref(pos)) != 0:
            return None
        size = int(pos.value)
        if size <= 0 or size > _MAX_PNG:
            return None
        if seek(stream, 0, _STREAM_SEEK_SET, None) != 0:
            return None
        buf = ctypes.create_string_buffer(size)
        got = c_ulong(0)
        if read(stream, ctypes.cast(buf, c_void_p), size, byref(got)) < 0:
            return None
        data = buf.raw[: int(got.value)]
        return data or None
    except Exception:  # noqa: BLE001
        return None


def _com_release(pobj: c_void_p) -> None:
    """IUnknown::Release (vtable[2]). fDeleteOnRelease=TRUE ise HGLOBAL de gider."""
    if not pobj:
        return
    try:
        _vtbl_fn(pobj, 2, c_ulong)(pobj)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------- public ---


def available() -> bool:
    """Windows'ta ve user32/gdi32/gdiplus/ole32 yuklenebiliyor mu?"""
    if platform.system() != "Windows":
        return False
    try:
        ctypes.windll.user32
        ctypes.windll.gdi32
        ctypes.windll.gdiplus
        ctypes.windll.ole32
        return True
    except Exception:  # noqa: BLE001
        return False


def foreground_title() -> str:
    """On plandaki pencerenin basligi + calisan dosya adi + pid.

    context.active_window() ile ayni ruhta ama process ADINI da cozer.
    Bicim: "Baslik - exe.exe (pid 1234)". Cozemezse pid'de kalir.
    """
    if platform.system() != "Windows":
        return ""
    try:
        w = _load()
        hwnd = w.GetForegroundWindow()
        if not hwnd:
            return ""
        n = w.GetWindowTextLengthW(hwnd)
        buf = create_unicode_buffer(n + 1)
        w.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value or "(basliksiz pencere)"

        pid = c_uint(0)
        w.GetWindowThreadProcessId(hwnd, byref(pid))
        exe = _process_name(w, pid.value)
        if exe:
            return f"{title} - {exe} (pid {pid.value})"
        return f"{title} (pid {pid.value})"
    except Exception:  # noqa: BLE001
        return ""


def _process_name(w, pid: int) -> str:
    """pid'den calisan dosyanin adini coz (best effort; izin yoksa bos)."""
    if not pid or w.QueryFullProcessImageNameW is None:
        return ""
    h = None
    try:
        h = w.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
        if not h:
            return ""
        size = c_uint(260)
        buf = create_unicode_buffer(size.value)
        if w.QueryFullProcessImageNameW(h, 0, buf, byref(size)):
            full = buf.value or ""
            return full.replace("/", "\\").rsplit("\\", 1)[-1]
        return ""
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if h:
            try:
                w.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass


def _dib_blank(bits: c_void_p, total: int) -> bool:
    """DIB bellegi pratikte tamamen 0 (siyah/bos) mi? Ucuz ornekleme.

    NEDEN SART: olculdu (bkz. modul basligi) - PrintWindow ve BitBlt 1 (basari)
    donerken bitmap tamamen siyah olabiliyor. Donus degerine guvenmek yeterli
    degil, gercek piksellere bakmak gerekiyor. DIB kesitinin ham isaretcisine
    dogrudan eristigimiz icin bu O(ornek): decode yok.

    "Hepsi tam 0" yalniz basarisiz yakalamada olur; gercekten koyu bir pencere
    bile sifir olmayan piksel icerir (yazi, imlec, kenarlik).
    """
    if not bits or total <= 0:
        return True
    base = bits.value or 0
    if not base:
        return True
    try:
        step = max(64, total // 128)   # ~128 noktadan 64'er bayt orneklenir
        nz = 0
        i = 0
        while i + 64 <= total:
            chunk = ctypes.string_at(base + i, 64)
            nz += sum(1 for b in chunk if b)
            if nz > 8:               # icerik var; erken cik
                return False
            i += step
        return nz == 0
    except Exception:  # noqa: BLE001
        return False   # yoklayamadiysak "bos" deme; icerigi atma riskini alma


def capture_active_window() -> bytes | None:
    """On plandaki pencereyi yakala, PNG bayt dizisi don. Basarisiz -> None.

    Yakalama sirasi (HER denemeden sonra ICERIK yoklanir, donus degerine
    guvenilmez - bkz. modul basligindaki olcum):
      1) PrintWindow(PW_RENDERFULLCONTENT): calisirsa ortulu/kismen ekran
         disindaki pencereyi bile kendi icerigiyle cizdirir.
      2) PrintWindow(0): bazi klasik Win32 pencereleri icin.
      3) BitBlt (ekran DC'sinden): GPU pencerelerinin PrintWindow'a siyah
         dondugu durumda calisabilen son care. On plandaki pencereyi
         yakaladigimiz icin pencere zaten ustte, dogru icerik gelir.

    Ucu de bos kare verirse None doneriz: siyah goruntu gondermek kotayi
    harcar ve kullaniciyi yaniltir.
    """
    if not available():
        return None

    w = _load()
    hwnd = w.GetForegroundWindow()
    if not hwnd or not w.IsWindow(hwnd) or w.IsIconic(hwnd):
        return None  # kucultulmus/gecersiz pencere yakalanamaz

    # HiDPI'de 1:1 fiziksel piksel icin thread'i gecici olarak per-monitor-aware
    # yap; sonda eski baglam geri verilir (surec genelini kirletmez).
    prev_dpi = None
    if w.SetThreadDpiAwarenessContext is not None:
        try:
            prev_dpi = w.SetThreadDpiAwarenessContext(
                c_void_p(_DPI_AWARENESS_PER_MONITOR_V2))
        except Exception:  # noqa: BLE001
            prev_dpi = None

    screen_dc = mem_dc = hbitmap = old_obj = None
    try:
        rect = _RECT()
        if not w.GetWindowRect(hwnd, byref(rect)):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0 or width > _MAX_DIM or height > _MAX_DIM:
            return None

        screen_dc = w.GetDC(None)
        if not screen_dc:
            return None
        mem_dc = w.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            return None

        bmih = _BITMAPINFOHEADER()
        bmih.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmih.biWidth = width
        bmih.biHeight = height
        bmih.biPlanes = 1
        bmih.biBitCount = 24          # alfa yok -> PNG hep opak
        bmih.biCompression = _BI_RGB

        bits = c_void_p()
        hbitmap = w.CreateDIBSection(
            screen_dc, byref(bmih), _DIB_RGB_COLORS, byref(bits), None, 0)
        if not hbitmap or not bits.value:
            return None

        old_obj = w.SelectObject(mem_dc, hbitmap)
        stride = ((width * 3 + 3) // 4) * 4
        total = stride * height

        def _try(fn) -> bool:
            """Bir deneme yap, GDI kuyrugunu bosalt, GERCEKTEN icerik var mi bak."""
            try:
                if not fn():
                    return False
            except Exception:  # noqa: BLE001
                return False
            w.GdiFlush()              # yazimlar bitmap'e islensin
            return not _dib_blank(bits, total)

        captured = (
            _try(lambda: w.PrintWindow(hwnd, mem_dc, _PW_RENDERFULLCONTENT))
            or _try(lambda: w.PrintWindow(hwnd, mem_dc, 0))
            or _try(lambda: w.BitBlt(mem_dc, 0, 0, width, height, screen_dc,
                                     int(rect.left), int(rect.top), _SRCCOPY))
        )
        if not captured:
            return None

        # GDI+'a vermeden ONCE bitmap'i DC'den cikar; aksi halde GDI+
        # islenmemis bitmap'i okuyup siyah PNG uretebilir.
        w.SelectObject(mem_dc, old_obj)
        old_obj = None

        return _hbitmap_to_png(w, hbitmap)
    except Exception:  # noqa: BLE001 - yakalama patlarsa araci dusurme
        return None
    finally:
        try:
            if mem_dc and old_obj:
                w.SelectObject(mem_dc, old_obj)
        except Exception:  # noqa: BLE001
            pass
        for handle, deleter in ((hbitmap, w.DeleteObject), (mem_dc, w.DeleteDC)):
            if handle:
                try:
                    deleter(handle)
                except Exception:  # noqa: BLE001
                    pass
        if screen_dc:
            try:
                w.ReleaseDC(None, screen_dc)
            except Exception:  # noqa: BLE001
                pass
        if prev_dpi and w.SetThreadDpiAwarenessContext is not None:
            try:
                w.SetThreadDpiAwarenessContext(prev_dpi)
            except Exception:  # noqa: BLE001
                pass


def _hbitmap_to_png(w, hbitmap) -> bytes | None:
    """HBITMAP -> PNG baytlari (GDI+, bellek ustu IStream). Her sey finally'de free."""
    token = c_void_p()
    gp_bitmap = c_void_p()
    stream = c_void_p()
    started = False
    try:
        si = _GdiplusStartupInput()
        si.GdiplusVersion = 1
        if w.GdiplusStartup(byref(token), byref(si), None) != 0:
            return None
        started = True

        if w.GdipCreateBitmapFromHBITMAP(
                hbitmap, None, byref(gp_bitmap)) != 0 or not gp_bitmap:
            return None

        # fDeleteOnRelease=TRUE: stream birakilinca arka HGLOBAL de silinir,
        # o yuzden baytlari MUTLAKA release'den once kopyalariz.
        if w.CreateStreamOnHGlobal(None, 1, byref(stream)) != 0 or not stream:
            return None

        clsid = _png_clsid()
        if w.GdipSaveImageToStream(gp_bitmap, stream, byref(clsid), None) != 0:
            return None

        data = _stream_read_all(stream)
        if not data or not data.startswith(_PNG_MAGIC):
            return None
        return data
    except Exception:  # noqa: BLE001
        return None
    finally:
        if gp_bitmap:
            try:
                w.GdipDisposeImage(gp_bitmap)
            except Exception:  # noqa: BLE001
                pass
        _com_release(stream)
        if started:
            try:
                w.GdiplusShutdown(token)
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------- saf yardimcilar (test) ---


def png_dimensions(png_bytes: bytes) -> tuple[int, int] | None:
    """PNG IHDR'den (genislik, yukseklik). SAF fonksiyon; gecersiz veri -> None."""
    if not png_bytes or len(png_bytes) < 24 or not png_bytes.startswith(_PNG_MAGIC):
        return None
    # 8 imza + 4 uzunluk + 4 "IHDR" = 16; offset 16..24 = W,H (big-endian).
    width = int.from_bytes(png_bytes[16:20], "big")
    height = int.from_bytes(png_bytes[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def fit_factor(w: int, h: int, max_w: int, max_h: int) -> int:
    """Onizleme icin tam sayili kucultme carpani (>=1). SAF fonksiyon.

    PhotoImage.subsample yalniz tam sayi kucultur; kutuya sigan en kucuk
    carpani buluruz. Orijinal baytlar DEGISMEZ - gonderilecek olan tam
    cozunurluktur, kucultme sadece ekranda gosterim icin.
    """
    if max_w <= 0 or max_h <= 0:
        return 1
    factor = 1
    while (w // factor) > max_w or (h // factor) > max_h:
        factor += 1
        if factor > 64:   # emniyet: sonsuz donguyu engelle
            break
    return factor


# --------------------------------------------------------- onizleme/onay ---


def preview_and_confirm(png_bytes: bytes, note: str = "",
                        *, timeout_ms: int | None = None) -> bool:
    """PNG'yi goster, "Gonder / Iptal" sun. Yalniz onaylanirsa True.

    GIZLILIK: False donerse cagiran taraf HICBIR sey gondermez. Bu yuzden
    guvenli taraf DAIMA False'tur - tkinter yoksa, PNG bozuksa, pencere capraz
    ile kapatilirsa, sure dolarsa ya da herhangi bir hata olursa False.

    Enter/Gonder = True; Esc/Iptal/kapat = False. timeout_ms verilirse o sure
    icinde karar verilmezse otomatik False (kullanici uzaklastiysa gonderme;
    ayrica otomatik testleri mumkun kilar).
    """
    if tk is None or platform.system() != "Windows":
        return False
    dims = png_dimensions(png_bytes)
    if dims is None:
        return False              # bozuk/eksik goruntu asla gonderilmez
    img_w, img_h = dims

    result = {"ok": False}
    root = None
    try:
        root = tk.Tk()
        root.title("all eye - goruntuyu gonder?")
        root.configure(bg="#12151c")
        root.withdraw()           # yerlesim hesaplanana kadar gizli (titremesin)
        root.attributes("-topmost", True)

        # PhotoImage base64 PNG okur (Tk 8.6+). Diske yazmadan, bellekten.
        b64 = base64.b64encode(png_bytes).decode("ascii")
        photo = tk.PhotoImage(data=b64)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        max_w = max(320, min(_PREVIEW_MAX_W, sw - 80))
        max_h = max(240, min(_PREVIEW_MAX_H, sh - 180))
        factor = fit_factor(img_w, img_h, max_w, max_h)
        shown = photo.subsample(factor) if factor > 1 else photo

        bg, fg, accent, dim = "#12151c", "#d6dde6", "#4aa3ff", "#7c8794"

        tk.Label(root, text="All Eye bu goruntuyu modele gonderecek. Onayliyor musun?",
                 bg=bg, fg=accent, anchor="w", font=("Segoe UI", 10, "bold"),
                 padx=12, pady=8).pack(fill="x")
        if note:
            tk.Label(root, text=note, bg=bg, fg=dim, anchor="w", justify="left",
                     wraplength=max_w, font=("Segoe UI", 9),
                     padx=12).pack(fill="x")

        img_lbl = tk.Label(root, image=shown, bg=bg, bd=1, relief="solid")
        img_lbl.pack(padx=12, pady=6)

        scale = f"onizleme 1/{factor} olceginde · " if factor > 1 else ""
        tk.Label(root, text=f"({scale}gonderilecek: {img_w}x{img_h} px)",
                 bg=bg, fg=dim, font=("Segoe UI", 8)).pack()

        def _send(*_):
            result["ok"] = True
            _finish()

        def _cancel(*_):
            result["ok"] = False
            _finish()

        def _finish():
            try:
                root.quit()
            except Exception:  # noqa: BLE001
                pass

        bar = tk.Frame(root, bg=bg)
        bar.pack(fill="x", padx=12, pady=(8, 12))
        # Iptal saga, varsayilan degil; kaza ile gonderim olmasin.
        tk.Button(bar, text="Iptal (Esc)", command=_cancel,
                  bg="#2a2f3a", fg=fg, activebackground="#3a4150",
                  activeforeground=fg, relief="flat", padx=14, pady=6,
                  font=("Segoe UI", 10)).pack(side="right")
        send_btn = tk.Button(bar, text="Gonder (Enter)", command=_send,
                             bg=accent, fg="#0b1017", activebackground="#6ab5ff",
                             activeforeground="#0b1017", relief="flat",
                             padx=14, pady=6, font=("Segoe UI", 10, "bold"))
        send_btn.pack(side="right", padx=(0, 8))

        root.protocol("WM_DELETE_WINDOW", _cancel)   # capraz = gonderme
        for seq in ("<Return>", "<KP_Enter>"):
            root.bind(seq, _send)
        root.bind("<Escape>", _cancel)

        # Ekranda ortala, sonra goster ve one getir.
        root.update_idletasks()
        rw, rh = root.winfo_reqwidth(), root.winfo_reqheight()
        root.geometry(f"+{max(0, (sw - rw) // 2)}+{max(0, (sh - rh) // 3)}")
        root.deiconify()
        try:
            root.lift()
            root.focus_force()
            send_btn.focus_set()
        except Exception:  # noqa: BLE001
            pass

        # PhotoImage referanslarini canli tut (GC silmesin).
        root._alleye_photo = photo    # type: ignore[attr-defined]
        root._alleye_shown = shown    # type: ignore[attr-defined]

        if timeout_ms and timeout_ms > 0:
            root.after(int(timeout_ms), _cancel)     # sure dolarsa gonderme

        root.mainloop()
        return bool(result["ok"])
    except Exception:  # noqa: BLE001 - herhangi bir hata -> gonderme (gizlilik)
        return False
    finally:
        if root is not None:
            try:
                root.destroy()
            except Exception:  # noqa: BLE001
                pass
