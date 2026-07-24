"""Komut satiri arayuzu."""

from __future__ import annotations

import argparse
import os
import sys
import time

from alleye import __version__, config, context, detect, journal, mentor, store, ui
from alleye.brain import Router, available
from alleye.brain.providers import ProviderError


def _hook_live() -> bool:
    """Hook bu kabukta yuklendi mi (ortam degiskeni cocuk surece miras kalir)."""
    return os.environ.get("ALLEYE_HOOK_LOADED") == "1"


def _hook_hint() -> None:
    from alleye import install as _install

    ui.error("bu terminalde hook aktif degil - komutlarin kaydedilmiyor")
    ui.note("  simdi acmak icin bu satiri calistir:")
    ui.note(f"    {_install.dot_source_line()}")


# --------------------------------------------------------------------- ask ---

def cmd_ask(args: argparse.Namespace) -> int:
    cfg = config.load()
    ui.init()
    con = store.connect()
    question = " ".join(args.question or "").strip()

    b = context.build(con=con)
    if not b.turns:
        ui.banner("gunluk bos")
        if _hook_live():
            ui.warn("Hook aktif ama henuz komut kaydi yok - birkac komut calistir.")
        else:
            _hook_hint()
        return 1

    level = max(1, min(3, args.level))
    rendered = context.render(b, question)

    # Bu duvari daha once kendisi cozup not birakmissa (alleye teach), mentorun
    # cevabindan ONCE kendi notunu goster - kendi ogrendigin en iyi cevaptir.
    if b.user_note:
        ui.banner("senin notun")
        ui.note(b.user_note)
        ui.note("(bunu sen ogrettin; mentorun yorumu asagida)")
        ui.rule()

    while True:
        ui.banner(mentor.header(b, level))
        if b.signals and level == 1:
            for s in b.signals[:3]:
                ui.note(str(s))
            ui.rule()

        prog = ui.Progress()
        router = Router(cfg, only=args.provider, notify=prog.set, deep=level >= 3)
        sys_p = mentor.system_prompt(level, cfg["language"])
        usr_p = mentor.user_prompt(rendered, level, question)

        prog.set("baglam gonderiliyor")
        prog.start()
        try:
            text = ui.stream_out(router.stream(sys_p, usr_p), on_first=prog.stop)
        except ProviderError as exc:
            prog.stop()
            ui.error(str(exc))
            ui.note("`alleye doctor --live` ile anahtarlari kontrol et.")
            return 2
        finally:
            prog.stop()

        used = router.used
        ui.rule()
        ui.note(f"{used.provider}/{used.model}")
        store.record_ask(con, cwd=b.cwd, level=level, trigger=args.trigger,
                         signature=b.signature, question=question or "(oto)",
                         answer=text, provider=used.provider, model=used.model)

        if args.once:
            return 0

        reply = ui.prompt_more(level)
        if reply.lower() in ("q", "quit", "exit", "yeter"):
            return 0
        if reply:
            question = reply
            b = context.build(con=None)
            rendered = context.render(b, question)
        elif level < 3:
            level += 1
        else:
            return 0


# ------------------------------------------------------------------ status ---

def cmd_status(args: argparse.Namespace) -> int:
    ui.init()
    cfg = config.load()
    turns = journal.read(limit=cfg["context"]["turns"])
    signals = detect.analyze(turns, cfg)
    ui.banner("durum")

    if not _hook_live():
        _hook_hint()
        ui.rule()
    if not turns:
        ui.warn("gunluk bos - henuz hicbir komut kaydedilmemis")
    else:
        last = turns[-1]
        ui.note(f"{len(turns)} komut kaydi · son: {time.strftime('%H:%M:%S', time.localtime(last.ts))}")
        ui.note(f"son komut: {last.cmd[:70]}  (exit={last.exit})")
        with_out = sum(1 for t in turns if t.out)
        ui.note(f"cikti yakalanan: {with_out}/{len(turns)}")

    ui.rule()
    if signals:
        for s in signals:
            (ui.warn if s.weight >= 2 else ui.note)(str(s))
        ui.note(f"skor {detect.score(signals)} · {'TAKILDIN' if detect.is_stuck(signals) else 'akis normal'}")
    else:
        ui.ok("zorlanma sinyali yok")

    con = store.connect()
    st = store.stats(con)
    ui.rule()
    ui.note(f"hafiza: {st['asks']} soru · {st['walls']} duvar · {st['resolved']} cozulmus")
    walls = store.top_walls(con, 5)
    for w in walls:
        if w["hits"] >= 2:
            mark = "✓" if w["resolved"] else "•"
            ui.note(f"  {mark} {w['hits']}x  {w['signature'][:64]}")
    ui.note(f"veri: {config.HOME}")
    return 0


# --------------------------------------------------------------------- key ---

def _parse_env(path) -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip().lstrip("﻿")
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip().lstrip("﻿")
        if k.lower().startswith(("export ", "set ")):
            k = k.split(None, 1)[1]
        vals[k] = v.strip().strip("'\"")
    return vals


def _write_env(path, vals: dict[str, str]) -> None:
    """Sablonu geri yaz, degerleri koru. BOM'suz UTF-8 - BOM parser'i bozuyor."""
    import re

    text = config.ENV_TEMPLATE
    leftover = {}
    for k, v in vals.items():
        pattern = rf"^{re.escape(k)}=.*$"
        if re.search(pattern, text, flags=re.M):
            text = re.sub(pattern, f"{k}={v}", text, count=1, flags=re.M)
        elif v:
            leftover[k] = v
    if leftover:
        text += "\n\n# --- diger ---\n" + "\n".join(f"{k}={v}" for k, v in leftover.items())
    path.write_text(text + "\n", encoding="utf-8")


def _fix_env(path) -> list[str]:
    """Yanlis satira yapistirilmis anahtarlari yerine tasi. Deger asla basilmaz."""
    vals = _parse_env(path)
    gem = vals.get("GEMINI_API_KEY", "")
    groq = vals.get("GROQ_API_KEY", "")
    notes: list[str] = []

    gem_in_groq = config._is_gemini_key(groq)
    groq_in_gem = gem.startswith("gsk_")

    if gem_in_groq and groq_in_gem:
        vals["GEMINI_API_KEY"], vals["GROQ_API_KEY"] = groq, gem
        notes.append("iki anahtar yer degistirmisti, duzeltildi")
    elif gem_in_groq and not gem:
        vals["GEMINI_API_KEY"], vals["GROQ_API_KEY"] = groq, ""
        notes.append("Gemini anahtari GROQ satirindan GEMINI satirina tasindi")
    elif groq_in_gem and not groq:
        vals["GROQ_API_KEY"], vals["GEMINI_API_KEY"] = gem, ""
        notes.append("Groq anahtari GEMINI satirindan GROQ satirina tasindi")

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        notes.append("BOM temizlendi (anahtarin okunmamasinin sebebi buydu)")
    if not notes and b"\r\n" not in raw:
        notes.append("duzeltilecek bir sey bulunamadi, dosya yeniden yazildi")

    backup = path.parent / (path.name + ".bak")
    backup.write_bytes(raw)
    _write_env(path, vals)
    notes.append(f"yedek: {backup.name}")
    return notes


def cmd_key(args: argparse.Namespace) -> int:
    """Anahtar dosyasini olustur/onar. Anahtarin kendisini SEN yapistiriyorsun."""
    import subprocess

    ui.init()
    path = config.ensure_env_file()

    if args.fix:
        ui.banner("anahtar dosyasi onariliyor")
        ui.note(f"dosya: {path}")
        ui.rule()
        for note in _fix_env(path):
            ui.ok(note)
        ui.rule()
        for k, v in _parse_env(path).items():
            ui.note(f"  {k:16} {config.mask_secret(v)}")
        ui.rule()
        ui.note("dogrula:  alleye doctor --live")
        return 0
    ui.banner("api anahtari")
    ui.note(f"dosya: {path}")
    ui.rule()
    ui.note("1) https://aistudio.google.com/apikey  ac, 'Create API key' de")
    ui.note("2) Anahtari kopyala - yeni anahtarlar 'AQ.Ab' ile baslar")
    ui.note("3) Dosyanin EN SON satiri GEMINI_API_KEY= — sonuna yapistir, kaydet")
    ui.note("4) alleye doctor --live  ile dogrula")
    ui.rule()

    if args.show:
        # Degerler maskeli basilir: bu ciktinin bir yere yapistirilmasi cok kolay.
        for line in path.read_text(encoding="utf-8").splitlines():
            bare = line.strip()
            if bare and not bare.startswith("#") and "=" in bare:
                k, _, v = bare.partition("=")
                print(f"{k.strip()}={config.mask_secret(v.strip())}")
            else:
                print(line)
        return 0
    try:
        subprocess.Popen(["notepad.exe", str(path)])
        ui.ok("dosya notepad'de acildi")
    except OSError:
        ui.warn("notepad acilamadi, dosyayi elle ac")
    return 0


# ------------------------------------------------------------------ forget ---

def cmd_forget(args: argparse.Namespace) -> int:
    """Duvar sayaclarini/gunlugu temizle. Test kirliligi ve cozulmus duvarlar icin."""
    ui.init()
    ui.banner("temizlik")
    con = store.connect()

    if args.walls or args.all:
        n = store.stats(con)["walls"]
        con.execute("DELETE FROM walls")
        con.execute("DELETE FROM asks")
        con.commit()
        ui.ok(f"{n} duvar kaydi ve soru gecmisi silindi")

    if args.journal or args.all:
        if config.JOURNAL.exists():
            backup = config.JOURNAL.with_suffix(".jsonl.bak")
            backup.write_bytes(config.JOURNAL.read_bytes())
            config.JOURNAL.write_text("", encoding="utf-8")
            ui.ok(f"komut gunlugu sifirlandi (yedek: {backup.name})")
        else:
            ui.note("gunluk zaten bos")

    if not (args.walls or args.journal or args.all):
        ui.note("ne silinecek? --walls (duvar sayaclari) · --journal (komut gunlugu) · --all")
        return 1
    return 0


# ------------------------------------------------------------------ doctor ---

def cmd_doctor(args: argparse.Namespace) -> int:
    ui.init()
    cfg = config.load()
    ui.banner(f"doctor · v{__version__}")

    from alleye import install as _install

    ui.note(f"ev: {config.HOME}")

    # Hook bu kabukta aktif mi? Hook yuklenirken ALLEYE_HOOK_LOADED ortam
    # degiskenini set ediyor; ortam degiskenleri cocuk sureclere miras kaldigi
    # icin buradan gorulebiliyor. Profil blogu yerinde olsa bile kabuk
    # -NoProfile ile aciliyorsa hook calismaz - en sinsi hata bu.
    hook_live = os.environ.get("ALLEYE_HOOK_LOADED") == "1"
    profile = _install.powershell_profile()
    has_block = profile.exists() and _install.BEGIN in profile.read_text(
        encoding="utf-8-sig", errors="replace")

    (ui.ok if has_block else ui.error)(
        f"profilde hook kaydi: {'var' if has_block else 'YOK - alleye install'}")
    ui.note(f"  {profile}")
    if hook_live:
        ui.ok("bu terminalde hook AKTIF")
    else:
        ui.error("bu terminalde hook AKTIF DEGIL - komutlar kaydedilmiyor")
        if has_block:
            ui.note("  bu terminal profili yuklemiyor (muhtemelen -NoProfile ile acildi)")
            ui.note("  hemen acmak icin bu satiri calistir:")
            ui.note(f"    {_install.dot_source_line()}")
            ui.note("  kalici cozum: profil yukleyen bir terminal kullan")
            ui.note("  (Windows Terminal / baslat menusunden PowerShell)")

    (ui.ok if config.JOURNAL.exists() else ui.warn)(
        f"journal.jsonl {'var' if config.JOURNAL.exists() else 'henuz bos'}")
    if config.JOURNAL.exists():
        size = config.JOURNAL.stat().st_size
        ui.note(f"  boyut {size / 1024:.0f} KB")
    ui.note(f"config: {config.CONFIG_FILE if config.CONFIG_FILE.exists() else '(varsayilan)'}")
    ui.note(f"anahtar dosyasi: {config.ENV_FILE}")

    from alleye import autostart as _autostart
    ui.note(f"autostart: {'acik' if _autostart.is_enabled() else 'kapali'}")

    ui.rule()
    ui.note("dosyadan okunan anahtarlar:")
    for env in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        val = os.environ.get(env, "").strip()
        src = config.ENV_SOURCE.get(env, "")
        ui.note(f"  {env:16} {config.mask_secret(val)}"
                + (f"  ← {src}" if src else ""))
        problem = config.key_looks_wrong(env, val)
        if problem:
            ui.warn(f"{env}: {problem}")

    ui.rule()
    any_ready = False
    for name, ready, why in available(cfg):
        if ready:
            any_ready = True
            models = ", ".join(cfg.get(name, {}).get("models", [])[:2])
            ui.ok(f"{name:12} hazir  ({models})")
        else:
            ui.error(f"{name:12} {why}")
    if not any_ready:
        ui.rule()
        ui.warn("Hicbir beyin hazir degil. Tek komutla coz:")
        ui.note("  alleye key")
        return 1

    if args.live:
        ui.rule()
        ui.note("canli test - anahtarlar gercekten calisiyor mu")
        for name, ready, _ in available(cfg):
            if not ready:
                continue
            try:
                ans = Router(cfg, only=name).ask("Cok kisa cevap ver.", "Sadece 'ok' yaz.")
                ui.ok(f"{name:12} GECTI ({ans.model}) → {ans.text.strip()[:40]}")
            except ProviderError as exc:
                ui.error(f"{name:12} BASARISIZ")
                for line in str(exc).splitlines():
                    ui.note(f"    {line.strip()}")

    ui.rule()
    ui.note(f"redaksiyon: {'acik' if cfg['redact'] else 'KAPALI'} · dil: {cfg['language']}")
    if not args.live:
        ui.note("gercekten calisiyor mu:  alleye doctor --live")
    return 0


# ----------------------------------------------------------------- install ---

def cmd_install(args: argparse.Namespace) -> int:
    from alleye.install import install_bash, install_powershell

    ui.init()
    ui.banner("hook kurulumu")
    # config.json BILEREK yazilmiyor. Varsayilanlari diske dondurmak, sonraki
    # surumlerdeki duzeltmelerin (calismayan model adlari gibi) kullaniciya hic
    # ulasmamasina yol aciyor. Dosya sadece kullanici ayar degistirmek isterse
    # olusturulur - o zaman da yalnizca degistirdigi anahtarlar yazilmali.

    if args.shell in ("powershell", "both"):
        path, changed = install_powershell(force=args.force)
        (ui.ok if changed else ui.note)(
            f"powershell profili: {path} {'guncellendi' if changed else '(zaten kurulu)'}")
    if args.shell in ("bash", "both"):
        path, changed = install_bash(force=args.force)
        (ui.ok if changed else ui.note)(
            f"bashrc: {path} {'guncellendi' if changed else '(zaten kurulu)'}")

    ui.rule()
    ui.note("Yeni bir terminal ac, birkac komut calistir, sonra:  alleye status")
    return 0


# ------------------------------------------------------------------- watch ---

def cmd_watch(args: argparse.Namespace) -> int:
    from alleye.daemon import run

    return run(hotkey_only=args.hotkey_only, interval=args.interval,
               hotkey=args.hotkey, probe=args.probe, tray=args.tray)


# --------------------------------------------------------------- autostart ---

def cmd_autostart(args: argparse.Namespace) -> int:
    """Oturum acilisinda arka planda (tepsi) baslat - Startup klasoru kisayolu."""
    from alleye import autostart

    ui.init()
    ui.banner("otomatik baslatma")

    if args.enable:
        try:
            path = autostart.enable()
        except (OSError, RuntimeError) as exc:
            ui.error(str(exc))
            return 2
        ui.ok(f"acildi: {path}")
        ui.note(f"komut: {' '.join(autostart.launch_target())}")
        ui.note("bir sonraki oturumda arka planda (tepsi) baslar")
        return 0

    if args.disable:
        if autostart.disable():
            ui.ok("kapatildi - kisayol silindi")
        else:
            ui.note("zaten kapaliydi")
        return 0

    ui.note(autostart.status())
    if not autostart.is_enabled():
        ui.note("acmak icin:  alleye autostart --enable")
    return 0


# ------------------------------------------------------------------- teach ---

def cmd_teach(args: argparse.Namespace) -> int:
    """Az once takildigin duvari cozulmus isaretle ve kendi cozum notunu birak."""
    ui.init()
    con = store.connect()
    note = " ".join(args.note or "").strip()
    if not note:
        ui.warn('ne ogrendigini yaz:  alleye teach "cozumu buraya"')
        return 1
    last = store.last_wall(con)
    if last is None:
        ui.warn("ogretilecek bir duvar yok - once bir hataya takil")
        return 1
    sig = last["signature"]
    store.teach_wall(con, sig, note)
    ui.banner("ogrenildi")
    ui.note(f"duvar: {sig[:64]}")
    ui.ok(f"notun: {note}")
    ui.note("ayni hataya tekrar takilirsan bu notu once sana gosterecegim.")
    return 0


# ------------------------------------------------------------------- walls ---

def cmd_walls(args: argparse.Namespace) -> int:
    """Carptigin duvarlari listele: kac kez, cozuldu mu (v/nokta), imza, varsa not."""
    ui.init()
    con = store.connect()
    ui.banner("duvarlar")
    walls = store.top_walls(con, args.limit)
    if not walls:
        ui.note("henuz hicbir duvara carpmadin")
        return 0
    for w in walls:
        mark = "✓" if w["resolved"] else "•"
        ui.note(f"  {mark} {w['hits']}x  {w['signature'][:64]}")
        note = store.get_note(con, w["signature"])
        if note:
            ui.note(f"      not: {note}")
    ui.rule()
    ui.note(f"toplam {len(walls)} duvar · ✓ cozulmus · • acik")
    return 0


# -------------------------------------------------------------------- main ---

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alleye",
        description="Takildigin ani fark eden, cevabi vermeden once elinden tutan mentor.",
    )
    p.add_argument("--version", action="version", version=f"all eye {__version__}")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("ask", help="son terminal baglamini analiz et ve yardim al")
    a.add_argument("question", nargs="*", help="istege bagli soru")
    a.add_argument("-l", "--level", type=int, default=1, help="1 durtme, 2 yon, 3 tam cozum")
    a.add_argument("--once", action="store_true", help="tek cevap ver, kademe sorma")
    a.add_argument("--provider", help="belirli bir saglayiciyi zorla (gemini/groq/ollama)")
    a.add_argument("--trigger", default="manual", help=argparse.SUPPRESS)
    a.set_defaults(func=cmd_ask)

    s = sub.add_parser("status", help="sinyalleri ve hafizayi goster")
    s.set_defaults(func=cmd_status)

    k = sub.add_parser("key", help="anahtar dosyasini olustur / onar / ac")
    k.add_argument("--show", action="store_true", help="icerigi maskeli bas")
    k.add_argument("--fix", action="store_true",
                   help="yanlis satirdaki anahtari tasi, BOM temizle")
    k.set_defaults(func=cmd_key)

    f = sub.add_parser("forget", help="duvar sayaclarini / gunlugu temizle")
    f.add_argument("--walls", action="store_true", help="duvar sayaclari ve soru gecmisi")
    f.add_argument("--journal", action="store_true", help="komut gunlugu")
    f.add_argument("--all", action="store_true", help="hepsi")
    f.set_defaults(func=cmd_forget)

    d = sub.add_parser("doctor", help="kurulum ve anahtar kontrolu")
    d.add_argument("--live", action="store_true",
                   help="gercek bir istek atarak anahtarlari dogrula")
    d.set_defaults(func=cmd_doctor)

    i = sub.add_parser("install", help="shell hook'larini kur")
    i.add_argument("--shell", choices=["powershell", "bash", "both"], default="powershell")
    i.add_argument("--force", action="store_true")
    i.set_defaults(func=cmd_install)

    w = sub.add_parser("watch", help="arka planda izle (kisayol + pasif tespit)")
    w.add_argument("--hotkey-only", action="store_true", help="pasif tespiti kapat")
    w.add_argument("--interval", type=float, default=20.0, help="tarama araligi (sn)")
    w.add_argument("--hotkey", help="kisayolu zorla (orn: ctrl+alt+e)")
    w.add_argument("--probe", action="store_true", help="hangi kisayollar bos, listele")
    w.add_argument("--tray", action="store_true", help="konsolu gizle, sistem tepsisine tasi")
    w.set_defaults(func=cmd_watch)

    au = sub.add_parser("autostart", help="oturum acilisinda arka planda baslat")
    au.add_argument("--enable", action="store_true", help="startup kisayolunu olustur")
    au.add_argument("--disable", action="store_true", help="startup kisayolunu sil")
    au.add_argument("--status", action="store_true", help="durumu goster (varsayilan)")
    au.set_defaults(func=cmd_autostart)

    t = sub.add_parser("teach", help="az once takildigin duvara kendi cozum notunu birak")
    t.add_argument("note", nargs="*", help="cozum notun")
    t.set_defaults(func=cmd_teach)

    wl = sub.add_parser("walls", help="carptigin duvarlari ve cozumleri listele")
    wl.add_argument("--limit", type=int, default=15, help="kac duvar gosterilsin")
    wl.set_defaults(func=cmd_walls)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    known = {"ask", "status", "doctor", "install", "watch", "key", "forget",
             "autostart", "teach", "walls",
             "-h", "--help", "--version"}
    # Ciplak `alleye` veya `alleye neden calismiyor` -> ask varsayilani
    if not argv or argv[0] not in known:
        argv = ["ask", *argv]
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
