"""Redaksiyon katmani: hicbir sey buluta gitmeden once buradan gecer.

Onemli tasarim karari: IP, port, hostname, servis surumu, NTLM/NT hash,
kullanici adi VE nmap/gobuster ciktilari MASKELENMEZ. HTB/pentest isinde
mentorun tam da bunlara bakmasi gerekiyor. Maskelenen sey senin gercek
sirlarin: API anahtarlari, ozel anahtarlar, .env degerleri, oturum jetonlari.
"""

from __future__ import annotations

import re

_MASK = "«redacted:{}»"

# (isim, desen, maskelenecek grup) - grup 0 ise tum eslesme maskelenir
_RULES: list[tuple[str, re.Pattern[str], int]] = [
    ("private-key", re.compile(
        r"-----BEGIN[ A-Z]*PRIVATE KEY-----.*?-----END[ A-Z]*PRIVATE KEY-----",
        re.S), 0),
    ("openai-key", re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"), 0),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"), 0),
    # Google'in 2026 "auth key" formati - AQ.Ab... ile baslar, uzunlugu degisken.
    ("google-authkey", re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}"), 0),
    ("groq-key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}"), 0),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{50,}"), 0),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), 0),
    ("hf-token", re.compile(r"\bhf_[A-Za-z0-9]{30,}"), 0),
    ("aws-key-id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), 0),
    ("bearer", re.compile(r"(?i)\b(?:bearer|authorization:\s*bearer)\s+([A-Za-z0-9._\-]{16,})"), 1),
    # .env / export tarzi KEY=VALUE
    ("env-secret", re.compile(
        r"(?im)^\s*(?:export\s+|set\s+|\$env:)?"
        r"([A-Z0-9_]*(?:PASS(?:WORD)?|SECRET|TOKEN|APIKEY|API_KEY|PRIVKEY|CREDENTIAL)[A-Z0-9_]*)"
        r"\s*[:=]\s*(\S+)"), 2),
    ("cli-password", re.compile(r"(?i)(--password[=\s]+|--pass[=\s]+)(\S+)"), 2),
    # Kisa -p bayragi SADECE parola alan araclarin yaninda maskelenir.
    # Yoksa "nmap -p-" veya "nmap -p80,443" yanlislikla silinir - o cikti bize lazim.
    ("tool-password", re.compile(
        r"(?i)\b(?:mysql|mysqldump|psql|smbclient|mssqlclient\.py|evil-winrm|sshpass|"
        r"rdesktop|xfreerdp|redis-cli)\b[^\n]{0,120}?\s-p(\S+)"), 1),
    ("smb-userpass", re.compile(r"(?i)(-U\s+[^\s%]+%)(\S+)"), 2),
    # baglanti dizesi: proto://user:pass@host
    ("conn-string", re.compile(r"(\w+://[^\s:/@]+:)([^\s@]+)(@)"), 2),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Metni maskele. (temiz_metin, tetiklenen_kural_isimleri) doner."""
    if not text:
        return text, []
    hits: list[str] = []

    for name, pattern, group in _RULES:
        def _sub(m: re.Match[str], _n=name, _g=group) -> str:
            if _n not in hits:
                hits.append(_n)
            if _g == 0:
                return _MASK.format(_n)
            start, end = m.span(_g)
            return m.group(0)[: start - m.start()] + _MASK.format(_n) + m.group(0)[end - m.start():]

        text = pattern.sub(_sub, text)

    return text, hits


def redact_if(enabled: bool, text: str) -> tuple[str, list[str]]:
    return redact(text) if enabled else (text, [])
