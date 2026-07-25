# All Eye — Mimari Hafıza (Index)

> **Bu dosya token tasarrufu içindir.** Yeni bir oturumda kod tabanını baştan
> taramadan önce burayı oku. Sadece burada cevabı olmayan şey için dosya aç.
> Son güncelleme: 2026-07-25 (Faz 0-1-2-3 bitti, 286 test yeşil).

## Tek cümle
Terminalde takıldığın anı fark edip, cevabı yapıştırmak yerine **3 kademede**
(dürtme → yön → tam çözüm) yol gösteren, tamamen yerel, sıfır bağımlılıklı
Windows aracı.

## Demir kurallar (ihlal etme — hepsi bilinçli karar)
1. **Sıfır Python bağımlılığı.** Sadece stdlib + ctypes + tkinter. pip paketi
   yok. Sürekli açık süreç 60-80 MB'da kalmalı.
2. **Bağlam terminalden gelir**, ekran görüntüsünden değil. Görüntü son çare,
   elle (`alleye look`), varsayılan kapalı.
3. **Kademeyi kullanıcı açar.** Hazır cevap öğrenmeyi bozar.
4. **Daemon kendiliğinden pencere açmaz.** Sadece haber verir.
5. **Redaksiyon:** gerçek sırlar maskelenir; IP/port/servis sürümü/NTLM hash
   **asla** maskelenmez (pentest mentoru tam da onlara bakar).

## Veri akışı (ana hat)
```
PowerShell/bash hook  →  journal.jsonl  →  detect.analyze()  →  context.build()
                                                                     ↓
   store (SQLite duvarlar)  ←  mentor promptu  ←  redact.redact()  ←  render()
                                     ↓
                          brain.Router → Gemini/Groq/Ollama
                                     ↓
                    ui (konsol)  |  window.py (cevap penceresi)
```

## Modül haritası (ne nerede)
| Dosya | Sorumluluk | Kritik detay |
|---|---|---|
| `hooks/alleye.ps1` | komut+çıktı+exit kaydı | `Start-Transcript` dilimleme; **bayat `$LASTEXITCODE`** koruması |
| `journal.py` | günlük okuma, `fingerprint()` | imza yol/sayı gürültüsünden arındırılır → duvar sayacı çalışsın |
| `detect.py` | zorlanma sinyalleri | tekrar · hata-serisi · aynı-hata · durgunluk · asılı · **yavaslama** · **dongu** |
| `context.py` | `Bundle` + `build()` + `render()` | git, son dosyalar, `window`, `user_note`, bütçe kırpma |
| `redact.py` | sır maskeleme | kural listesi; nmap `-p` bayrağı **maskelenmez** |
| `mentor.py` | kademe promptları | kademe 1/2/3 kuralları, `header()` |
| `store.py` | SQLite duvar hafızası | `walls`, `asks`; `teach_wall`/`get_note`/`last_wall` |
| `brain/router.py` | sağlayıcı zinciri | `stream(system, user, image_png=None)`; vision filtresi |
| `brain/providers.py` | Gemini/Groq/OpenRouter/Ollama | Gemini `supports_vision`, `inlineData` |
| `cli.py` | komutlar | ask status doctor install key forget watch autostart teach walls look calibrate |
| `daemon.py` | kısayol + pasif döngü + tepsi | `_invoke()`, `_answer_window()`, `_passive_loop()` |
| `tray.py` | sistem tepsisi (ctypes) | `pump()` bloklamaz; `notify_balloon()` |
| `window.py` | cevap penceresi (tkinter) | çerçevesiz, topmost, Esc/Enter |
| `vision.py` | pencere yakalama + PNG + onay | **içerik doğrulamalı** yakalama; ağ yok |
| `autostart.py` | Startup `.lnk` | PowerShell WScript.Shell (pywin32 yok) |
| `calibrate.py` | eşik kalibrasyonu | `--apply` sadece değişen anahtarı yazar |
| `clipboard.py` | pano izleyici | hata kopyalanınca sinyal; buluta gitmez |
| `review.py` | öğrenen hafıza (Faz 4) | konu kümeleme · **EQ** (Jadud uyarlaması) · dip-cevap aynası · alıştırma |
| `ui.py` | konsol HUD | `_fix_encoding()` — boru/dosyada çökmeyi önler |

## Tuzaklar (her biri bir kez sessizce bozdu — tekrar açma)
1. **`$LASTEXITCODE` cmdlet'lerde güncellenmez** → bayat değer sızar. Hook
   "değişti mi + gerçekten harici program mı" diye çözüyor.
2. **`.env` utf-8-sig ile okunmalı** (BOM). Üç savunma var; üçü birden
   kalkarsa "kaydettim ama tanımlı değil" sessiz hatası döner.
3. **`install` config.json YAZMAZ** — yazarsa varsayılanlar donar, sonraki
   düzeltmeler (ölü model adları) kullanıcıya ulaşmaz.
4. **Gemini auth `x-goog-api-key` başlığıyla** — `AQ.` anahtarlar `?key=` ile
   çalışmaz.
5. **Model adları hızla ölüyor.** Kademe 1-2 `lite`, kademe 3 `models_deep`.
6. **`-NoProfile` terminaller** hook'u yüklemez → `ALLEYE_HOOK_LOADED` ile tespit.
7. **Profile yol yazarken `json.dumps` KULLANMA** — ters bölüyü ikiye katlar.
   `install._ps_quote()` kullan.
8. **SQLite bağlantısı thread'e bağlı** — cevap penceresi ayrı worker thread'de
   akıtıyor; kayıt orada **taze bağlantı** açmalı.
9. **`PrintWindow`/`BitBlt` `1` dönerken siyah kare verebilir** — ölçüldü.
   Dönüş değerine güvenme, gerçek piksele bak (`vision._dib_blank`).
10. **Boru/dosyaya yazarken yerel kod sayfası** `◉`/`─` yüzünden komutu
    çökertir → `ui._fix_encoding()`.
11. **`redact` env-secret kuralı `^`'a bağlı** — düzyazı not içindeki
    `DB_PASSWORD=xyz` kaçıyordu. `inline-secret` kuralı bunu kapatıyor;
    `memory export` notları buradan geçer.
12. **Konu kuralında sıra:** hata MESAJI komut ADINI yener
    (`ssh: permission denied` → ağ değil **izin**).

## Test ağı
```bash
.venv\Scripts\python.exe -m unittest discover tests      # 286 test, ~3 sn
```
```bash
.venv\Scripts\python.exe tools\mutation_check.py         # testler gerçekten koruyor mu
```
`mutation_check` her tuzağı koda geri getirip testin kırmızıya düştüğünü
doğrular. **Yeşil paket tek başına bir şey kanıtlamaz** — boş paket de yeşildir.

## Ortam
- venv: `.venv\Scripts\alleye.exe` (editable install)
- veri: `%LOCALAPPDATA%\AllEye\` (journal.jsonl, alleye.db, .env, config.json, hooks/)
- Gemini anahtarı kurulu ve çalışıyor. Groq yok, Ollama kurulu değil.
- Kısayol: `ctrl+alt+e`. Repo: github.com/Diandyistaken/all-eye (public).

## Nerede ne var (arama kısayolu)
- Yeni CLI komutu → `cli.py`: `cmd_*` + `build_parser()` + `main()` `known` seti
  (**üçü birden** yoksa çıplak-ask fallback'ına düşer)
- Yeni config anahtarı → `config.py` `DEFAULTS`
- Yeni sinyal → `detect.py` `analyze()`
- Yeni sağlayıcı → `brain/providers.py` + `REGISTRY`
