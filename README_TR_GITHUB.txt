COPYGUARD GITHUB ACTIONS v1

Bu sürüm:
- GitHub Actions ile 5 dakikada bir çalışır.
- 15m / 1H / 4H / 1D veriye bakar.
- 1D = büyük yön/risk filtresi.
- 4H = ana trend.
- 1H = işlem yönü.
- 15m = giriş tetikleyici.
- Binance API key gerekmez.
- Otomatik emir açmaz.
- Telegram'a sadece kaliteli sinyal gönderir.
- Aynı coin/yön için 6 saat cooldown uygular.
- Sinyal yoksa Telegram'a mesaj atmaz.

GITHUB KURULUM ÖZETİ

1) GitHub hesabına gir.
2) New repository oluştur.
   Repository name: copyguard-bot
   Public seçmen önerilir.
3) Bu ZIP içindeki dosyaları repo'ya yükle:
   - copyguard_github.py
   - .github/workflows/copyguard.yml
4) Repo → Settings → Secrets and variables → Actions
5) Secrets sekmesine şunları ekle:
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
6) Variables sekmesine şunları ekleyebilirsin:
   ACCOUNT_CAPITAL_USDT = 500
   POSITION_USDT_PER_SIGNAL = 40
7) Repo → Actions sekmesi
8) CopyGuard Signals workflow'unu aç
9) Run workflow ile manuel test et
10) Sonra 5 dakikada bir otomatik çalışır.

ÖNEMLİ
Telegram tokenını hiçbir dosyaya yazma.
Sadece GitHub Secrets içine yaz.
Daha önce token ekran görüntüsünde göründüyse BotFather'dan yeni token al.
