# All Eye — Yol Haritası

> Tek kural: **her faz kendi başına kullanılabilir bir şey bırakır.** Yarım
> özellik biriktirmiyoruz. Bir faz bitmeden sonrakine geçmiyoruz.

Son güncelleme: 2026-07-24

---

## Şu an neredeyiz

**Faz 0 tamamlandı ve canlı doğrulandı.** Çalışan, ölçülmüş bir sistem var.

| Bileşen | Durum | Kanıt |
|---|---|---|
| PowerShell hook (komut + çıktı + exit) | ✅ | `git status` → `exit=128` doğru yakalandı |
| bash hook (çıktı hariç) | ✅ | `.bashrc` kurulu |
| Zorlanma tespiti | ✅ | tekrar · hata serisi · aynı hata · durgunluk · asılı kalma |
| Redaksiyon | ✅ | sırlar maskeleniyor, nmap/NTLM dokunulmuyor |
| Beyin zinciri | ✅ | Gemini `AQ.` auth key, kademe 1 **1.5 sn** |
| Kademeli mentor (1→2→3) | ✅ | kademe 3 ağır modele geçiyor |
| Duvar hafızası (SQLite) | ✅ | "bu duvara N. kez çarpıyorsun" |
| Global kısayol | ✅ | `ctrl+alt+e`, dolu olursa otomatik yedek |
| Pasif tespit | ✅ | tepsi modunda ikon renk değiştirir (Faz 1.1) |
| Test ağı | ✅ | 226 test, ~3.6 sn · her tuzak mutasyonla doğrulandı |
| Tepsi ikonu | ✅ | `watch --tray` konsolu gizler, sağ tık menüsü (Faz 1.1) |
| Otomatik başlatma | ✅ | `autostart --enable` Startup kısayolu (Faz 1.2) |
| Cevap penceresi | ✅ | tkinter, çerçevesiz, imleç yanı, Esc/Enter (Faz 1.3) |
| teach / walls | ✅ | duvarı kapat, kendi notunu önce göster (Faz 1.4) |

**Faz 1 tamamlandı (2026-07-24)** — 4 alt görev paralel ajanlarla yazıldı,
senior lead denetiminden geçti (bir KRİTİK SQLite thread hatası yakalanıp
düzeltildi), 226 test yeşil.

**Bilinen sınırlar:** bash'te komut çıktısı yakalanmıyor · terminal dışı hiçbir
bağlam yok (Faz 3) · pasif tespit sinyalleri hâlâ kaba (Faz 2.1).

---

## Test ağı

```bash
.venv\Scripts\python.exe -m unittest discover tests
```

```bash
.venv\Scripts\python.exe tools\mutation_check.py
```

Birincisi paketi çalıştırır (156 test, ~1.4 sn, sıfır bağımlılık — stdlib
`unittest`). İkincisi asıl soruyu sorar: **bu testler gerçekten bir şey
koruyor mu?** Bilinen her tuzağı kaynak koda geri getirir ve testin kırmızıya
düştüğünü doğrular. Yeşil bir test paketi tek başına hiçbir şey kanıtlamaz —
boş bir paket de yeşildir.

| Dosya | Test | Ne kilitliyor |
|---|---|---|
| `test_redact.py` | 25 | sırlar maskeleniyor · nmap portları / NTLM hash'leri **dokunulmadan** geçiyor |
| `test_config.py` | 27 | `.env` BOM'u · `export`/`set` öneki · tırnaklı değer · ölü model adları |
| `test_detect.py` | 24 | tekrar · hata serisi · aynı hata · durgunluk · eşikler config'ten okunuyor |
| `test_install.py` | 21 | `_ps_quote` ters bölü ikilemiyor · idempotanlık · `install` config.json yazmıyor |
| `test_provider.py` | 16 | `x-goog-api-key` **başlığı** · anahtar URL'de değil · 503→sonraki model |
| `test_journal.py` | 15 | imza kararlı (yol/sayı değişince aynı) · PowerShell gürültü satırları atlanıyor |
| `test_context.py` | 15 | ana klasörde tarama yok · süre ve klasör sınırı çalışıyor |
| `test_hook_powershell.py` | 13 | **gerçek powershell.exe ile:** bayat `$LASTEXITCODE` sızmıyor, çıktı dilimleniyor |

`test_hook_powershell.py` gerçek bir `powershell.exe` başlatır. `prompt`
yalnızca interaktif kabukta çalıştığı için `Get-History` sahtelenip
`AllEye-Record` doğrudan çağrılır. Windows dışında kendini atlar.

**Ölçülen not:** `.env` BOM'una karşı kodda üç ayrı savunma var (`utf-8-sig`
okuma + iki `lstrip`). Tek birini kaldırmak davranışı değiştirmiyor — mutasyon
aracı bunları "eşdeğer mutant" diye işaretler; test ancak üçü birden kalkınca
kırmızıya düşer.

---

## Faz 1 — Günlük kullanıma geçiş ✅ (2026-07-24)

**Amaç:** Aracı "kurdum" olmaktan çıkarıp "her gün açık" hale getirmek.

**Nasıl yapıldı:** 4 alt görev dört paralel ajana bölündü, ortak bir sözleşmeyle
(imzalar, dosya sahiplikleri, DB şeması) koordine edildi; çakışan dosyalar
(cli.py, daemon.py, config.py) tek elden birleştirildi; senior lead ajanı
uyum denetimi yaptı.

### 1.1 Tepsi ikonu — konsol penceresini öldür ✅
- [x] `alleye/tray.py` — ctypes ile `Shell_NotifyIcon`, sıfır bağımlılık
- [x] Durum renkleri: sakin (gri) / sinyal (turuncu) / hazır (yeşil, ileride)
- [x] Sağ tık menüsü: Sor · Durum · Duraklat · Çık
- [x] `daemon.run(tray=True)` konsolu gizler (`ShowWindow(hwnd, 0)`)

**Bitti kriteri:** `alleye watch --tray` konsolu gizler; pasif sinyal gelince
ikon turuncuya döner. Canlı doğrulandı (test_tray smoke gerçek ikon üretti).

### 1.2 Otomatik başlatma ✅
- [x] `alleye autostart --enable/--disable/--status`
- [x] Startup klasörüne `.lnk` (PowerShell WScript.Shell, pip yok, yönetici yok)
- [x] `alleye doctor` otomatik başlatma durumunu gösteriyor

**Bitti kriteri:** Startup kısayolu `pythonw -m alleye watch --tray` çalıştırır;
gerçek `.lnk` roundtrip testi geçti.

### 1.3 Cevap penceresi ✅
- [x] Çerçevesiz, her zaman üstte, imlecin yanında açılan pencere
- [x] **tkinter (stdlib)** — pywebview DEĞİL; sıfır bağımlılık kuralı korundu
- [x] Esc = kapat, Enter = kademe derinleştir
- [x] Odağı çalmaz; kapanınca eski pencereye döner

**Bitti kriteri:** `window.available()` ise kısayol cevabı imleç yanında üstte
gösterir; Esc ile kapanır. tkinter yoksa konsol yoluna nazikçe düşer.

### 1.4 `alleye teach` — duvarı kapat ✅
- [x] `alleye teach "çözüm notu"` → son duvarı `resolved=1` yap + not ekle
- [x] Aynı imza tekrar ederse mentor önce **senin notunu** gösterir
- [x] `alleye walls` — en çok çarptığın duvarlar listesi (+ notlar)

**Bitti kriteri:** `context.build` aynı imza için `user_note` yüklüyorsa
`cmd_ask` modelden önce senin notunu basar. Canlı doğrulandı.

---

## Faz 2 — Tetikleyiciyi genişlet

**Amaç:** Kısayola basmayı unuttuğun anları yakalamak.

**Tahmini:** 2 oturum

### 2.1 Pasif tespit v2
Şu anki sinyaller kaba. Gerçek "zorlanma" daha ince.

- [ ] Aynı dosyayı tekrar tekrar kaydetme (kaydet-çalıştır-hata döngüsü)
- [ ] Komutlar arası süre uzuyor (düşünme/arama süresi artıyor)
- [ ] Aynı hata mesajının panoya kopyalanması (= aramaya gidiyorsun)
- [ ] Sinyal ağırlıklarını kendi verinle kalibre et: `alleye calibrate`

**Bitti kriteri:** Bir hafta kullan, `alleye calibrate` yanlış alarm oranını
raporlasın; eşikler otomatik ayarlansın.

### 2.2 Ses tetikleyici
- [ ] openWakeWord (tamamen yerel, birkaç MB, CPU'da çalışır)
- [ ] "all eye" uyandırma kelimesi
- [ ] Mikrofon **sadece** uyandırma kelimesi arar; kayıt yok, buluta gitmez
- [ ] `alleye watch --voice`, varsayılan **kapalı**

**Bitti kriteri:** Klavyeye dokunmadan "all eye" de, cevap gelsin.
Yanlış tetiklenme günde 1'den az.

---

## Faz 3 — Terminal dışı bağlam

**Amaç:** Burp, Wireshark, tarayıcı, IDE — terminal olmayan yerlerde de görmek.

**Tahmini:** 2 oturum

### 3.1 Aktif pencere farkındalığı
- [ ] Pencere başlığı + process adı (zaten `context.active_window()` var)
- [ ] Uygulama profilleri: hangi uygulamada hangi bağlam toplanır
- [ ] Terminal/IDE ise ekran görüntüsü **alma** — mevcut yol daha iyi

### 3.2 Son çare ekran görüntüsü
- [ ] Sadece aktif pencere (tam ekran değil), PNG, ctypes `PrintWindow`
- [ ] Gemini vision'a gönder (ücretsiz katmanda görsel dahil)
- [ ] Gönderilmeden önce **önizleme göster** — ne yolladığını gör
- [ ] Görüntüde OCR ile sır taraması, redaksiyon katmanına bağla

**Bitti kriteri:** Burp Suite'te takıl, `ctrl+alt+e`, mentor ekrandaki isteği
okuyup yorum yapsın. Gönderim öncesi ne yollandığını görmüş olasın.

**Risk:** Bu faz gizlilik yüzeyini en çok büyüten faz. Varsayılan **kapalı**
olmalı, her gönderimde açık onay istemeli.

---

## Faz 4 — Öğrenen hafıza

**Amaç:** "Bu duvara 4. kez çarpıyorsun"u, "sen bu konuda hep şurada
takılıyorsun"a çevirmek.

**Tahmini:** 1-2 oturum

- [ ] Duvarları konuya göre kümele (git · ağ · izin · bağımlılık · sözdizimi)
- [ ] Haftalık özet: `alleye review` — en çok zaman kaybettiğin 3 konu
- [ ] Tekrar eden duvarlar için kısa alıştırma önerisi
- [ ] Hafızayı dışa aktar/içe aktar (makine değiştirince kaybolmasın)

**Bitti kriteri:** Bir ay sonra `alleye review` sana kendin hakkında
bilmediğin bir şey söylesin.

---

## Faz 5 — Siber güvenlik modu

**Amaç:** HackTheBox / CTF için özelleşmiş mentor. Projenin başlangıç sebebi.

**Tahmini:** 2-3 oturum

- [ ] `alleye box start <isim>` — hedef IP, kapsam, notlar için oturum
- [ ] nmap / gobuster / ffuf çıktısını **yapılandırılmış** ayrıştır
      (ham metin yerine: açık portlar, servisler, sürümler, bulunan yollar)
- [ ] "Neyi denemedin" analizi — bulunan yüzeylerden dokunulmayanlar
- [ ] Kademe kuralı sıkılaştır: flag ve tam exploit zinciri **asla** kademe
      1-2'de açılmaz; kademe 3'te bile önce kavramı anlatır
- [ ] `alleye box report` — çözdüğün kutunun kendi writeup'ı, senin notlarınla

**Bitti kriteri:** Bir HTB kutusunu All Eye ile çöz, hiçbir writeup açma,
sonunda `alleye box report` kendi öğrenme kaydını çıkarsın.

---

## Hedef dosya iskeleti

```
tests/                   ✅  226 test · stdlib unittest
tools/mutation_check.py  ✅  testler gercekten koruyor mu

alleye/
├── __init__.py          ✅
├── __main__.py          ✅
├── cli.py               ✅  ask status doctor install key forget watch autostart teach walls
├── config.py            ✅  ayarlar, .env, anahtar doğrulama
├── journal.py           ✅  günlük okuma, hata imzası
├── detect.py            ✅  zorlanma sinyalleri            → Faz 2.1 derinleşir
├── context.py           ✅  bağlam paketi                  → Faz 3.1 genişler
├── redact.py            ✅  sır maskeleme                  → Faz 3.2 OCR ekler
├── mentor.py            ✅  kademe promptları              → Faz 5 sıkılaşır
├── store.py             ✅  duvar hafızası                 → Faz 4 kümeleme
├── install.py           ✅  hook kurulumu
├── ui.py                ✅  konsol HUD, ilerleme
├── daemon.py            ✅  kısayol + pasif döngü
├── brain/
│   ├── http.py          ✅  stdlib SSE/NDJSON
│   ├── providers.py     ✅  gemini · groq · openrouter · ollama
│   └── router.py        ✅  yedekleme zinciri, hızlı/derin model seçimi
├── hooks/
│   ├── alleye.ps1       ✅  transcript dilimleme
│   └── alleye.bash      ✅  komut + exit
│
├── tray.py              ✅ Faz 1.1  sistem tepsisi (ctypes Shell_NotifyIcon)
├── window.py            ✅ Faz 1.3  cevap penceresi (tkinter, stdlib)
├── autostart.py         ✅ Faz 1.2  başlangıçta çalıştır (Startup .lnk)
├── voice.py             ⬜ Faz 2.2  openWakeWord
├── vision.py            ⬜ Faz 3.2  pencere görüntüsü + vision
└── box.py               ⬜ Faz 5    HTB oturum yönetimi
```

---

## Teknik borç

Faz atlamadan önce temizlenecekler:

- [x] **Test yok.** ✅ 2026-07-24 — `tests/` altında 156 test (stdlib
      `unittest`, sıfır bağımlılık) + `tools/mutation_check.py`. Bilinen 7
      tuzağın **her biri** için kırmızıya düşen test var, mutasyonla
      kanıtlandı. Ayrıntı: yukarıdaki "Test ağı" bölümü.
- [ ] **bash çıktı yakalama** — `script` kullanmadan çözülebilir mi araştır
- [ ] **`ask` içinde ikinci `context.build`** — takip sorusunda bağlam
      yeniden kuruluyor, gereksiz iş
- [ ] **Kota takibi yok** — günlük Gemini kullanımını say, sınıra yaklaşınca uyar
- [ ] **`watch` tek örnek kontrolü yok** — iki kez başlatılırsa kısayol çakışır
- [x] Git deposu ✅ 2026-07-24 — public: github.com/Diandyistaken/all-eye

---

## Karar günlüğü

Neden böyle yapıldığını unutmamak için. Bunlar tartışılıp karara bağlandı:

| Karar | Gerekçe |
|---|---|
| Bağlam ekran görüntüsünden değil terminalden | Piksel pahalı ve eksik; transcript kesin. Piyasadaki overlay'ler bu yüzden aptal. |
| Cevap 3 kademede, kademeyi kullanıcı açar | Hazır cevap öğrenmeyi bozar; HTB'de writeup okumakla aynı şey. |
| Daemon asla kendiliğinden pencere açmaz | Araya giren asistan ilk gün kapatılır. Sadece haber verir. |
| Sıfır Python bağımlılığı | Sürekli açık duran süreç 60-80 MB'da kalmalı. |
| `install` config.json yazmaz | Varsayılanları donduruyordu; çalışmayan model adları düzeltilse bile kullanıcıya ulaşmıyordu. |
| Kademe 1-2 lite model, kademe 3 ağır model | Büyük flash modelleri ücretsiz katmanda sık 503 veriyor; öne koyunca her çağrı 30-130 sn sürüyordu. |
| Model zincirinde `-latest` takma adları | Google modelleri hızla emekliye ayırıyor; takma ad yeniden adlandırmayı sessizce atlatır. |
| Kimlik doğrulama `x-goog-api-key` başlığı | `AQ.` auth key'ler eski `?key=` parametresiyle çalışmıyor. |
| IP, port, servis sürümü, NTLM hash maskelenmez | Pentest mentoru tam da onlara bakmalı. Maskelenen şey gerçek sırlar. |
| Testler stdlib `unittest`, pytest yok | Sıfır bağımlılık kuralı test paketi için de geçerli; `discover` zaten yeterli. |
| Testin kendisi mutasyonla doğrulanıyor | Yeşil paket hiçbir şey kanıtlamaz. Bir testin değeri, ilgili kod bozulduğunda kırmızıya düşmesidir — `tools/mutation_check.py` bunu ölçüyor. |
| Hook testi gerçek `powershell.exe` başlatır | Bayat `$LASTEXITCODE` tuzağı saf Python'da taklit edilemez; PowerShell'in kendi semantiği olmadan test bir şey kanıtlamaz. |
| Cevap penceresi tkinter, pywebview değil | pywebview pip bağımlılığıdır; "sıfır bağımlılık" demir kuralını bozar. tkinter Python'la gelir. ROADMAP metni burada kendi kuralıyla çelişiyordu; kural kazandı. |
| Faz 1 paralel ajanlar + senior lead | Bağımsız 4 alt görev aynı anda ayrı ajanlarda; paylaşılan sözleşme imzaları hizaladı, çakışan dosyalar tek elden birleşti, senior lead uyumu denetledi (bir KRİTİK SQLite hatası böyle yakalandı). |
| Pencere yolunda thread-başına SQLite | `show_answer` cevabı ayrı worker thread'de akıtıyor; sqlite bağlantısı oluşturulduğu thread'e bağlı, paylaşılırsa `ProgrammingError`. Bağlam ana thread'de, kayıt worker thread'de kendi bağlantısıyla. |

---

## Çalışma düzeni

1. Bir faz seç, alt maddelerini sırayla bitir
2. Her alt madde bitince **bitti kriterini** gerçekten test et
3. Faz bitince bu dosyada işaretle, karar günlüğüne yeni kararları ekle
4. Sonraki faza geçmeden teknik borç listesine bak

Sıradaki iş: **Faz 2.1 — pasif tespit v2** (Faz 1 tamamlandı).
