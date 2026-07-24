"""Zorlanma tespiti.

Buradaki tek is: "su an takildin mi?" sorusuna LLM'e hic sormadan,
bedavaya, gunlukteki desenlere bakarak cevap vermek. Model cagrisi
ancak buradan sinyal cikarsa anlamli.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from alleye import config, journal
from alleye.journal import Turn


@dataclass
class Signal:
    kind: str
    weight: int       # 1 hafif .. 3 guclu
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.detail}"


def _norm(cmd: str) -> str:
    return " ".join(cmd.lower().split())


def analyze(turns: list[Turn], cfg: dict | None = None) -> list[Signal]:
    cfg = (cfg or config.load())["detect"]
    signals: list[Signal] = []
    if not turns:
        return signals

    recent = turns[-15:]

    # 1) Ayni komutu tekrar tekrar calistirmak
    counts: dict[str, int] = {}
    for t in recent:
        counts[_norm(t.cmd)] = counts.get(_norm(t.cmd), 0) + 1
    for cmd, n in counts.items():
        if n >= cfg["repeat_threshold"]:
            signals.append(Signal("tekrar", 2, f"ayni komut son 15 turda {n} kez: {cmd[:80]}"))

    # 2) Ust uste basarisiz cikis kodlari
    streak = 0
    for t in reversed(recent):
        if t.failed:
            streak += 1
        else:
            break
    if streak >= cfg["fail_streak"]:
        signals.append(Signal("hata-serisi", 3, f"son {streak} komut ust uste hata verdi"))
    elif streak > 0:
        signals.append(Signal("hata", 1, f"son komut hata verdi (exit={recent[-1].exit})"))

    # 3) Ayni hata imzasi tekrar ediyor
    sigs: dict[str, int] = {}
    for t in recent:
        if t.failed:
            fp = journal.fingerprint(t)
            sigs[fp] = sigs.get(fp, 0) + 1
    for fp, n in sigs.items():
        if n >= 2:
            signals.append(Signal("ayni-hata", 3, f"ayni hata {n} kez tekrarlandi: {fp[:100]}"))

    # 4) Durgunluk: uzun suredir hicbir sey degismiyor
    span_min = (recent[-1].ts - recent[0].ts) / 60 if len(recent) > 1 else 0
    if span_min >= cfg["stagnation_minutes"] and not any(not t.failed for t in recent[-6:]):
        signals.append(Signal("durgunluk", 2,
                              f"{span_min:.0f} dakikadir basarili giden bir adim yok"))

    # 5) Uzun sessizlik sonrasi geri donus (mola / kaybolma)
    if recent[-1].age_s > 900 and recent[-1].failed:
        signals.append(Signal("asili-kalmis", 1,
                              f"{recent[-1].age_s / 60:.0f} dakika once bir hatada birakilmis"))

    # 6) Yavaslama: komut araliklari belirgin uzuyorsa (dusunme/arama suresi artiyor).
    # Son pencereyi ikiye bol (eski yari / yeni yari), ortalama araligi karsilastir.
    slowdown_factor = cfg.get("slowdown_factor", 2.5)
    if len(recent) >= 6:
        deltas = [recent[i].ts - recent[i - 1].ts for i in range(1, len(recent))]
        half = len(deltas) // 2
        old_deltas, new_deltas = deltas[:half], deltas[half:]
        if old_deltas and new_deltas:
            avg_old = sum(old_deltas) / len(old_deltas)
            avg_new = sum(new_deltas) / len(new_deltas)
            # cok kucuk araliklar gurultu sayilir (orn. testte ardisik hizli cagrilar);
            # anlamli bir karsilastirma icin eski pencere en az yarim saniye olmali.
            if avg_old >= 0.5 and avg_new >= avg_old * slowdown_factor:
                signals.append(Signal("yavaslama",
                    1, f"komut araligi buyudu: onceki ort {avg_old:.0f}sn -> "
                       f"son ort {avg_new:.0f}sn (~{avg_new / avg_old:.1f}x)"))

    # 7) Kaydet-calistir-hata dongusu: AYNI komut kisa araliklarla tekrarlanip
    # HER SEFERINDE AYNI hata imzasini veriyorsa - klasik takilma dongusu.
    # "ayni-hata" sinyalinden farki: burada komut da ayni olmali ve araliklar kisa olmali.
    loop_window_s = cfg.get("loop_window_s", 90)
    by_cmd: dict[str, list[Turn]] = {}
    for t in recent:
        if t.failed:
            by_cmd.setdefault(_norm(t.cmd), []).append(t)
    for cmd, occ in by_cmd.items():
        if len(occ) < 2:
            continue
        occ = sorted(occ, key=lambda t: t.ts)
        fps = {journal.fingerprint(t) for t in occ}
        if len(fps) != 1:
            continue  # farkli hatalar - klasik "kaydet-calistir-hata" dongusu degil
        gaps = [occ[i].ts - occ[i - 1].ts for i in range(1, len(occ))]
        if gaps and all(0 <= g <= loop_window_s for g in gaps):
            signals.append(Signal("dongu", 2,
                f"'{cmd[:60]}' {len(occ)} kez ayni hatayla kisa araliklarla tekrarlandi"))

    signals.sort(key=lambda s: -s.weight)
    return signals


def score(signals: list[Signal]) -> int:
    return sum(s.weight for s in signals)


def is_stuck(signals: list[Signal], threshold: int = 3) -> bool:
    return score(signals) >= threshold


def summarize(signals: list[Signal]) -> str:
    if not signals:
        return "belirgin bir zorlanma sinyali yok"
    return "; ".join(str(s) for s in signals[:5])


def focus_turn(turns: list[Turn]) -> Turn | None:
    """Mentorun uzerine egilecegi tur: en son basarisiz olan, yoksa en sonuncu."""
    for t in reversed(turns):
        if t.failed:
            return t
    return turns[-1] if turns else None


def watch_tick(seen: set[str]) -> tuple[list[Signal], list[Turn]]:
    """Daemon icin: gunlugu oku, sinyalleri cikar, ayni olayi iki kez bildirme."""
    cfg = config.load()
    turns = journal.read(limit=cfg["context"]["turns"] + 8)
    signals = analyze(turns, cfg)
    if not signals:
        return [], turns
    key = f"{turns[-1].ts if turns else 0}:{','.join(s.kind for s in signals)}"
    if key in seen:
        return [], turns
    seen.add(key)
    if len(seen) > 200:
        seen.clear()
    return signals, turns


def now() -> float:
    return time.time()
