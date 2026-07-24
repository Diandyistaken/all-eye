"""All Eye test paketi.

Calistirmak icin (proje kokunden):

    .venv\\Scripts\\python.exe -m unittest discover tests

Kural: sifir bagimlilik. pytest yok, sadece stdlib unittest.

Buradaki testlerin cogu "guzel olsun" diye degil, bu projede ZATEN BIR KEZ
sessizce bozulmus seyleri kilitlemek icin var. Her biri bir tuzagi bekliyor:
bayat $LASTEXITCODE, .env BOM'u, ters bolu ikilemesi, olu model adlari,
nmap/NTLM ciktisinin yanlislikla maskelenmesi.
"""
