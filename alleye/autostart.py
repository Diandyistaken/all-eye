"""Otomatik baslatma: Startup klasorune bir kisayol koyar, yonetici gerekmez.

.lnk dosyasi bir COM nesnesidir (IShellLink); onu Python'dan uretmek normalde
pywin32/win32com ister. Sifir bagimlilik kurali geregi paket YOK: kisayolu
PowerShell'in WScript.Shell COM'u ile (subprocess) yaziyoruz.

Konsol parlamasi tuzagi: hedef python.exe olursa her acilista bir konsol
penceresi caksin diye gorunuyor. Bu yuzden hedef olarak once pythonw.exe
(penceresiz yorumlayici) secilir; kisayol da minimize baslatilir.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Startup klasorundeki kisayol adi. Sabit ad idempotanligi garantiler:
# ayni ada tekrar yazmak tek dosya birakir, cogaltmaz.
SHORTCUT_NAME = "All Eye.lnk"


# --------------------------------------------------------------- yardimcilar ---

def _is_windows() -> bool:
    return platform.system() == "Windows"


def _ps_quote(value: str) -> str:
    """PowerShell tek tirnakli literal. json.dumps KULLANMA: ters boluleri
    ikiye katliyor ve PowerShell'de ters bolu kacis karakteri olmadigi icin
    'C:\\\\Users\\\\...' gibi bozuk bir yol cikiyor. install._ps_quote ile ayni
    mantik; autostart kendi kendine yetsin diye burada tekrar tanimli."""
    return "'" + value.replace("'", "''") + "'"


def _join_args(parts: list[str]) -> str:
    """Kisayolun Arguments alanina tek satirlik komut satiri uret. Bosluk ya da
    cift tirnak iceren parcalari cift tirnakla sar."""
    out: list[str] = []
    for p in parts:
        if not p or " " in p or '"' in p:
            out.append('"' + p.replace('"', '\\"') + '"')
        else:
            out.append(p)
    return " ".join(out)


def _powershell_exe() -> str | None:
    """Kisayolu uretecek PowerShell'i bul. Once Windows PowerShell, sonra pwsh."""
    for exe in ("powershell", "pwsh"):
        if shutil.which(exe):
            return exe
    return None


def _pythonw() -> str | None:
    """Mevcut yorumlayicinin yanindaki pythonw.exe. Konsol acmaz, bu yuzden
    otomatik baslatmada tercih edilir. venv'de Scripts\\pythonw.exe olur."""
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    if cand.exists():
        return str(cand)
    return None


def _working_dir() -> str:
    """Kisayolun calisma dizini. alleye paketinin ust klasoru: `-m alleye`
    hem pip ile kurulu hem de kaynaktan calisan kurulumda buradan cozulur."""
    return str(Path(__file__).resolve().parent.parent)


# ------------------------------------------------------------------ yollar ---

def startup_dir() -> Path:
    """%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup.

    Buradaki kisayollar kullanici oturum acinca calisir; yonetici izni istemez.
    """
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path(os.path.expanduser("~")) / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def shortcut_path(directory: Path | None = None) -> Path:
    """Kisayol dosyasinin tam yolu. directory verilirse (test) o kullanilir."""
    base = directory if directory is not None else startup_dir()
    return Path(base) / SHORTCUT_NAME


def launch_target() -> list[str]:
    """Kisayolun calistiracagi komut: `alleye watch --tray`.

    install.launcher() mantigini ornek alir ama pencere gizleyen yorumlayiciyi
    one koyar (konsol parlamasi olmasin):
      1) pythonw.exe -m alleye watch --tray   (tercih; konsol acmaz)
      2) kurulu alleye.exe watch --tray        (pythonw yoksa)
      3) python.exe -m alleye watch --tray     (son care)
    """
    tail = ["watch", "--tray"]
    pyw = _pythonw()
    if pyw:
        return [pyw, "-m", "alleye", *tail]
    exe = shutil.which("alleye")
    if exe:
        return [exe, *tail]
    return [sys.executable, "-m", "alleye", *tail]


# ------------------------------------------------------- kisayol uretimi ---

def _create_shortcut(path: Path, target: list[str]) -> None:
    """WScript.Shell ile .lnk uret. Windows + PowerShell sart.

    Ayri fonksiyon: testler bunu mock'layarak dosya yonetimi mantigini
    (idempotanlik, silme) gercek PowerShell olmadan dogrulayabilsin."""
    ps = _powershell_exe()
    if ps is None:
        raise RuntimeError("PowerShell bulunamadi - kisayol uretilemiyor")

    exe = target[0]
    args = _join_args(target[1:])
    script = (
        "$ErrorActionPreference='Stop';"
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut({_ps_quote(str(path))});"
        f"$s.TargetPath={_ps_quote(exe)};"
        f"$s.Arguments={_ps_quote(args)};"
        f"$s.WorkingDirectory={_ps_quote(_working_dir())};"
        "$s.WindowStyle=7;"  # 7 = minimize; exe'ye duserse konsol parlamasini kisar
        f"$s.Description={_ps_quote('All Eye - otomatik baslatma')};"
        "$s.Save()"
    )
    proc = subprocess.run(
        [ps, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0 or not path.exists():
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"kisayol uretilemedi: {detail or 'bilinmeyen hata'}")


# --------------------------------------------------------------- genel API ---

def is_enabled(directory: Path | None = None) -> bool:
    """Otomatik baslatma acik mi (kisayol dosyasi var mi)."""
    # Gercek kullanimda (directory=None) Windows disinda anlamsiz -> False.
    # Enjekte edilmis dizinde (test) platformdan bagimsiz dosya varligina bak.
    if directory is None and not _is_windows():
        return False
    return shortcut_path(directory).exists()


def enable(directory: Path | None = None) -> Path:
    """Startup kisayolunu olustur, yolunu don. Idempotent: ayni ada yazdigi
    icin iki kez cagrilinca tek kisayol kalir."""
    if directory is None and not _is_windows():
        raise OSError("otomatik baslatma sadece Windows'ta desteklenir")
    path = shortcut_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    _create_shortcut(path, launch_target())
    return path


def disable(directory: Path | None = None) -> bool:
    """Kisayol varsa sil. Gercekten silindiyse True, zaten yoksa False."""
    path = shortcut_path(directory)
    if path.exists():
        path.unlink()
        return True
    return False


def status(directory: Path | None = None) -> str:
    """Insan-okur durum satiri (cli `autostart` icin)."""
    if directory is None and not _is_windows():
        return "otomatik baslatma: sadece Windows'ta desteklenir"
    if is_enabled(directory):
        return f"otomatik baslatma: acik  ({shortcut_path(directory)})"
    return "otomatik baslatma: kapali"
