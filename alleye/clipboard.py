"""Pano izleyici: ses tetikleyicisinin bagimliliksiz alternatifi.

Fikir basit: kullanici bir hata mesajini panoya kopyaladiysa buyuk
olasilikla onu Google/StackOverflow'da aramaya gidiyor - bu da "takildim"
demenin dolayli bir yolu. Ses/ekran goruntusu yerine (bagimlilik, gizlilik,
VRAM derdi) sadece pano metnini saf ctypes ile okuyoruz.

Windows disinda / erisim yoksa her fonksiyon nazikce bos/None doner,
hicbir yerde patlamaz - daemon._passive_loop bu modulu hic sorgusuz cagirir.
"""

from __future__ import annotations

import ctypes
import platform
import time

from alleye import detect
from alleye.journal import Turn

_CF_UNICODETEXT = 13

# journal.fingerprint'teki hata anahtar kelimeleriyle ayni ruhta - ayrik bir
# sozluk tutmak yerine mumkun oldugunca ayni kelimeler kullanildi ki "bu bir
# hata mi" sorusunun cevabi tum projede tutarli olsun.
_ERROR_KEYWORDS = (
    "error", "exception", "traceback", "failed", "fatal", "denied", "refused",
    "not found", "no such", "cannot", "unable", "panic:", "segmentation fault",
    "hata", "bulunamadi", "erisim reddedildi",
)

# Kopyalanan butun bir dosya/makale hata mesaji sayilmasin diye ust sinir.
# Bir stack trace rahatlikla bu sinirlarin altinda kalir.
_MAX_CHARS = 4000
_MAX_LINES = 60


def available() -> bool:
    """Windows'ta ve user32/kernel32 erisilebilir mi?"""
    if platform.system() != "Windows":
        return False
    try:
        ctypes.windll.user32
        ctypes.windll.kernel32
        return True
    except Exception:
        return False


def read_text() -> str:
    """Pano metnini oku (CF_UNICODETEXT). Windows disinda / hata / bos -> "".

    OpenClipboard baska bir uygulama tarafindan anlik kilitlenmis olabilir;
    birkac kez kisa aralikla denenir. Ne olursa olsun GlobalUnlock ve
    CloseClipboard ile temizlenir - pano acik unutulursa sistem genelinde
    kopyala/yapistir bozulur.
    """
    if not available():
        return ""
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        u32.OpenClipboard.restype = ctypes.c_int
        u32.GetClipboardData.argtypes = [ctypes.c_uint]
        u32.GetClipboardData.restype = ctypes.c_void_p
        u32.CloseClipboard.restype = ctypes.c_int
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    except Exception:
        return ""

    opened = False
    for _ in range(3):
        try:
            if u32.OpenClipboard(None):
                opened = True
                break
        except Exception:
            return ""
        time.sleep(0.05)
    if not opened:
        return ""

    try:
        handle = u32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        ptr = k32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            text = ctypes.wstring_at(ptr)
        finally:
            k32.GlobalUnlock(handle)
        return text or ""
    except Exception:
        return ""
    finally:
        try:
            u32.CloseClipboard()
        except Exception:
            pass


def looks_like_error(text: str) -> bool:
    """SAF: pano metni bir hataya benziyor mu?

    Kisa/orta uzunlukta (kopyalanmis butun bir dosya degil) VE en az bir
    hata anahtar kelimesi iceriyorsa True. Yan etkisi yok, pano/IO yok.
    """
    if not text:
        return False
    t = text.strip()
    if not t or len(t) > _MAX_CHARS:
        return False
    if t.count("\n") + 1 > _MAX_LINES:
        return False
    low = t.lower()
    return any(kw in low for kw in _ERROR_KEYWORDS)


def _meaningful_lines(text: str) -> list[str]:
    """Karsilastirmaya deger satirlar: kisa/gurultu satirlari elenir."""
    out: list[str] = []
    for line in (text or "").splitlines():
        norm = " ".join(line.strip().lower().split())
        if len(norm) < 8:
            continue
        if norm.startswith(("+", "at ")):
            continue  # PowerShell yigin izi gurultusu (journal.fingerprint ile ayni ruh)
        out.append(norm)
    return out


def _overlaps(clip_text: str, turn_out: str) -> bool:
    """Pano metni ile komut ciktisi arasinda ortak anlamli bir satir var mi?"""
    clip_lines = _meaningful_lines(clip_text)
    out_lines = _meaningful_lines(turn_out)
    if not clip_lines or not out_lines:
        return False
    for cl in clip_lines:
        for ol in out_lines:
            if cl in ol or ol in cl:
                return True
    return False


def clipboard_signal(clip_text: str, turns: list[Turn]) -> detect.Signal | None:
    """Pano bir hataya benziyor VE son basarisiz komutun ciktisiyla ortusuyorsa sinyal.

    Ortusme yoksa (kullanici alakasiz bir sey kopyalamis) ya da hicbir
    basarisiz komut yoksa None doner - burada yanlis alarm vermek pahali,
    kullanici araci ilk gun kapatir.
    """
    if not looks_like_error(clip_text):
        return None
    if not turns:
        return None

    last_failed: Turn | None = None
    for t in reversed(turns):
        if getattr(t, "failed", False):
            last_failed = t
            break
    if last_failed is None:
        return None

    if not _overlaps(clip_text, last_failed.out):
        return None

    snippet = clip_text.strip().splitlines()[0][:100]
    return detect.Signal("pano-arama", 2, f"pano hatayla ortusuyor: {snippet}")
