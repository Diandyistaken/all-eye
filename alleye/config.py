"""Ayarlar ve yol yonetimi. Tum veri tek bir klasorde durur, tasinabilir."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path


def _home() -> Path:
    env = os.environ.get("ALLEYE_HOME")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "AllEye"


HOME = _home()
JOURNAL = HOME / "journal.jsonl"
TRANSCRIPTS = HOME / "transcripts"
DB = HOME / "alleye.db"
CONFIG_FILE = HOME / "config.json"
ENV_FILE = HOME / ".env"

DEFAULTS: dict = {
    # Beyin zinciri: sirayla denenir, ilk cevap veren kazanir.
    "providers": ["gemini", "groq", "ollama"],
    # Model listeleri 2026-07 tarihinde gercek bir ucretsiz anahtarla olculdu.
    # "-latest" takma adlari bilerek zincirde: Google modelleri hizli emekliye
    # ayiriyor, takma ad yeniden adlandirmalari sessizce hayatta kaliyor.
    # Kademe 1-2 hiz ister (durtme/yon), kademe 3 derinlik ister (tam cozum).
    # Buyuk flash modelleri ucretsiz katmanda sik sik 503 "asiri yuk" donuyor;
    # onlari one koymak her cagriyi dakikalara cikariyor. lite modeller
    # olcumde ~0.6sn ve kararli - varsayilan onlar, agir model derin kademede.
    "gemini": {
        "models": [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-flash-lite-latest",
        ],
        "models_deep": [
            "gemini-3.6-flash",
            "gemini-flash-latest",
            "gemini-3.5-flash-lite",
        ],
        "api_key_env": "GEMINI_API_KEY",
    },
    "groq": {
        "models": ["llama-3.3-70b-versatile", "qwen/qwen3-32b"],
        "api_key_env": "GROQ_API_KEY",
    },
    "ollama": {
        "models": ["qwen2.5-coder:7b"],
        "host": "http://127.0.0.1:11434",
    },
    "context": {
        "turns": 12,             # journal'dan okunacak son komut sayisi
        "max_output_chars": 3500,  # tek komut ciktisi ust siniri
        "budget_chars": 24000,    # modele giden toplam baglam butcesi
    },
    "detect": {
        "repeat_threshold": 3,     # ayni komut kac kez tekrarlarsa sinyal
        "fail_streak": 3,          # ust uste kac hata sinyal sayilir
        "stagnation_minutes": 20,  # ilerleme yok sayilan sure
        # Faz 2.1 pasif tespit v2:
        "slowdown_factor": 2.5,    # komut araligi eskisinin kac kati olursa yavaslama
        "loop_window_s": 90,       # ayni komut+ayni hata ardisik denemeler arasi ust sinir
    },
    "redact": True,   # buluta gitmeden once sirlari maskele
    "language": "tr",
    # Pano izleyici (Faz 2): bir hatayi panoya kopyalayinca "aramaya gidiyorsun"
    # sinyali. Pano metni ASLA buluta gitmez - sadece yerelde son hatayla
    # karsilastirilir ve yalniz hata-benzeri metin islenir. Gizlilik icin
    # kapatilabilir: false yap.
    "clipboard_watch": True,
    # Cevap penceresi (Faz 1.3, alleye/window.py). tkinter ile, sifir bagimlilik.
    # window.py bu blok olmadan da varsayilanlarla calisir; buraya konmasi
    # kullaniciya ayar noktasi verir.
    "window": {
        "font_size": 10,
        "width": 480,
        "height": 320,
    },
    # ctrl+alt+space cok yaygin sekilde baska uygulamalarca tutuluyor.
    # Dolu olursa daemon.FALLBACKS listesinden ilk bos olana kendisi duser.
    "hotkey": "ctrl+alt+e",
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


ENV_TEMPLATE = """# All Eye - API anahtarlari
# Bu dosya sadece bu makinede durur. Hicbir yere gonderilmez, git'e girmez.
# Anahtari '=' isaretinin hemen arkasina yapistir; tirnak yok, bosluk yok.

# --- ISTEGE BAGLI ---------------------------------------------------------
# Groq: Gemini gunluk kotasi dolunca otomatik devreye girer.
# Al: https://console.groq.com/keys      Anahtar "gsk_" ile baslar.
GROQ_API_KEY=

# --- ONCE BUNU DOLDUR ----------------------------------------------------
# Gemini: ucretsiz, kredi karti istemez, gunde ~1500 istek.
# Al: https://aistudio.google.com/apikey
# Yeni anahtarlar "AQ.Ab" ile baslar. Eski "AIza" anahtarlari da calisir ama
# Google bunlari Eylul 2026'da tamamen kapatiyor.
# Dosyanin SON satiri bilerek bu: notepad'de imlec buraya duser.
GEMINI_API_KEY="""


def ensure_env_file() -> Path:
    """.env yoksa sablonu olustur. Aranan ama var olmayan dosya sorunu icin."""
    HOME.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.exists():
        ENV_FILE.write_text(ENV_TEMPLATE, encoding="utf-8")
    return ENV_FILE


def mask_secret(value: str) -> str:
    """Anahtari tanimaya yetecek kadar goster, sizdirmadan."""
    if not value:
        return "(bos)"
    if len(value) <= 8:
        return f"{value[:2]}… ({len(value)} kr)"
    return f"{value[:5]}…{value[-2:]} ({len(value)} kr)"


def _is_gemini_key(v: str) -> bool:
    return v.startswith(("AQ.", "AIza"))


def key_is_usable(name: str, value: str) -> bool:
    """Format kesin yanlis mi? Eski AIza anahtari 'usable' sayilir - hala calisiyor."""
    if not value:
        return False
    if name == "GEMINI_API_KEY":
        return _is_gemini_key(value)
    if name == "GROQ_API_KEY":
        return value.startswith("gsk_")
    return True


def key_looks_wrong(name: str, value: str) -> str:
    """Bilinen anahtar formatlarini kontrol et; bos string = sorun yok."""
    if not value:
        return ""
    if name == "GEMINI_API_KEY":
        if value.startswith("AIza"):
            return ("eski 'Standard' anahtar. Calisir ama Google Eylul 2026'da "
                    "kapatiyor; AI Studio'dan yeni bir anahtar al (AQ.Ab...).")
        if value.startswith("gsk_"):
            return "buraya bir GROQ anahtari yapistirilmis. Satirlari karistirmissin."
        if not _is_gemini_key(value):
            return "Gemini anahtari 'AQ.Ab' (yeni) ya da 'AIza' (eski) ile baslar."
    if name == "GROQ_API_KEY" and not value.startswith("gsk_"):
        if _is_gemini_key(value):
            return ("buraya bir GEMINI anahtari yapistirilmis. Bu satiri bosalt, "
                    "anahtari GEMINI_API_KEY= satirina tasi.")
        return "Groq anahtari 'gsk_' ile baslamali."
    return ""


ENV_SOURCE: dict[str, str] = {}


def load_env_file() -> None:
    """%LOCALAPPDATA%\\AllEye\\.env dosyasindaki anahtarlari ortama al.

    utf-8-sig sart: Notepad ve PowerShell'in `Set-Content -Encoding utf8`
    komutu dosyayi BOM ile kaydediyor. BOM temizlenmezse ilk satirin anahtar
    adi gorunmez bir karakterle basliyor ve "kaydettim ama tanimli degil"
    diyen sessiz bir hataya donusuyor.
    """
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().lstrip("﻿")
        if key.lower().startswith(("export ", "set ")):
            key = key.split(None, 1)[1]
        val = val.strip().strip("'\"")
        if not key:
            continue
        if key in os.environ and os.environ[key].strip():
            ENV_SOURCE[key] = "ortam degiskeni (.env yerine bu kullaniliyor)"
        elif val:
            ENV_SOURCE[key] = ".env dosyasi"
        os.environ.setdefault(key, val)


_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    HOME.mkdir(parents=True, exist_ok=True)
    TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    ensure_env_file()
    load_env_file()
    user = {}
    if CONFIG_FILE.exists():
        try:
            user = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"[all eye] config.json okunamadi ({exc}), varsayilanlar kullaniliyor")
    _cache = _merge(DEFAULTS, user)
    return _cache


def write_default_config() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(DEFAULTS, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return CONFIG_FILE
