"""Hook kurulumu: shell profillerine idempotent blok ekler."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from alleye import config

BEGIN = "# >>> all eye >>>"
END = "# <<< all eye <<<"

HOOK_SRC = Path(__file__).parent / "hooks"


def launcher() -> list[str]:
    """All Eye'i cagirmanin en saglam yolu: kurulu exe varsa o, yoksa `-m`."""
    exe = shutil.which("alleye")
    if exe:
        return [exe]
    return [sys.executable, "-m", "alleye"]


def _ps_quote(value: str) -> str:
    """PowerShell tek tirnakli literal. json.dumps KULLANMA: ters boluleri
    ikiye katliyor ve PowerShell'de ters bolu kacis karakteri olmadigi icin
    profile 'C:\\\\Users\\\\...' gibi bozuk bir yol yaziliyor."""
    return "'" + value.replace("'", "''") + "'"


def _ps_array(parts: list[str]) -> str:
    return "@(" + ", ".join(_ps_quote(p) for p in parts) + ")"


def _sh_cmd(parts: list[str]) -> str:
    return " ".join('"' + p.replace('"', '\\"') + '"' for p in parts)


def _materialize(name: str, placeholder: str, value: str) -> Path:
    """Hook sablonunu %LOCALAPPDATA%\\AllEye\\hooks altina yazar."""
    dest_dir = config.HOME / "hooks"
    dest_dir.mkdir(parents=True, exist_ok=True)
    text = (HOOK_SRC / name).read_text(encoding="utf-8")
    text = text.replace(placeholder, value)
    dest = dest_dir / name
    newline = "\r\n" if name.endswith(".ps1") else "\n"
    dest.write_text(text, encoding="utf-8", newline=newline)
    return dest


def _splice(profile: Path, block: str, force: bool) -> bool:
    """Profildeki all eye blogunu ekler/gunceller. Degisiklik oldu mu doner."""
    profile.parent.mkdir(parents=True, exist_ok=True)
    old = profile.read_text(encoding="utf-8-sig", errors="replace") if profile.exists() else ""

    if BEGIN in old and END in old:
        head, _, rest = old.partition(BEGIN)
        _, _, tail = rest.partition(END)
        new = head.rstrip() + "\n\n" + block + tail
        if new.strip() == old.strip() and not force:
            return False
    else:
        new = (old.rstrip() + "\n\n" if old.strip() else "") + block

    if profile.exists():
        backup = profile.with_suffix(profile.suffix + ".alleye-bak")
        if not backup.exists():
            backup.write_text(old, encoding="utf-8")
    profile.write_text(new, encoding="utf-8")
    return True


def powershell_profile() -> Path:
    """$PROFILE.CurrentUserAllHosts - OneDrive yonlendirmesini de dogru cozer."""
    for exe in ("powershell", "pwsh"):
        try:
            p = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command",
                 "$PROFILE.CurrentUserAllHosts"],
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="replace")
            path = (p.stdout or "").strip()
            if path:
                return Path(path)
        except (OSError, subprocess.SubprocessError):
            continue
    docs = Path(os.path.expanduser("~")) / "Documents" / "WindowsPowerShell"
    return docs / "profile.ps1"


def powershell_hook_path() -> Path:
    return config.HOME / "hooks" / "alleye.ps1"


def dot_source_line() -> str:
    """Profili yuklemeyen bir kabukta elle calistirilacak satir."""
    return f". {_ps_quote(str(powershell_hook_path()))}"


def install_powershell(force: bool = False) -> tuple[Path, bool]:
    hook = _materialize("alleye.ps1", "@@ALLEYE_CMD@@", _ps_array(launcher()))
    block = f"{BEGIN}\n. {_ps_quote(str(hook))}\n{END}\n"
    profile = powershell_profile()
    return profile, _splice(profile, block, force)


def install_bash(force: bool = False) -> tuple[Path, bool]:
    hook = _materialize("alleye.bash", "@@ALLEYE_CMD_SH@@", _sh_cmd(launcher()))
    posix = str(hook).replace("\\", "/")
    block = (
        f"{BEGIN}\n"
        f'[ -f "{posix}" ] && . "{posix}"\n'
        f"{END}\n"
    )
    rc = Path(os.path.expanduser("~")) / ".bashrc"
    return rc, _splice(rc, block, force)


def uninstall(profile: Path) -> bool:
    if not profile.exists():
        return False
    old = profile.read_text(encoding="utf-8-sig", errors="replace")
    if BEGIN not in old:
        return False
    head, _, rest = old.partition(BEGIN)
    _, _, tail = rest.partition(END)
    profile.write_text(head.rstrip() + "\n" + tail.lstrip(), encoding="utf-8")
    return True
