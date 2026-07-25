"""Ogrenen hafiza (Faz 4): duvarlari konuya gore kumele, kendine ayna tut.

Faz 0-3 veri topladi; bu modul onu YORUMLUYOR. Model cagrisi YOK - hepsi
yerel, cevrimdisi ve aninda. "Bu duvara 4. kez carpiyorsun" cumlesini
"sen ag/port konusunda hep ayni yerde takiliyorsun"a cevirir.

--- Error Quotient (EQ) uyarlamasi ---
Jadud'un Error Quotient'i (2006) ardisik DERLEME olaylarini ciftler halinde
puanlayip [0,1] araliginda bir "zorlanma" skoru uretir. Orijinal algoritma
(Villamor 2020 incelemesinden birinci elden dogrulandi):

    ciftler: (e1,e2), (e2,e3), ... (e_{n-1}, e_n)
    ikisi de hata verdi mi?      hayir -> 0
    evet                          -> +2
    ayni hata tipi                -> +3
    ayni hata konumu              -> +3
    ayni duzenleme konumu         -> +1
    her cift /9 ile normalize, sonra TUM ciftlerin ortalamasi

Dogrulama: makalenin kendi ornegi 2+3+3=8 -> 8/9=0.88 -> 0.88/3=0.29.

BIZ KABUK KOMUTLARINA UYARLIYORUZ (derleme olayi yok, komut var):
    ikisi de basarisiz (exit != 0)     -> +2
    ayni hata imzasi (fingerprint)     -> +3   [orijinal: ayni hata tipi]
    ayni komut (normalize)             -> +3   [orijinal: ayni hata konumu]
    ayni dizin (cwd)                   -> +1   [orijinal: ayni duzenleme konumu]
    /9, sonra ortalama

DURUST SINIR: literatur EQ'nun ders notu varyansinin en fazla ~%26'sini
acikladigini soyluyor (Svabensky 2024). Yani EQ BECERI OLCMEZ; bir oturumdaki
zorlanmayi olcer. Bizim kullanimimiz zaten bu: kullaniciya kendi trendini
gostermek, puan vermek degil.
"""

from __future__ import annotations

import re
import sqlite3
import time

from alleye import journal
from alleye.journal import Turn

# --------------------------------------------------------------- konular ---
# Kural tabanli siniflandirma. Model cagrisi YOK: hem ucuz hem cevrimdisi
# calisir, hem de kullanicinin hatalari zaten imzada ("komut::mesaj") duruyor.
# Sira ONEMLI: ilk eslesen kazanir.
# KURAL: hata MESAJI komut ADINI yener. `ssh: permission denied` bir AG sorunu
# degil bir IZIN sorunudur; komuta bakip "ssh -> ag" demek yanlis konuya
# yonlendirir. Bu yuzden mesaja dayali kesin kurallar (izin, bagimlilik,
# sozdizimi) once; komut adina dayali genel kurallar (ag, git, docker) sonra.
_TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("izin/kimlik", re.compile(
        r"permission denied|access denied|access is denied|unauthorized|"
        r"forbidden|\b403\b|\b401\b|erisim reddedildi|not permitted|"
        r"operation not permitted|authentication failed|bad credentials|"
        r"publickey|password authentication")),
    ("bagimlilik/paket", re.compile(
        r"modulenotfounderror|no module named|importerror|cannot find module|"
        r"\bpip\b|\bnpm\b|yarn|pnpm|cargo|nuget|apt-get|package not found|"
        r"unresolved import|could not find a version")),
    ("sozdizimi/tip", re.compile(
        r"syntaxerror|indentationerror|typeerror|nameerror|attributeerror|"
        r"unexpected token|parse error|expected .* but|is not defined|"
        r"unterminated|invalid syntax")),
    ("ag/port", re.compile(
        r"connection refused|connection reset|timed out|timeout|unreachable|"
        r"\bport\b|\bcurl\b|\bwget\b|\bnmap\b|\bssh\b|\bdns\b|resolve|"
        r"address already in use|econnrefused|no route to host")),
    ("git", re.compile(
        r"\bgit\b|\bmerge\b|rebase|upstream|detached head|non-fast-forward|"
        r"\bcommit\b|pull request")),
    ("docker/konteyner", re.compile(
        r"docker|podman|kubectl|kubernetes|compose|container|image not found")),
    ("derleme/yapi", re.compile(
        r"\bmake\b|cmake|\bgcc\b|clang|msbuild|compil|linker|undefined reference|"
        r"build failed|cannot compile")),
    ("test", re.compile(
        r"pytest|unittest|jest|assertionerror|test failed|failing test|"
        r"\d+ failed")),
    ("dosya/yol", re.compile(
        r"no such file|cannot find path|filenotfounderror|not found|"
        r"bulunamadi|is a directory|not a directory|path")),
]

UNKNOWN_TOPIC = "diger"


def topic_of(signature: str) -> str:
    """Duvar imzasindan konu cikar. SAF fonksiyon.

    Imza `komut::hata mesaji` bicimindedir (journal.fingerprint). Konu
    TURETILMIS veridir - `walls` tablosuna kolon olarak YAZILMAZ; sema
    degistirmek geri alinamaz, imzadan her zaman yeniden hesaplanabilir.
    """
    if not signature:
        return UNKNOWN_TOPIC
    low = signature.lower()
    for name, pattern in _TOPIC_RULES:
        if pattern.search(low):
            return name
    return UNKNOWN_TOPIC


# ---------------------------------------------------------- error quotient ---


def _norm_cmd(cmd: str) -> str:
    return " ".join((cmd or "").lower().split())


def pair_score(a: Turn, b: Turn) -> int:
    """Jadud EQ cift puani, kabuk komutlarina uyarlanmis. En fazla 9."""
    if not (a.failed and b.failed):
        return 0                      # ikisi de hata vermediyse ceza yok
    score = 2
    if journal.fingerprint(a) == journal.fingerprint(b):
        score += 3                    # ayni hata imzasi
    if _norm_cmd(a.cmd) == _norm_cmd(b.cmd):
        score += 3                    # ayni komutu tekrar denemis
    if a.cwd and a.cwd == b.cwd:
        score += 1                    # ayni yerde debelenmis
    return score


PAIR_MAX = 9


def error_quotient(turns: list[Turn]) -> float:
    """Oturumun EQ'su: [0,1]. Yuksek = ayni duvarda debelenme.

    Ceza vermeyen ciftler de paydaya girer (Jadud boyle; aksi halde tek bir
    kotu cift tum oturumu 1.0 gosterirdi).
    """
    if len(turns) < 2:
        return 0.0
    pairs = list(zip(turns, turns[1:]))
    total = sum(pair_score(a, b) / PAIR_MAX for a, b in pairs)
    return total / len(pairs)


# ------------------------------------------------------------------ ozet ---

MIN_WALLS_FOR_REPORT = 5   # bu kadar veri yoksa rapor yaniltici olur


def _window(turns: list[Turn], start: float, end: float) -> list[Turn]:
    return [t for t in turns if start <= t.ts < end]


def summarize(con: sqlite3.Connection | None, turns: list[Turn],
              days: int = 7, now: float | None = None) -> dict:
    """Haftalik ayna verisi. Model cagrisi YOK.

    Don: {
      "enough": bool, "days": int,
      "eq": float, "eq_prev": float, "eq_delta": float,
      "topics": [{"topic","hits","resolved","eq"}...],   # cok carpilandan aza
      "walls": int, "resolved": int, "open_repeat": [(imza, hits)...],
      "commands": int, "failed": int,
    }
    """
    now = now or time.time()
    cut = now - days * 86400
    prev_cut = cut - days * 86400

    cur = _window(turns, cut, now + 1)
    prev = _window(turns, prev_cut, cut)

    eq = error_quotient(cur)
    eq_prev = error_quotient(prev)

    # Konu basina: hangi konuda kac basarisiz komut + o konunun EQ'su.
    by_topic: dict[str, list[Turn]] = {}
    for t in cur:
        if t.failed:
            by_topic.setdefault(topic_of(journal.fingerprint(t)), []).append(t)

    walls = resolved = 0
    open_repeat: list[tuple[str, int]] = []
    wall_topics: dict[str, dict[str, int]] = {}
    if con is not None:
        rows = con.execute(
            "SELECT signature, hits, resolved FROM walls ORDER BY hits DESC").fetchall()
        walls = len(rows)
        for r in rows:
            topic = topic_of(r["signature"])
            slot = wall_topics.setdefault(topic, {"hits": 0, "resolved": 0})
            slot["hits"] += int(r["hits"])
            if r["resolved"]:
                resolved += 1
                slot["resolved"] += 1
            elif int(r["hits"]) >= 2:
                open_repeat.append((r["signature"], int(r["hits"])))

    topics = []
    names = set(by_topic) | set(wall_topics)
    for name in names:
        t_turns = by_topic.get(name, [])
        w = wall_topics.get(name, {"hits": 0, "resolved": 0})
        topics.append({
            "topic": name,
            "hits": w["hits"] or len(t_turns),
            "resolved": w["resolved"],
            "eq": error_quotient(t_turns) if len(t_turns) >= 2 else 0.0,
            "failed_commands": len(t_turns),
        })
    topics.sort(key=lambda d: (-d["hits"], -d["failed_commands"]))

    return {
        "enough": walls >= MIN_WALLS_FOR_REPORT or len(cur) >= 30,
        "days": days,
        "eq": eq,
        "eq_prev": eq_prev,
        "eq_delta": eq - eq_prev,
        "topics": topics,
        "walls": walls,
        "resolved": resolved,
        "open_repeat": open_repeat[:5],
        "commands": len(cur),
        "failed": sum(1 for t in cur if t.failed),
    }


# ----------------------------------------------------- kademe kullanimi ---
# ITS literaturunde "gaming the system": ogrenciler ipucu sistemini ogrenmek
# yerine cevabi almak icin kullanir; en son ("bottom-out") ipucuna atlamak
# klasik ornegidir. Baker ve ark. bu davranisi gosterenlerin benzer
# ogrencilerin YALNIZCA 2/3'u kadar ogrendigini olcmus.
# Bizde karsiligi: hep dogrudan kademe 3'e (tam cozum) gitmek.
#
# DURUST SINIR: bu bulgu ITS ortamindaki OGRENCILER icin. Calisan bir
# gelistiricinin bazen dogrudan cozume ihtiyaci olmasi mesru. O yuzden bunu
# bir HUKUM degil AYNA olarak sunuyoruz; arac kimseyi engellemez.

MIN_ASKS_FOR_STAGE = 10
BOTTOM_OUT_WARN = 0.6


def stage_stats(con: sqlite3.Connection | None) -> dict:
    """Hangi kademede kac cevap aldin? 'Dip cevaba atlama' orani nedir?"""
    counts = {1: 0, 2: 0, 3: 0}
    if con is not None:
        for row in con.execute("SELECT level, COUNT(*) AS c FROM asks GROUP BY level"):
            lv = int(row["level"])
            if lv in counts:
                counts[lv] = int(row["c"])
    total = sum(counts.values())
    return {
        "total": total,
        "levels": counts,
        "bottom_out": (counts[3] / total) if total else 0.0,
        "stayed_at_1": (counts[1] - counts[2]) if counts[1] > counts[2] else 0,
        "enough": total >= MIN_ASKS_FOR_STAGE,
    }


def stage_sentences(st: dict) -> list[str]:
    """Kademe aynasi cumleleri. Yargilamaz, olculeni soyler."""
    if not st["enough"]:
        return []
    lv = st["levels"]
    out = [f"Kademe dagilimi: {lv[1]} durtme · {lv[2]} yon · {lv[3]} tam cozum."]
    if st["bottom_out"] >= BOTTOM_OUT_WARN:
        out.append(
            f"Cevaplarin %{st['bottom_out'] * 100:.0f}'i dogrudan tam cozum. "
            "ITS arastirmasi ipucu sistemini bu sekilde kullananlarin "
            "benzerlerinin 2/3'u kadar ogrendigini olcmus (Baker ve ark.). "
            "Acele isin varsa sorun degil - ama ogrenmek istedigin konuda "
            "kademe 1'de biraz durmayi dene.")
    elif st["bottom_out"] <= 0.25 and lv[1] >= 5:
        out.append("Cogunlukla durtme kademesinde kaliyorsun - arac tam da "
                   "boyle kullanilmak icin yazildi.")
    return out


# --------------------------------------------------------- alistirma (4.3) ---
# ITS literaturunde "gaming" tespit edilince standart mudahale: ogrenciye ek
# materyal / ikinci sans vermek. Bizim karsiligimiz: acik kalmis tekrar eden
# duvar icin KISA bir kendine-soru. Model cagrisi YOK - konuya gore sablon,
# cevrimdisi calisir, kota harcamaz.
#
# Kademe kuralina sadik: soru CEVABI VERMEZ, seni dusundurur. Cevabini
# `alleye teach` ile yazarsan duvar kapanir.
_PRACTICE: dict[str, str] = {
    "git": "Bu hatada uzaktaki dal ile senin dalin nerede ayrildi? "
           "`git log --oneline --graph` ile ayrilma noktasini bulabilir misin?",
    "ag/port": "O portta GERCEKTEN ne dinliyor? Once dinleyen var mi, sonra "
               "guvenlik duvari mi engelliyor - hangisini once dogrularsin?",
    "izin/kimlik": "Hangi kimlikle baglaniyorsun ve o kimligin bu kaynakta ne "
                   "yetkisi var? Yetkiyi nereden dogrularsin?",
    "bagimlilik/paket": "Paket hangi ortama kurulu, kod hangi ortamda calisiyor? "
                        "Ikisinin ayni oldugunu nasil kanitlarsin?",
    "sozdizimi/tip": "Hata mesajindaki satir gercekten sorunun oldugu satir mi, "
                     "yoksa bir onceki satirdan mi geliyor?",
    "docker/konteyner": "Bu hata konteynerin ICINDE mi disinda mi olusuyor? "
                        "Ikisini nasil ayirt edersin?",
    "derleme/yapi": "Eksik olan sey basligi mi, kutuphane mi, yoksa baglama "
                    "sirasi mi? Hangisini once elersin?",
    "test": "Test mi yanlis, kod mu? Testi elle dogrulayacak en kucuk ornek ne?",
    "dosya/yol": "Programin calistigi dizin ile yolu yazdigin dizin ayni mi? "
                 "Bunu nasil dogrularsin?",
    UNKNOWN_TOPIC: "Bu hatayi bir kez daha uretebilir misin? Uretemiyorsan "
                   "cozdugun sey neydi - onu yazmak bir dahaki sefere kazandirir.",
}


def practice_hint(signature: str) -> str:
    """Acik kalmis duvar icin model gerektirmeyen kendine-soru."""
    return _PRACTICE.get(topic_of(signature), _PRACTICE[UNKNOWN_TOPIC])


def sentences(stats: dict) -> list[str]:
    """Sayilari CUMLEYE cevir. Rapor sayi dokmez, sana bir sey soyler.

    Veri azsa uydurmaz - "yeterli veri yok" der.
    """
    if not stats["enough"]:
        return ["Henuz yeterli veri yok - birkac gun daha kullan, sonra tekrar bak."]

    out: list[str] = []
    d = stats["days"]
    out.append(f"Son {d} gunde {stats['commands']} komut, {stats['failed']} tanesi hata verdi.")

    top = [t for t in stats["topics"] if t["hits"] > 0][:3]
    if top:
        adlar = ", ".join(f"{t['topic']} ({t['hits']}x)" for t in top)
        out.append(f"En cok carptigin konular: {adlar}.")

    # EQ trendi - asil "ayna" cumlesi.
    eq, prev, delta = stats["eq"], stats["eq_prev"], stats["eq_delta"]
    if prev > 0 and abs(delta) >= 0.05:
        yon = "dusmus" if delta < 0 else "yukselmis"
        yorum = ("hatalarini daha hizli cozuyorsun" if delta < 0
                 else "ayni duvarda daha cok debeleniyorsun")
        out.append(f"Debelenme skorun (EQ) {prev:.2f} -> {eq:.2f} {yon}: {yorum}.")
    elif eq > 0:
        out.append(f"Debelenme skorun (EQ) {eq:.2f}.")

    # En kotu konu, varsa
    zor = [t for t in stats["topics"] if t["eq"] >= 0.3 and t["failed_commands"] >= 4]
    if zor:
        z = max(zor, key=lambda t: t["eq"])
        out.append(f"En cok debelendigin konu '{z['topic']}' (EQ {z['eq']:.2f}) - "
                   f"burada ayni seyi tekrar deniyorsun.")

    if stats["walls"]:
        oran = 100 * stats["resolved"] / stats["walls"]
        out.append(f"{stats['walls']} duvarin {stats['resolved']} tanesini kapatmissin "
                   f"(%{oran:.0f}); `alleye teach` ile not birakmak bunu artirir.")

    if stats["open_repeat"]:
        out.append(f"Hala acik ve tekrar eden {len(stats['open_repeat'])} duvar var - "
                   f"bunlari cozmek en cok zaman kazandirir.")
    return out
