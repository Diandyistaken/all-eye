"""Siber guvenlik modu (Faz 5): HTB/CTF icin ozellesmis mentor.

Projenin baslangic sebebi buydu. Fikir: bir hedefe sizmaya calistigini
KENDILIGINDEN anla (nmap/gobuster gibi araclari bir IP'ye karsi calistirinca),
ve cevabi yapistirmak yerine yol goster. Kullanici tam cozumu ACIKCA
isterse (nasil sorduğundan anlariz) o zaman tam cozumu ver.

Bu dosya SAF mantiktir - ag cagrisi, model cagrisi, disk yazimi YOK:
  - hedef/pentest baglami tespiti (journal'daki komutlardan)
  - nmap / gobuster / ffuf / feroxbuster ciktisi ayristirma
  - "neyi denemedin": bulunan ama dokunulmayan yuzeyler
  - niyet algisi: kullanici ipucu mu tam cozum mu istiyor (kademe secimi)

Oturum kalicilizi (start/status/report) store.py'de; prompt mentor.py'de.

--- Metodoloji dayanagi ---
Standart pentest asamalari: kesif -> enumerasyon -> somuru -> yetki yukseltme
-> raporlama. Karakteristik desen: yuzeyleri GENISLEMESINE tara, sonra umut
vaat edeni DERINLEMESINE somur. "Neyi denemedin" analizi tam da bu genislemesine
taramanin bosluklarini gosterir (arxiv 2602.17622, pentest metodoloji kaynaklari).

--- Kademe kurali (Faz 5'te sikilastirilir) ---
Flag ve tam exploit zinciri kademe 1-2'de ASLA acilmaz. Kademe 3 tam cozumu
verir ama once kavrami anlatir. HTB/CTF YETKILI bir laboratuvardir; yardim
mesrudur - kural pedagoji icindir, reddetmek icin degil.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field

from alleye.journal import Turn

# Pentest araclari - bunlardan biri bir hedefe karsi calisiyorsa "box modu".
_PENTEST_TOOLS = {
    "nmap", "masscan", "rustscan", "gobuster", "ffuf", "feroxbuster", "dirb",
    "dirbuster", "nikto", "wpscan", "hydra", "medusa", "crackmapexec", "cme",
    "netexec", "nxc", "smbclient", "smbmap", "enum4linux", "enum4linux-ng",
    "evil-winrm", "impacket", "psexec.py", "secretsdump.py", "getuserspns.py",
    "wfuzz", "sqlmap", "searchsploit", "msfconsole", "msfvenom", "responder",
    "kerbrute", "ldapsearch", "rpcclient", "showmount", "onesixtyone", "snmpwalk",
    "hashcat", "john", "sslscan", "whatweb", "curl", "wget", "nc", "ncat", "netcat",
}

# HTB sanal ag araliklari + genel lab araliklari. Buralara giden trafik pentest.
_HTB_HINTS = re.compile(r"\b10\.10\.1[0-4]\.\d{1,3}\b|\.htb\b|\bhtb\b", re.I)


@dataclass
class Finding:
    """Kesfedilen tek bir saldiri yuzeyi (port, yol, servis...)."""
    kind: str          # "port" | "path" | "service" | "cred" | "host"
    value: str         # "8080", "/admin", "kerberos"...
    detail: str = ""   # "http nginx 1.18.0", "Status 200 Size 1234"...
    ts: float = 0.0    # kesfedildigi an (journal turn'unun ts'i)

    def key(self) -> str:
        return f"{self.kind}:{self.value}"


# ------------------------------------------------------- baglam tespiti ---


def find_target(turns: list[Turn]) -> str | None:
    """Son komutlarda hedef IP/host bul. En son gecen kazanir (guncel hedef).

    IP'yi tercih eder; yoksa *.htb host adi. Loopback/0.0.0.0 sayilmaz.
    """
    host = None
    for t in turns:
        # IPv4 adaylari
        for m in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", t.cmd):
            try:
                ip = ipaddress.ip_address(m)
            except ValueError:
                continue
            if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
                continue
            host = m
        # *.htb host adlari
        for m in re.findall(r"\b[\w-]+\.htb\b", t.cmd, re.I):
            host = m
    return host


def is_pentest_context(turns: list[Turn]) -> bool:
    """Son komutlar bir hedefe karsi pentest araci calistirildigini gosteriyor mu?

    Iki sinyalden biri yeter: (a) bilinen bir pentest araci bir HTB/lab hedefine
    karsi, ya da (b) birden cok farkli pentest araci arka arkaya. Tek basina
    `curl example.com` pentest sayilmaz - hedef lab araligi ya da .htb olmali,
    ya da nmap/gobuster gibi acikca saldirgan bir arac kullanilmali.
    """
    aggressive = {"nmap", "masscan", "rustscan", "gobuster", "ffuf", "feroxbuster",
                  "nikto", "wpscan", "hydra", "crackmapexec", "netexec", "nxc",
                  "enum4linux", "evil-winrm", "sqlmap", "kerbrute", "smbmap"}
    tools_seen: set[str] = set()
    for t in turns:
        tok = (t.cmd.split() or [""])[0].lower().rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        tok = tok.removesuffix(".py").removesuffix(".exe")
        if tok in _PENTEST_TOOLS:
            tools_seen.add(tok)
            # Acikca saldirgan bir arac -> tek basina yeter.
            if tok in aggressive:
                return True
        # Bilinen bir arac + lab hedefi
        if tok in _PENTEST_TOOLS and _HTB_HINTS.search(t.cmd):
            return True
    # Birden cok farkli pentest araci -> muhtemelen bir kutu uzerinde calisiliyor
    return len(tools_seen) >= 2


# ------------------------------------------------------------ ayristirma ---

_NMAP_PORT = re.compile(
    r"^\s*(\d{1,5})/(tcp|udp)\s+(open|open\|filtered|filtered)\s+(\S+)(?:\s+(.*))?$",
    re.I)


def parse_nmap(text: str, ts: float = 0.0) -> list[Finding]:
    """nmap ciktisindan acik portlari cikar. Kapali/filtered atlanir (open* kalir)."""
    out: list[Finding] = []
    for line in (text or "").splitlines():
        m = _NMAP_PORT.match(line)
        if not m:
            continue
        port, proto, state, service, version = m.groups()
        if "open" not in state.lower():
            continue
        detail = service
        if version:
            detail = f"{service} {version.strip()}"
        out.append(Finding("port", f"{port}/{proto}", detail.strip(), ts))
    return out


# gobuster/dirb: "/admin (Status: 200) [Size: 1234]"
_GOBUSTER = re.compile(r"^\s*(/\S*)\s*\(Status:\s*(\d{3})\)(?:\s*\[Size:\s*(\d+)\])?", re.I)
# ffuf/feroxbuster/wfuzz: bir yol/kelime + "[Status: 200" ya da satir basi "200 GET"
_FFUF = re.compile(r"(\S+)\s*\[Status:\s*(\d{3})", re.I)
_FEROX = re.compile(r"^\s*(\d{3})\s+\w+\s+.*?\s(\S+)\s*$")


def parse_web_paths(text: str, ts: float = 0.0) -> list[Finding]:
    """gobuster/ffuf/feroxbuster/dirb ciktisindan bulunan yollari cikar.

    404'ler atlanir (gurultudur); 200/301/302/401/403 ilginctir - ozellikle
    403 "var ama yetki gerek" demektir, es gecilmemeli.
    """
    out: list[Finding] = []
    seen: set[str] = set()
    for line in (text or "").splitlines():
        path = status = None
        m = _GOBUSTER.match(line)
        if m:
            path, status = m.group(1), m.group(2)
        else:
            m = _FEROX.match(line)
            if m and m.group(2).startswith(("/", "http")):
                status, path = m.group(1), m.group(2)
            else:
                m = _FFUF.search(line)
                if m:
                    path, status = m.group(1), m.group(2)
        if not path or not status:
            continue
        if status == "404":
            continue
        # http://host/admin -> /admin (yalniz yol kismini tut)
        short = re.sub(r"^https?://[^/]+", "", path)
        if short in seen:
            continue
        seen.add(short)
        out.append(Finding("path", short, f"Status {status}", ts))
    return out


def parse_output(cmd: str, out: str, ts: float = 0.0) -> list[Finding]:
    """Komuta bakip dogru ayristiriciyi sec. Bilinmeyen arac -> bos liste."""
    low = cmd.lower()
    if "nmap" in low or "rustscan" in low or "masscan" in low:
        return parse_nmap(out, ts)
    if any(t in low for t in ("gobuster", "ffuf", "feroxbuster", "dirb", "wfuzz")):
        return parse_web_paths(out, ts)
    return []


def collect_findings(turns: list[Turn]) -> list[Finding]:
    """Tum journal'i tarayip kesfedilen yuzeyleri topla (imzaya gore tekil)."""
    found: dict[str, Finding] = {}
    for t in turns:
        for f in parse_output(t.cmd, t.out, t.ts):
            found.setdefault(f.key(), f)   # ilk kesif zamani korunur
    return list(found.values())


# --------------------------------------------------- neyi denemedin ---


def untouched(findings: list[Finding], turns: list[Turn]) -> list[Finding]:
    """Kesfedildikten SONRA hicbir komutta gecmeyen yuzeyler.

    Ornek: nmap 8080'i buldu ama sonra hic `curl ...:8080` yapmadin -> 8080
    dokunulmamis. gobuster /admin buldu ama hic ziyaret etmedin -> /admin
    dokunulmamis. Bu, "genislemesine tara, derinlemesine somur" desenindeki
    bosluktur - saldirinin en cok atladigi yer.
    """
    out: list[Finding] = []
    for f in findings:
        # Port icin sadece numarayi, yol icin yolu ara.
        needle = f.value.split("/")[0] if f.kind == "port" else f.value
        touched = any(
            needle and needle in t.cmd and t.ts > f.ts + 0.001
            for t in turns
        )
        if not touched:
            out.append(f)
    return out


def phase(findings: list[Finding], turns: list[Turn]) -> str:
    """Kabaca hangi asamadasin? Rapor ve prompt icin baglam."""
    cmds = " ".join(t.cmd.lower() for t in turns)
    if any(k in cmds for k in ("evil-winrm", "psexec", "ssh ", "sudo ",
                               "getsystem", "privesc", "linpeas", "winpeas")):
        return "somuru/yetki-yukseltme"
    if findings:
        return "enumerasyon"
    if any(k in cmds for k in ("nmap", "rustscan", "masscan")):
        return "kesif"
    return "baslangic"


# ------------------------------------------------------------ niyet algisi ---
# Kullanici IPUCU mu TAM COZUM mu istiyor? Sorusundan anla, ona gore kademe sec.
# Kullanici hiz istiyor: dogru kademeyi tek seferde yakalayip gereksiz tur atmayalim.

# Tam cozum isteyen acik ifadeler (kademe 3).
# Turkce ekler kesme isaretiyle gelir (exploit'i, payload'u); ['’]?\w* buna
# tolerans tanir. \b yerine gevsek sinir - suffix'ler kelime sinirini kaydiriyor.
_WANT_FULL = re.compile(
    r"(?i)("
    r"tam\s*cozum|cozum[u'’\w]*\s*(ver|goster|soyle|ne)|direkt\s*(ver|soyle)|"
    r"komut[u'’\w]*\s*(ver|ne|goster)|exploit[i'’\w]*\s*(ver|goster|nedir|ne|al)|"
    r"nasil\s+(root|user|shell|giris|sizar|exploit|yetki)|"
    r"root\s*ol|shell\s*al|reverse\s*shell|payload|"
    r"cevab[i'’\w]*\s*ver|spoiler|acikla\s*hepsini|"
    r"just\s*(give|tell|show)|full\s*(solution|answer)|how\s*do\s*i|give\s*me"
    r")")

# Yon isteyen ifadeler (kademe 2). Kapanis \b yok: Turkce ekleri
# (baslamaliyim, yontemi...) kelime sinirini kaydiriyor.
_WANT_DIR = re.compile(
    r"(?i)(yon\s*(ver|goster)|hangi\s*(yol|yontem|arac|adim)|"
    r"nereden\s*basla|ne\s*deneme|siradaki\s*adim|next\s*step|which\s*(way|approach))")

# Sadece ipucu / dürtme (kademe 1) - varsayilan zaten bu.
_WANT_HINT = re.compile(
    r"(?i)\b(ipucu|dürt|durt|takildim|nereye\s*bak|hint|nudge|kucuk\s*bir)\b")


def infer_level(question: str, default: int = 1) -> int:
    """Sorunun niyetinden kademe cikar. Bulamazsa `default` (varsayilan 1=ipucu).

    En yuksek eslesen kazanir: kullanici "tam cozum" dediyse yon/ipucu
    kelimeleri de gecse bile 3 doner.
    """
    q = question or ""
    if _WANT_FULL.search(q):
        return 3
    if _WANT_DIR.search(q):
        return 2
    if _WANT_HINT.search(q):
        return 1
    return default


# ------------------------------------------------------- prompt baglami ---


def render_box(target: str, findings: list[Finding], untried: list[Finding],
               phase_name: str = "") -> str:
    """Bulunan yuzeyleri ve denenmeyenleri modele giden metne cevir.

    "Neyi denemedin" bolumu bilerek EN USTTE ve ayri: mentorun once oraya
    bakmasini istiyoruz (saldirinin en cok atladigi yer).
    """
    lines = ["## HEDEF", target or "(hedef belirlenmedi)"]
    if phase_name:
        lines.append(f"asama: {phase_name}")

    if untried:
        lines += ["", "## HENUZ DENENMEYEN YUZEYLER (once bunlara bak)"]
        for f in untried:
            d = f" - {f.detail}" if f.detail else ""
            lines.append(f"- {f.kind}: {f.value}{d}")

    ports = [f for f in findings if f.kind == "port"]
    paths = [f for f in findings if f.kind == "path"]
    if ports:
        lines += ["", "## ACIK PORTLAR / SERVISLER"]
        lines += [f"- {f.value}: {f.detail}" for f in ports]
    if paths:
        lines += ["", "## BULUNAN YOLLAR"]
        lines += [f"- {f.value} ({f.detail})" for f in paths]
    return "\n".join(lines)
