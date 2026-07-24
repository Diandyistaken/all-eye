"""Testlerin gercekten bir sey koruyup korumadigini olcer.

Yesil bir test paketi hicbir sey kanitlamaz - bos bir paket de yesildir.
Bu arac bilinen her tuzagi kaynak koda GERI GETIRIR ve testin kirmiziya
dustugunu dogrular. Duserse ag saglam, dusmezse test yalanci yesil.

Proje dosyalarina DOKUNMAZ: her tur icin gecici bir kopya cikarilir.

    .venv\\Scripts\\python.exe tools\\mutation_check.py

Bir tuzak "esdeger mutant" olarak isaretliyse, o savunmanin tek basina
kaldirilmasi davranisi degistirmiyor demektir (ornek: BOM'a karsi uc ayri
savunma var). Testin kirmiziya dusmesi icin hepsinin birden kalkmasi gerekir.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not PY.exists():
    PY = Path(sys.executable)

BOM = "﻿"

# (ad, dosya, [(aranan, yerine), ...], hedef test, kirmizi bekleniyor mu)
MUTATIONS: list[tuple[str, str, list[tuple[str, str]], str, bool]] = [
    ("1  bayat $LASTEXITCODE cmdlet hatasina yapisiyor",
     "alleye/hooks/alleye.ps1",
     [("if ($fresh -and ($null -ne $Lec) -and ($Lec -ne 0)) { $exit = [int]$Lec }",
       "if (($null -ne $Lec) -and ($Lec -ne 0)) { $exit = [int]$Lec }")],
     "tests.test_hook_powershell.TestPowerShellHook"
     ".test_stale_exit_code_does_not_leak_into_cmdlet_error", True),

    ("2a .env BOM · sadece encoding savunmasi kalkti",
     "alleye/config.py",
     [('ENV_FILE.read_text(encoding="utf-8-sig", errors="replace")',
       'ENV_FILE.read_text(encoding="utf-8", errors="replace")')],
     "tests.test_config.TestLoadEnvFile", False),

    ("2b .env BOM · sadece satir lstrip'i kalkti",
     "alleye/config.py",
     [(f'line = line.strip().lstrip("{BOM}")', "line = line.strip()")],
     "tests.test_config.TestLoadEnvFile", False),

    ("2c .env BOM · her uc savunma birden kalkti",
     "alleye/config.py",
     [('ENV_FILE.read_text(encoding="utf-8-sig", errors="replace")',
       'ENV_FILE.read_text(encoding="utf-8", errors="replace")'),
      (f'line = line.strip().lstrip("{BOM}")', "line = line.strip()"),
      (f'key = key.strip().lstrip("{BOM}")', "key = key.strip()")],
     "tests.test_config.TestLoadEnvFile.test_bom_prefixed_file", True),

    ("3  install yine config.json yaziyor",
     "alleye/install.py",
     [("def install_powershell(force: bool = False) -> tuple[Path, bool]:",
       "def install_powershell(force: bool = False) -> tuple[Path, bool]:\n"
       "    config.write_default_config()")],
     "tests.test_install.TestMaterialize.test_nobody_calls_write_default_config", True),

    ("4  gemini anahtari URL'ye geri kondu (?key=)",
     "alleye/brain/providers.py",
     [('url = f"{self.BASE}/{model}:streamGenerateContent?alt=sse"',
       'url = f"{self.BASE}/{model}:streamGenerateContent?alt=sse&key={key}"')],
     "tests.test_provider.TestGeminiAuth.test_key_never_in_url", True),

    ("5  olu model adi zincire geri girdi",
     "alleye/config.py",
     [('"gemini-3.5-flash-lite",\n            "gemini-3.1-flash-lite",',
       '"gemini-2.0-flash",\n            "gemini-3.1-flash-lite",')],
     "tests.test_config.TestModelChain", True),

    ("6  -NoProfile tespiti korlesti",
     "alleye/cli.py",
     [('return os.environ.get("ALLEYE_HOOK_LOADED") == "1"', "return True")],
     "tests.test_install.TestHookLiveDetection.test_not_detected_when_absent", True),

    ("7  profile yol yazarken json.dumps'a donuldu",
     "alleye/install.py",
     [("return \"'\" + value.replace(\"'\", \"''\") + \"'\"", "return json.dumps(value)")],
     "tests.test_install.TestPsQuote", True),

    ("R  redaksiyon nmap -p bayragini yiyor",
     "alleye/redact.py",
     [(r'r"(?i)\b(?:mysql|mysqldump|psql|smbclient|mssqlclient\.py|evil-winrm|sshpass|"',
       r'r"(?i)\b(?:nmap|mysql|mysqldump|psql|smbclient|mssqlclient\.py|evil-winrm|sshpass|"')],
     "tests.test_redact.TestPentestOutputUntouched.test_nmap_port_flags_survive", True),

    ("J  imzada PowerShell gurultu filtresi kalkti",
     "alleye/journal.py",
     [('if not stripped or stripped.startswith(("+", "At ")):', "if not stripped:")],
     "tests.test_journal.TestFingerprint.test_powershell_noise_lines_skipped", True),

    ("D  zorlanma esigi config yerine sabit kodlandi",
     "alleye/detect.py",
     [('if n >= cfg["repeat_threshold"]:', "if n >= 3:")],
     "tests.test_detect.TestScoring.test_config_thresholds_are_honoured", True),

    ("C  recent_files ana klasor korumasi kalkti",
     "alleye/context.py",
     [('    if _is_home_or_root(root):\n        return ""', '    if False:\n        return ""')],
     "tests.test_context.TestGuards.test_home_directory_returns_empty", True),
]


def fresh_copy(work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "alleye", work / "alleye", ignore=ignore)
    shutil.copytree(ROOT / "tests", work / "tests", ignore=ignore)


def run(work: Path, target: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), "-m", "unittest", target],
                          cwd=work, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=300)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="alleye-mut-") as tmp:
        work = Path(tmp) / "mut"
        fresh_copy(work)
        base = run(work, "discover")
        if base.returncode != 0:
            print("kopya agacta baseline KIRMIZI - mutasyon testi anlamsiz")
            print(base.stderr[-3000:])
            return 1
        print(f"baseline: {base.stderr.strip().splitlines()[-3]}\n")

        bad = 0
        for name, rel, edits, target, expect_red in MUTATIONS:
            fresh_copy(work)
            path = work / rel
            text = path.read_text(encoding="utf-8")
            applied = True
            for old, new in edits:
                if text.count(old) != 1:
                    print(f"[?] {name:48s} desen {text.count(old)} kez bulundu")
                    applied = False
                    break
                text = text.replace(old, new)
            if not applied:
                bad += 1
                continue
            path.write_text(text, encoding="utf-8")

            red = run(work, target).returncode != 0
            good = red == expect_red
            state = "KIRMIZI" if red else "YESIL"
            note = "" if red else "  (esdeger mutant)"
            print(f"[{state:7s} {'OK' if good else 'BEKLENMEDIK':11s}] {name}{note}")
            bad += 0 if good else 1

    print("\n" + ("tum tuzaklar yakalandi" if not bad else f"{bad} tuzak YAKALANMADI"))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
