# All Eye

Takıldığın anı fark eden, cevabı hemen vermeden **elinden tutan** yerel mentor.

Ücretsiz. Sıfır Python bağımlılığı. Boşta ~60 MB RAM.

```
Ctrl+Alt+Space  ya da  terminalde:  ae
```

---

## Neden başka bir "AI overlay" değil

Piyasadaki ekran-gören asistanlar iki şeyi yanlış yapıyor:

1. **Bağlamı ekran görüntüsünden alıyorlar.** Piksel pahalı, yavaş ve eksik.
   All Eye bağlamı asıl kaynaktan alır: gerçek terminal geçmişin, çıkış kodların,
   komut çıktıların, git durumun. Aynı model, iyi bağlamla dâhi olur.
2. **Cevabı yapıştırıyorlar.** Bu HackTheBox'ta writeup okumakla aynı şey —
   öğrenmiyorsun. All Eye kademeli açılır ve kademeyi sen kontrol edersin.

| Kademe | Ne yapar |
|---|---|
| 1 · dürtme | Tıkanıklığı adlandırır, gözden kaçırdığın tek detayı gösterir. Çözümü **vermez**. |
| 2 · yön | Hangi yaklaşımı denemen gerektiğini ve önceki denemenin neden tutmadığını söyler. Komutu **vermez**. |
| 3 · tam çözüm | Komut, gerekçe, kök sebep. |

Enter'a basmazsan kademe 1'de durur.

---

## Kurulum

```bash
uv venv --python 3.12 .venv
```

```bash
uv pip install -e . --python .venv\Scripts\python.exe
```

Ücretsiz bir beyin bağla. Bu komut anahtar dosyasını oluşturur ve açar:

```bash
.venv\Scripts\alleye key
```

https://aistudio.google.com/apikey → "Create API key" → anahtarı açılan dosyada
`GEMINI_API_KEY=` satırının sonuna yapıştır. Kart istemez, günde ~1500 istek.

Yeni anahtarlar **`AQ.Ab`** ile başlar ("auth key", servis hesabına bağlı).
Eski `AIza` anahtarları hâlâ çalışıyor ama Google bunları Eylül 2026'da kapatıyor.
All Eye ikisini de destekler — kimlik doğrulama `x-goog-api-key` **başlığıyla**
yapılır, URL'deki eski `?key=` parametresiyle değil. `AQ.` anahtarları `?key=`
ile çalışmaz; birçok üçüncü parti araç bu yüzden 401 veriyor.

Anahtarın gerçekten çalıştığını doğrula:

```bash
.venv\Scripts\alleye doctor --live
```

Groq isteğe bağlı ama önerilir: Gemini kotası dolduğunda otomatik devreye girer
(günde ~14.400 istek). İkisi birden pratikte tükenmez.

Shell hook'unu kur ve **yeni bir terminal aç**:

```bash
.venv\Scripts\alleye install --shell both
```

Doğrula:

```bash
.venv\Scripts\alleye doctor
```

## Kullanım

```bash
alleye            # son bağlamı analiz et, kademe 1'den başla
```

```bash
alleye "neden 8080 cevap vermiyor"    # doğrudan soru sor
```

```bash
alleye -l 3 --once                    # sabrım yok, tam çözümü ver
```

```bash
alleye status                         # sinyaller + en çok çarptığın duvarlar
```

```bash
alleye watch                          # arka planda izle, Ctrl+Alt+E ile çağır
```

```bash
alleye watch --tray                   # konsolu gizle, sistem tepsisine taşı
```

```bash
alleye watch --probe                  # hangi kısayollar boş, listele
```

```bash
alleye autostart --enable             # bilgisayar açılınca arka planda başlat
```

```bash
alleye teach "çözüm: PATH'e ekle"     # az önce takıldığın duvara kendi notunu düş
```

```bash
alleye walls                          # en çok çarptığın duvarlar + kendi notların
```

```bash
alleye look                           # aktif pencereyi (onayınla) modele göster
```

```bash
alleye calibrate                      # yanlış alarm oranını ölç, eşik öner
```

```bash
alleye calibrate --apply              # önerilen eşikleri config.json'a yaz
```

Kısayola bastığında cevap, imlecin yanında çerçevesiz bir pencerede belirir
(Esc = kapat, Enter = kademe derinleştir). Pencere odağı çalmaz; kapanınca
eski pencerene dönersin. `--tray` ile konsol penceresi hiç görünmez.

Kısayol başka bir uygulama tarafından tutuluyorsa All Eye ölmez — yedek
listesinden ilk boş olanı kendisi seçer ve hangisini kullandığını söyler.
Zorlamak için: `alleye watch --hotkey ctrl+shift+e`

Hook kurulduktan sonra terminalde kısaca `ae` yazman yeterli.

---

## Nasıl çalışıyor

```
PowerShell hook  ──▶  journal.jsonl          komut · dizin · süre · exit · ÇIKTI
       │                    │
       │                    ▼
       │              detect.py               tekrar · hata serisi · aynı hata · durgunluk
       │                    │                 (buraya kadar tek bir model çağrısı yok)
       │                    ▼
       │              context.py              + git durumu + son dokunulan dosyalar
       │                    │
       │                    ▼
       │              redact.py               API key / .env / token / parola → maskele
       │                    │                 IP, port, servis sürümü, NTLM hash → DOKUNULMAZ
       │                    ▼
       │              router                  Gemini → Groq → Ollama (ilk cevap veren kazanır)
       │                    │
       ▼                    ▼
  alleye.db  ◀────────  mentor.py             kademe 1 → 2 → 3
  (duvarlar)                                  "bu duvara 4. kez çarpıyorsun"
```

**Çıktı yakalama:** `Start-Transcript` + `prompt` fonksiyonu. Her prompt'ta
transcript dosyasındaki yeni bayt aralığı = az önceki komutun çıktısı. Mevcut
prompt'un (oh-my-posh, posh-git) üstüne biner, ezmez.

**Bash tarafında çıktı yakalanmaz** — komut, dizin, süre ve çıkış kodu kaydedilir.
Bash'te çıktı için oturumu `script` altında çalıştırmak gerekirdi; her terminale
bulaşan bir çözüm olduğu için tercih edilmedi.

## `ae` bulunamıyor / hiç komut kaydedilmiyor

Bazı terminaller (IDE ve uygulama içi terminaller) PowerShell'i `-NoProfile`
ile açar. O zaman profildeki kayıt yerinde durur ama **hiç yüklenmez** — ne `ae`
tanımlanır ne de komutların kaydedilir. `alleye doctor` bunu açıkça söyler:

```
x bu terminalde hook AKTIF DEGIL - komutlar kaydedilmiyor
```

O terminalde hemen açmak için:

```bash
. 'C:\Users\<kullanıcı>\AppData\Local\AllEye\hooks\alleye.ps1'
```

Kalıcı çözümü: profil yükleyen bir terminal kullan (Windows Terminal veya
Başlat menüsünden PowerShell).

## Gizlilik

- Her şey yerelde: `%LOCALAPPDATA%\AllEye\`
- Buluta yalnızca modele giden bağlam gider ve **önce redaksiyondan geçer**
- Pano izleyici (Faz 2) panonu **buluta yollamaz** — sadece yerelde son hatayla
  karşılaştırır ve yalnızca hata-benzeri metni işler. Kapatmak için:
  `config.json` → `"clipboard_watch": false`
- Ekran görüntüsü (`alleye look`) **varsayılan KAPALI**. Açmak için
  `config.json` → `"vision": {"enabled": true}`. Açıkken bile iki kapı var ve
  ikisi de varsayılan olarak reddeder: (1) config bayrağı, (2) her çağrıda
  görüntüyü **kendi gözünle görüp onaylaman**. Esc / İptal / pencereyi kapatma
  = gönderilmez. "Bir daha sorma" seçeneği bilerek yok.
- Tamamen çevrimdışı çalışmak için `config.json` → `"providers": ["ollama"]`
- `ollama pull qwen2.5-coder:7b` — 6 GB VRAM'e sığar, hiçbir veri makineden çıkmaz

## Ayarlar

`%LOCALAPPDATA%\AllEye\config.json`

| Anahtar | Ne işe yarar |
|---|---|
| `providers` | Beyin sırası. İlk cevap veren kazanır. |
| `hotkey` | Varsayılan `ctrl+alt+space` |
| `context.turns` | Modele kaç komut gönderilsin (varsayılan 12) |
| `context.budget_chars` | Toplam bağlam bütçesi |
| `detect.*` | Zorlanma eşikleri |
| `redact` | `false` yaparsan maskeleme kapanır — dikkat |
| `language` | `tr` / `en` |

## Doğrulanmış / doğrulanmamış

```bash
.venv\Scripts\python.exe -m unittest discover tests
```

156 test, ~1.4 saniye, sıfır bağımlılık (stdlib `unittest`). Kapsananlar:
hook'un çıktı dilimlemesi, çıkış kodu tespiti (bayat `$LASTEXITCODE` tuzağı
dahil — test gerçek bir `powershell.exe` başlatır), `alleye` çağrılarının geri
besleme filtresi, sinyal motoru ve eşikleri, hata imzasının kararlılığı,
redaksiyon (nmap port bayrakları ve NTLM hash'leri kasten maskelenmiyor),
`.env` ayrıştırma (BOM dahil), profil yolu alıntılama, sağlayıcı yedekleme
zinciri ve `x-goog-api-key` başlığı.

```bash
.venv\Scripts\python.exe tools\mutation_check.py
```

Bu araç asıl soruyu sorar: **testler gerçekten bir şey koruyor mu?** Bilinen
her tuzağı kaynak koda geri getirir ve ilgili testin kırmızıya düştüğünü
doğrular. Yeşil bir test paketi tek başına hiçbir şey kanıtlamaz — boş bir
paket de yeşildir. Şu an 7 tuzağın hepsi yakalanıyor.

Canlı doğrulandı (2026-07-24, gerçek ücretsiz anahtarla): `x-goog-api-key`
başlığıyla `AQ.` auth key kabul ediliyor. Uçtan uca kademe 1 → 2 → 3 zinciri
çalışıyor, kademe 1 yanıtı **1.5 sn**.

Ölçülen model durumu — `gemini-3-flash` diye bir model **yok**,
`gemini-2.5-flash` yeni kullanıcılara kapalı, `gemini-2.0-flash` ücretsiz
kotası sıfır (429). Büyük flash modelleri (`gemini-3.6-flash`,
`gemini-flash-latest`) ücretsiz katmanda **sık sık 503 "aşırı yük"** dönüyor;
onları zincirin başına koymak her çağrıyı 30–130 sn'ye çıkarıyordu. Bu yüzden
kademe 1-2 `lite` modellerle (~1.5 sn, kararlı), kademe 3 ise `models_deep`
zinciriyle çalışıyor. Zincirde `-latest` takma adları bilerek var: Google
modelleri hızla emekliye ayırıyor, takma adlar yeniden adlandırmaları sessizce
atlatıyor.

`alleye install` **config.json yazmaz** — bu bilinçli. Varsayılanları diske
dondurmak, çalışmayan model adları gibi düzeltmelerin kullanıcıya hiç
ulaşmamasına yol açıyor.

Test edilmedi: gerçek interaktif oturumda `prompt` → `Get-History` akışı.
Şöyle doğrula — yeni bir terminal aç, birkaç komut çalıştır, sonra:

```bash
alleye status
```

`cikti yakalanan: N/N` satırı doluysa hook çalışıyor.

## Sırada ne var

Fazlar, görevler, bitti kriterleri ve karar günlüğü: **[ROADMAP.md](ROADMAP.md)**

Faz 1-2-3 tamamlandı (tepsi · otomatik başlatma · cevap penceresi · teach/walls ·
pasif tespit v2 · pano izleyici · calibrate · aktif pencere bağlamı · `look`).
Sıradaki iş: Faz 4 — öğrenen hafıza (duvarları konuya göre kümele, haftalık özet).
