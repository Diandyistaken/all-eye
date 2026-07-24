"""Esik kalibrasyonu: kullanicinin KENDI journal'ina bakip oneri uret.

detect.py'deki esikler (repeat_threshold, fail_streak, stagnation_minutes)
herkese ayni gelmez. Biri icin "3 hata ust uste" gercekten takilmak, bir
digeri icin normal deneme-yanilma temposu olabilir. Bu modul LLM'e hic
sormadan, gecmis journal'i kayan pencerede tekrar oynatarak "ne siklikta
sinyal verdik, kullanici genelde kendisi mi cozdu" sorusuna cevap arar ve
SADECE degisen esikleri onerir (config'e minimal yazim icin).

Model cagrisi yok, ag erisimi yok - sadece journal + detect.analyze.
"""

from __future__ import annotations

from alleye import config, detect
from alleye.journal import Turn

# detect.analyze de zaten "recent = turns[-15:]" ile calisiyor; burada ayni
# genislikte bir pencere kaydirarak journal'i "daemon o an ne gorurdu" gibi
# yeniden oynatiyoruz.
_WINDOW = 15

# Takilma sinyali basladiktan sonra bu sure icinde basarili (exit=0) bir
# komut gelirse "kullanici kendi cozmus" sayariz - potansiyel yanlis alarm.
_SELF_RESOLVE_S = 600  # 10 dakika

# suggest_thresholds esikleri
_HIGH_RATE = 0.5     # bu ve uzeri: sinyal cok - esikleri gevset
_LOW_RATE = 0.15      # bu ve alti (yeterli veriyle): esikleri sikilastir
_MIN_STUCK_FOR_LOWER = 3  # sikilastirma icin en az bu kadar takilma orneği

# Onerilen degerlerin tasmayacagi makul sinirlar.
_REPEAT_RANGE = (2, 6)
_FAIL_RANGE = (2, 6)
_STAG_RANGE = (5, 60)


def _clamp(v: int, lo_hi: tuple[int, int]) -> int:
    lo, hi = lo_hi
    return max(lo, min(hi, v))


def analyze_history(turns: list[Turn], cfg: dict | None = None) -> dict:
    """Journal'i kayan pencerede detect.analyze ile yeniden oynat.

    Her adimda pencere bir tur genisler (en fazla son _WINDOW tur) ve o anki
    sinyaller/"takildin mi" hesaplanir - daemon'un canli izlerken gorecegini
    simule eder. Ayni takilma OLAYININ ust uste pencerelerde tekrar tekrar
    sayilmamasi icin sadece GECIS anlari sayilir (sakin->sinyal, sinyal->takildin).

    Donen sozluk:
      windows        - degerlendirilen pencere sayisi (== len(turns))
      signals        - kac kez sinyal SIFIRDAN baslad (sakin->sinyal gecisi)
      stuck          - kac kez "takildin" esigine ulasildi (gecis sayisi)
      self_resolved  - bunlardan kaci, takilma basladiktan sonraki
                        _SELF_RESOLVE_S icinde gelen basarili bir komutla
                        kendiliginden cozuldu (= olasi yanlis alarm)
      rate           - self_resolved / stuck (veri yoksa 0.0)
    """
    cfg = cfg or config.load()
    result = {"windows": 0, "signals": 0, "stuck": 0, "self_resolved": 0, "rate": 0.0}
    if not turns:
        return result

    prev_signal = False
    prev_stuck = False
    stuck_positions: list[int] = []  # 1-tabanli: pencere o an turns[:i] idi

    for i in range(1, len(turns) + 1):
        window = turns[max(0, i - _WINDOW):i]
        sigs = detect.analyze(window, cfg)
        result["windows"] += 1

        has_signal = bool(sigs)
        stuck_now = detect.is_stuck(sigs)

        if has_signal and not prev_signal:
            result["signals"] += 1
        if stuck_now and not prev_stuck:
            result["stuck"] += 1
            stuck_positions.append(i)

        prev_signal = has_signal
        prev_stuck = stuck_now

    for pos in stuck_positions:
        anchor = turns[pos - 1]
        for t in turns[pos:]:
            if t.ts - anchor.ts > _SELF_RESOLVE_S:
                break
            if not t.failed:
                result["self_resolved"] += 1
                break

    if result["stuck"] > 0:
        result["rate"] = result["self_resolved"] / result["stuck"]
    return result


def suggest_thresholds(stats: dict, cfg: dict | None = None) -> dict:
    """Yanlis alarm oranina gore detect esiklerini oner.

    Sadece DEGISEN anahtarlari dondurur - cagiran taraf (cli.py --apply)
    bunlari mevcut config.json'un uzerine minimal sekilde yazabilsin diye.
    Yeterli veri yoksa (hic takilma olayi yoksa) bos sozluk doner.
    """
    cfg = cfg or config.load()
    cur = cfg.get("detect", {})
    cur_repeat = cur.get("repeat_threshold", config.DEFAULTS["detect"]["repeat_threshold"])
    cur_fail = cur.get("fail_streak", config.DEFAULTS["detect"]["fail_streak"])
    cur_stag = cur.get("stagnation_minutes", config.DEFAULTS["detect"]["stagnation_minutes"])

    suggestions: dict = {}
    stuck = stats.get("stuck", 0)
    rate = stats.get("rate", 0.0)

    if stuck <= 0:
        return suggestions  # oneri kuracak veri yok

    if rate >= _HIGH_RATE:
        # Cogu "takildin" uyarisini kullanici zaten kendi cozmus - arac fazla
        # erken/sik konusuyor demektir. Esikleri gevset (daha az sinyal).
        new_repeat = _clamp(cur_repeat + 1, _REPEAT_RANGE)
        new_fail = _clamp(cur_fail + 1, _FAIL_RANGE)
        new_stag = _clamp(int(cur_stag * 1.5), _STAG_RANGE)
        if new_repeat != cur_repeat:
            suggestions["repeat_threshold"] = new_repeat
        if new_fail != cur_fail:
            suggestions["fail_streak"] = new_fail
        if new_stag != cur_stag:
            suggestions["stagnation_minutes"] = new_stag
    elif rate <= _LOW_RATE and stuck >= _MIN_STUCK_FOR_LOWER:
        # Takilma sinyalleri nadiren yanlis alarm - kullanici gercekten
        # yardima ihtiyac duyuyor. Biraz erken uyarsin diye sikilastir.
        new_fail = _clamp(cur_fail - 1, _FAIL_RANGE)
        new_stag = _clamp(int(cur_stag * 0.75), _STAG_RANGE)
        if new_fail != cur_fail:
            suggestions["fail_streak"] = new_fail
        if new_stag != cur_stag:
            suggestions["stagnation_minutes"] = new_stag
    # _LOW_RATE < rate < _HIGH_RATE (veya stuck yetersiz): dokunma, mevcut iyi.

    return suggestions
