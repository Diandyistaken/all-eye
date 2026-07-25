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
| Pasif tespit v2 | ✅ | yavaslama + dongu + pano-arama sinyalleri (Faz 2.1) |
| Pano izleyici | ✅ | hatayı kopyalayınca sinyal, buluta gitmez (Faz 2.1) |
| calibrate | ✅ | yanlış alarm oranı + eşik ayarı (Faz 2.1) |
| Tepsi balonu | ✅ | sinyalde sessiz "takıldın gibi" bildirimi |
| Aktif pencere bağlamı | ✅ | `Bundle.window`, her `ask`'te (Faz 3.1) |
| Ekran görüntüsü + onay | ✅ | `alleye look`, varsayılan KAPALI, çift kapı (Faz 3.2) |
| Gemini vision | ✅ | `inlineData`, Router vision-farkında (Faz 3.2) |

**Faz 1 tamamlandı (2026-07-24)** — 4 alt görev paralel ajanlarla, senior lead
denetiminden geçti (bir KRİTİK SQLite thread hatası yakalandı), 226 test.

**Faz 2 tamamlandı (2026-07-25)** — pasif tespit v2 + pano izleyici + calibrate,
3 paralel ajan, 263 test yeşil. Ses tetikleyici sıfır-bağımlılık kuralı için
ertelendi (yerine pano izleyici).

**Faz 3 tamamlandı (2026-07-25)** — aktif pencere bağlamı + `alleye look`
(görüntü + onay + Gemini vision), peer-ajan modeli, 286 test yeşil. OCR sır
taraması ertelendi (bağımlılık); yerine zorunlu insan onayı.

**Bağımsız denetim (2026-07-25):** fact-checker ajanı Faz 1-2'nin 15 iddiasını
tek tek doğruladı — hepsi VERIFIED, kırık bir şey yok. Denetim sırasında
iddialar dışında **gerçek bir hata** bulundu ve düzeltildi: çıktı boruya/dosyaya
yönlendirilince `ui.banner` cp1254 yüzünden `UnicodeEncodeError` ile tüm komutu
çökertiyordu (`walls`, `calibrate`, `autostart`, `status` — Faz 0'dan beri
vardı). Özellikle kritikti çünkü autostart `pythonw` ile çalışıyor (konsol yok).

**Bilinen sınırlar:** bash'te komut çıktısı yakalanmıyor · sesli çağrı yok
(bağımlılık nedeniyle ertelendi) · görüntüde otomatik sır taraması yok
(insan onayına dayanıyor).

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

## Faz 2 — Tetikleyiciyi genişlet ✅ (2026-07-25)

**Amaç:** Kısayola basmayı unuttuğun anları yakalamak.

**Nasıl yapıldı:** 3 paralel ajan (sonnet), paylaşılan sözleşme, minimal test;
çakışan dosyalar (cli/daemon/config/tray) tek elden birleştirildi, denetim
koordinatörde. Ses tetikleyici ertelendi (aşağıya bak).

### 2.1 Pasif tespit v2 ✅
- [x] Kaydet-çalıştır-hata döngüsü → `dongu` sinyali (aynı komut+aynı hata, kısa aralık)
- [x] Komutlar arası süre uzuyor → `yavaslama` sinyali (düşünme/arama süresi)
- [x] Aynı hatanın panoya kopyalanması → `pano-arama` sinyali (`clipboard.py`, ctypes)
- [x] `alleye calibrate` — yanlış alarm oranını ölçer, eşik önerir/uygular
- [x] **Fikir eklendi:** tepsi balon bildirimi — sinyalde sessiz "takıldın gibi" balonu

**Bitti kriteri:** `alleye calibrate` yanlış alarm oranını raporluyor,
`--apply` ile sadece değişen eşikleri config.json'a yazıyor. Canlı doğrulandı.

### 2.2 Ses tetikleyici — ERTELENDİ ⏸️
`openWakeWord` bir pip bağımlılığıdır (onnxruntime + numpy, ~50MB, sürekli
mikrofon). Bu, **"sıfır bağımlılık, süreç 60-80MB"** demir kuralını bozar.
Karar (2026-07-25): sesi ertele; Faz 2'nin amacına ("unuttuğun anı yakala")
bağımlılıksız hizmet eden **pano izleyici** ile karşıla. Ses ileride ancak
opsiyonel bir extra olarak (çekirdeği kirletmeden) düşünülebilir.

- [ ] (ertelendi) openWakeWord "all eye" uyandırma kelimesi — çekirdek dışı extra

---

## Faz 3 — Terminal dışı bağlam ✅ (2026-07-25)

**Amaç:** Burp, Wireshark, tarayıcı, IDE — terminal olmayan yerlerde de görmek.

**Nasıl yapıldı:** Peer-ajan modeli — her iş için **iki ajan bağımsız çözüm**
üretti, sonra çözümler kıyaslanıp en sağlamı (birleştirilerek) uygulandı.

### 3.1 Aktif pencere farkındalığı ✅
- [x] Pencere başlığı + process adı → `Bundle.window`, her `ask` bağlamında
- [x] `vision.foreground_title()` process adını da çözüyor (`Baslik - exe (pid N)`)
- [x] Terminal/IDE'de ekran görüntüsü **alınmıyor** — mevcut terminal yolu daha iyi
      (görüntü yalnız `alleye look` ile, elle istendiğinde)

### 3.2 Son çare ekran görüntüsü ✅
- [x] Sadece aktif pencere (tam ekran değil), PNG, ctypes `PrintWindow` + yedekler
- [x] Gemini vision'a `inlineData` ile gönderim; Router vision-farkında
- [x] Gönderilmeden önce **önizleme + açık onay** (tkinter, Esc/İptal = gönderme)
- [ ] ~~Görüntüde OCR ile sır taraması~~ → **ERTELENDİ** (aşağıdaki karar)

**Bitti kriteri:** `alleye look` aktif pencereyi yakalar, önizletir, onay
verilmezse hiçbir bayt çıkmaz. Canlı doğrulandı: kapalıyken yakalama kodu hiç
çalışmıyor (çıkış kodu 1), `vision.py` içinde ağ kullanımı YOK.

**OCR ertelendi — gerekçe:** stdlib'de OCR yok; pytesseract/opencv sıfır
bağımlılık kuralını bozar. Yerine **daha güçlü** bir garanti kondu: görüntüyü
model görmeden **kullanıcı kendi gözüyle** görüp onaylıyor. Otomatik OCR
taramasına güvenmek (kaçırabilir) insan onayından zayıftır.

**Ölçülen tuzak — `PrintWindow` yalan söyleyebiliyor:** İki aday çelişti, ölçüm
yapıldı. Beş farklı pencerede (Chromium, UWP, Progman) `PrintWindow(0x2)`,
`PrintWindow(0)` ve `BitBlt` **üçü de `1` (başarı) döndü ama bitmap tamamen
siyahtı** (sıfır olmayan bayt oranı %0.00; aynı araçla DIB'e beyaz çizince %100
okundu, yani ölçüm doğru). Sonuç: dönüş değerine güvenen zincir modele siyah
kare gönderir. Bu yüzden her denemeden sonra **gerçek piksellere** bakılıyor
(`_dib_blank`), üçü de boşsa dürüstçe `None` dönülüyor.

---

## Faz 4 — Öğrenen hafıza

**Amaç:** "Bu duvara 4. kez çarpıyorsun"u, "sen bu konuda hep şurada
takılıyorsun"a çevirmek.

**Tahmini:** 1-2 oturum · **Yeni dosya:** `alleye/review.py`

**Neden şimdi:** Faz 0-3'te veri toplandı (journal + `walls` + `asks`). Şimdiye
kadar hafıza *sayıyordu*; Faz 4 onu *yorumluyor*. Model çağrısı gerektirmeyen
kısmı önce yap — ucuz, hızlı, çevrimdışı çalışır.

### 4.1 Konu kümeleme (model çağrısı YOK)
Duvar imzaları zaten `komut::hata` biçiminde. Kural tabanlı sınıflandırma
yeterli; LLM'e sormak hem yavaş hem gereksiz.

- [ ] `review.topic_of(signature) -> str` — SAF fonksiyon, kural listesi:
      `git` · `ağ/port` · `izin` · `bağımlılık/modül` · `sözdizimi` · `dosya-yolu`
      · `docker` · `derleme` · `diğer`
- [ ] `store`'a `topic` kolonu **ekleme** — imzadan türetilebilir, şema
      değiştirmek geri alınamaz; türetilmiş veriyi diske yazmıyoruz

### 4.2 `alleye review` — haftalık ayna
- [ ] `review.summarize(con, days=7) -> dict`: en çok çarpılan 3 konu, toplam
      duvar, çözülmüş oranı, en uzun süren tıkanma, `teach` ile kapatılanlar
- [ ] `alleye review [--days 30] [--topic git]` — konsol raporu
- [ ] Rapor **sayı değil cümle** üretsin: "bu hafta 4 saatinin 3'ü ağ/port
      konusunda geçti; 3 duvarın 2'sini kendin çözdün, 1'i hâlâ açık"

### 4.3 Alıştırma önerisi (model çağrısı VAR, opsiyonel)
- [ ] Tekrar eden ve **çözülmemiş** duvarlar için 3-5 satırlık mini alıştırma
- [ ] Kademe kuralına sadık: alıştırma çözümü vermez, yaptırır
- [ ] `--no-ai` bayrağıyla tamamen çevrimdışı çalışabilmeli

### 4.4 Hafıza taşınabilirliği
- [ ] `alleye memory export [dosya.json]` — `store.export_json()` zaten var
- [ ] `alleye memory import <dosya.json>` — imza çakışırsa `hits` topla,
      `note` doluysa koru (veri kaybı yok)
- [ ] Export'tan önce redaksiyon: notlar kullanıcının yazdığı serbest metin,
      sır içerebilir → `redact.redact()` geçir

**Bitti kriteri:** Bir ay kullandıktan sonra `alleye review` sana kendin
hakkında bilmediğin bir şey söylesin; `memory export` → başka makinede
`memory import` → duvar geçmişi ve notlar korunmuş olsun.

**Riskler / dikkat:**
- Az veriyle rapor yanıltıcı olur → 10'dan az duvar varsa "henüz yeterli veri
  yok" de, uydurma
- `asks.answer` uzun metinler tutuyor; rapor bunları modele geri göndermesin
  (bütçe patlar) — sadece imza/konu/sayı kullan
- Kümeleme kuralları İngilizce hata mesajlarına göre yazılmalı, Türkçe
  yerelleştirilmiş çıktılar da olabilir (`hata`, `bulunamadı`)

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
├── clipboard.py         ✅ Faz 2.1  pano izleyici (ctypes, hata-arama sinyali)
├── calibrate.py         ✅ Faz 2.1  yanlış alarm oranı + eşik ayarı
├── vision.py            ✅ Faz 3.2  pencere görüntüsü + PNG + önizleme/onay
├── voice.py             ⏸️ Faz 2.2  openWakeWord — ertelendi (pip bağımlılığı)
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
| Ses tetikleyici ertelendi (Faz 2.2) | openWakeWord = onnxruntime + numpy + sürekli mikrofon; "sıfır bağımlılık / 60-80MB" kuralını bozar. Amaca (unuttuğun anı yakala) bağımlılıksız pano izleyiciyle ulaşıldı. |
| Pano izleyici buluta hiçbir şey yollamaz | Pano metni yalnızca yerelde son hatayla karşılaştırılır; sadece `looks_like_error` olan metin işlenir (şifre değil). `config.clipboard_watch: false` ile kapatılır — gizlilik kontrolü kullanıcıda. |
| `calibrate --apply` sadece değişen anahtarı yazar | `install config.json yazmaz` kuralıyla aynı gerekçe: tüm DEFAULTS'u dondurmak sonraki sürüm düzeltmelerini kullanıcıya ulaştırmaz. Mevcut config oku-birleştir-yaz. |
| Görüntü yakalamada dönüş değerine güvenilmez | Ölçüldü: `PrintWindow`/`BitBlt` `1` dönerken bitmap tamamen siyah olabiliyor. Her denemeden sonra gerçek piksel örneklenir; hepsi boşsa `None` — siyah kare göndermek kotayı harcar ve kullanıcıyı yanıltır. |
| 24bpp DIB, `CreateCompatibleBitmap` değil | 32bpp'de alfa tanımsız kalıp GDI+ şeffaf PNG üretebiliyor (boş görüntü); 24bpp'de alfa yok. Ayrıca DIB'in ham piksel işaretçisi boşluk kontrolünü decode'suz mümkün kılıyor. |
| Görüntüde OCR yok, insan onayı var | stdlib'de OCR yok (bağımlılık). Otomatik tarama kaçırabilir; kullanıcının görüntüyü kendi gözüyle görüp onaylaması daha güçlü bir garanti. |
| Vision Router seviyesinde filtreleniyor | Görüntü varken vision desteklemeyen sağlayıcılar elenir ve hiçbiri yoksa net hata verilir. Sessizce metin-only göndermek kullanıcıyı yanıltırdı (görüntüye baktığını sanır). |
| `ui` çıktısı utf-8'e zorlanır, sembol ASCII'ye düşer | Boru/dosyaya yönlendirmede yerel kod sayfası (cp1254) `◉`/`─` yüzünden komutu çökertiyordu. Autostart `pythonw` ile çalıştığı için bu sessiz hata üretimde vurabilirdi. |

---

## Çalışma düzeni

1. Bir faz seç, alt maddelerini sırayla bitir
2. Her alt madde bitince **bitti kriterini** gerçekten test et
3. Faz bitince bu dosyada işaretle, karar günlüğüne yeni kararları ekle
4. Sonraki faza geçmeden teknik borç listesine bak

Sıradaki iş: **Faz 4 — öğrenen hafıza** (Faz 1, 2 ve 3 tamamlandı).
