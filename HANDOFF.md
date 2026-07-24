# Devralma promptu

Yeni bir Claude Code / Cowork oturumu açtığında aşağıdaki bloğu olduğu gibi
yapıştır. Kendi kendine yeter: proje durumu, tuzaklar, kararlar ve sıradaki iş
içinde.

---

```
Bir projeyi devralıyorsun. Aşağıdaki her şey doğrulanmış gerçek durum, varsayım değil.

## PROJE

C:\dev\Projeler\All Eye — "All Eye": kullanıcının takıldığı anı fark edip
cevabı hemen vermeden, kademeli olarak elinden tutan yerel mentor aracı.
Python, sıfır bağımlılık (sadece stdlib), Windows 11 hedefli.

Önce şunları oku, hepsi güncel:
- README.md   (ne olduğu, kurulum, doğrulanmış/doğrulanmamış)
- ROADMAP.md  (fazlar, görevler, bitti kriterleri, karar günlüğü, teknik borç)

## MAKİNE VE ORTAM (kontrol etme, böyle)

- i7-11800H, 32 GB RAM, RTX 3060 Laptop 6 GB VRAM, Windows 11 Pro
- Python 3.12 venv: "C:\dev\Projeler\All Eye\.venv"
  Komut: .venv\Scripts\alleye.exe  (editable install, kod değişikliği anında geçerli)
- Veri klasörü: %LOCALAPPDATA%\AllEye  (journal.jsonl, alleye.db, .env, hooks/)
- Gemini API anahtarı KURULU ve ÇALIŞIYOR. Groq yok, Ollama kurulu değil.
- Shell hook kurulu: PowerShell profili + .bashrc
- Kısayol: ctrl+alt+e
- Kullanıcı Türkçe konuşuyor, cevapları Türkçe ver.
- Kullanıcı ücretli hiçbir servis istemiyor. Sadece ücretsiz katman + yerel.

## ŞU ANA KADAR NE YAPILDI (Faz 0 — bitti, canlı doğrulandı)

Çalışan uçtan uca zincir:
PowerShell hook → journal.jsonl → zorlanma tespiti → bağlam paketi →
redaksiyon → Gemini → kademeli mentor (1 dürtme / 2 yön / 3 tam çözüm) →
SQLite duvar hafızası ("bu duvara N. kez çarpıyorsun")

Ölçülmüş: kademe 1 yanıtı 1.5 sn. `git status` → exit=128 doğru yakalanıyor.

## TUZAKLAR — bunlar zaten bir kez sessizce bozdu, tekrar açma

1. $LASTEXITCODE cmdlet'ler tarafından GÜNCELLENMEZ. Bir cmdlet hatasından
   sonra önceki native komuttan kalma bayat değer okunur. Hook bunu "değişti mi"
   + "komut gerçekten harici program mı" diye çözüyor. Bozma.
2. .env dosyası utf-8-sig ile okunmalı. Notepad/PowerShell BOM yazıyor, BOM
   temizlenmezse ilk satırın anahtar adı eşleşmiyor ve "kaydettim ama tanımlı
   değil" diyen sessiz hata çıkıyor.
3. install config.json YAZMAZ. Yazarsa varsayılanlar diske donuyor ve
   sonraki düzeltmeler (ölü model adları gibi) kullanıcıya hiç ulaşmıyor.
4. Gemini kimlik doğrulama x-goog-api-key BAŞLIĞI ile. Yeni AQ. auth key'ler
   eski ?key= parametresiyle çalışmıyor.
5. Model adları hızla ölüyor. Ölçülen durum: gemini-3-flash YOK,
   gemini-2.5-flash yeni kullanıcılara kapalı, gemini-2.0-flash kotası sıfır.
   Büyük flash modelleri ücretsiz katmanda sık 503 veriyor — bu yüzden
   kademe 1-2 lite modelle, kademe 3 models_deep zinciriyle çalışıyor.
6. Bazı terminaller PowerShell'i -NoProfile ile açar; o zaman hook hiç
   yüklenmez. doctor bunu ALLEYE_HOOK_LOADED ortam değişkeninden tespit ediyor.
7. Profile yol yazarken json.dumps KULLANMA — ters bölüleri ikiye katlıyor.
   install._ps_quote() kullan.

## DEĞİŞMEZ TASARIM KARARLARI — ihlal etme

- Bağlam ekran görüntüsünden değil TERMİNALDEN gelir. Ekran görüntüsü sadece
  terminal dışı pencereler için, son çare, ve Faz 3'te.
- Cevap 3 kademede açılır, kademeyi KULLANICI açar. Hazır cevap öğrenmeyi bozar.
- Daemon asla kendiliğinden pencere açmaz. Sadece haber verir.
- Sıfır Python bağımlılığı. Sürekli açık süreç 60-80 MB'da kalmalı.
- Redaksiyon: gerçek sırlar maskelenir; IP, port, servis sürümü, NTLM hash
  ASLA maskelenmez (pentest mentoru tam da onlara bakmalı).

## SIRADAKİ İŞ

Öncelik 1 — TEST ALTYAPISI (ROADMAP > Teknik borç).
Bu projede dört ayrı sessiz hata çıktı ve hiçbirini yakalayan ağ yok.
tests/ altına stdlib unittest ile (pytest ekleme, sıfır bağımlılık kuralı):
  - redact: sırlar maskeleniyor + nmap port bayrakları/NTLM hash maskelenmiyor
  - journal.fingerprint: PowerShell gürültü satırları atlanıyor, imza kararlı
  - detect: tekrar/hata serisi/aynı hata/durgunluk eşikleri
  - config.load_env_file: BOM'lu dosya, export öneki, tırnaklı değer
  - install._ps_quote: ters bölü ikiye katlanmıyor
  - context.recent_files: ana klasörde boş döner, süre sınırı çalışır
Bitti kriteri: `python -m unittest discover tests` yeşil, ve yukarıdaki
tuzakların her biri için en az bir kırmızıya düşen test var.

Öncelik 2 — Faz 1.1: sistem tepsisi ikonu (ROADMAP'te detaylı).

## NASIL ÇALIŞ

- Komutları SEN çalıştır. Kullanıcıya "şunu çalıştır" deme, kendin yap ve
  sonucu göster. Kullanıcı terminale hiçbir şey yazmak istemiyor.
- İddia etme, doğrula. "Çalışıyor" demeden önce gerçekten çalıştır ve çıktıyı
  göster. Testler kırmızıysa kırmızı olduğunu söyle.
- Sessiz hata avla. Bir şey beklendiği gibi davranmıyorsa tahmin yürütme,
  ölç: dosyayı oku, komutu çalıştır, gerçek çıktıya bak.
- Kısa konuş. Uzun açıklama değil, yapılan iş + kanıt.
- Bir faz bitmeden sonrakine geçme. ROADMAP'teki bitti kriterlerini uygula.
- İş bitince ROADMAP.md'de kutuları işaretle ve yeni kararları karar
  günlüğüne ekle.
- Geri alınamaz veya yıkıcı bir şey (dosya silme, git push, profil değişikliği,
  paket kaldırma) gerekirse ÖNCE sor. Onun dışında durma, ilerle.

Şimdi README.md ve ROADMAP.md'yi oku, ortamın hâlâ sağlam olduğunu
`.venv\Scripts\alleye.exe doctor` ile doğrula, sonra test altyapısını kur.
```

---

## Notlar

- Claude Code'da izin sorularını azaltmak için oturum başında izin modunu
  gevşetebilirsin; aksi halde her komut için tek tek onay çıkar.
- Bu dosyayı proje ilerledikçe güncelle: "ŞU ANA KADAR NE YAPILDI" ve
  "SIRADAKİ İŞ" bölümleri her faz sonunda değişmeli.
