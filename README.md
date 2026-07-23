# SEC Sentinel - Kurulum ve Çalıştırma

## 1. Sanal ortam (venv) oluşturma

```bash
cd sec-sentinel
python3 -m venv venv
source venv/bin/activate
```

## 2. Bağımlılıkları kurma

```bash
pip install -r requirements.txt
```

## 3. .env dosyasını doldurma

```bash
cp .env.example .env
```

`.env` dosyasını açıp şu alanları doldurun:

- `TELEGRAM_BOT_TOKEN`: BotFather üzerinden oluşturduğunuz bot token'ı.
- `TELEGRAM_CHAT_ID`: Bildirimlerin gönderileceği chat ID (bkz. adım 4).
- `EDGAR_IDENTITY`: SEC EDGAR'ın istediği format ile "Ad Soyad eposta@ornek.com"
  şeklinde bir kimlik. Bu değer olmadan SEC istekleri 403 ile reddedilir.

## 4. chat_id öğrenme yöntemi

1. Telegram'da BotFather ile oluşturduğunuz bota gidin ve `/start` yazın.
2. `.env` dosyasındaki `TELEGRAM_CHAT_ID` alanını geçici olarak herhangi bir
   sayı ile doldurup botu bir kere manuel çalıştırın (adım 5).
3. Bota gönderdiğiniz `/start` komutu konsol loglarına chat_id'yi yazdıracaktır
   (`chat_id: <sayı>` satırı). Bu değeri kopyalayıp `.env` dosyasındaki
   `TELEGRAM_CHAT_ID` alanına yapıştırın ve botu yeniden başlatın.

## 5. Manuel çalıştırma

```bash
source venv/bin/activate
python main.py
```

İlk çalıştırmada `seen.json` dosyası oluşturulur, mevcut belgeler sessizce
"görüldü" olarak işaretlenir ve hiçbir Telegram mesajı gönderilmez. Sonraki
taramalarda yalnızca gerçekten yeni belgeler bildirilir.

Botu durdurmak için `Ctrl+C` kullanın.

## 6. systemd (--user) ile kurma

1. `sec-sentinel.service` dosyasındaki `/path/to/sec-sentinel` yer
   tutucularını gerçek proje yoluyla değiştirin (venv'in de bu yol altında
   oluşturulmuş olması gerekir).
2. Servis dosyasını kullanıcı systemd dizinine kopyalayın:

   ```bash
   mkdir -p ~/.config/systemd/user
   cp sec-sentinel.service ~/.config/systemd/user/
   ```

3. Servisi etkinleştirip başlatın:

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now sec-sentinel.service
   ```

4. Logları izlemek için:

   ```bash
   journalctl --user -u sec-sentinel.service -f
   ```

5. Oturum kapandığında servisin çalışmaya devam etmesini istiyorsanız:

   ```bash
   loginctl enable-linger $USER
   ```

## Telegram komutları

- `/start`: Botun aktif olduğunu bildirir ve chat_id'yi konsola loglar.
- `/test`: Bekleme döngüsünü atlayıp takip listesindeki her kayıt için en
  son 1 belgeyi (form tipi fark etmeksizin) gönderir. `seen.json`'u değiştirmez.
- `/status`: Son tarama zamanını, takip edilen CIK sayısını, `seen.json`
  kayıt sayısını ve varsa son hata mesajını döner.

## GitHub Actions ile çalıştırma

Bot, sürekli çalışan bir süreç yerine saatte bir tetiklenen bir GitHub
Actions workflow'u (`.github/workflows/sentinel.yml`) olarak da
çalıştırılabilir. Bu modda `python main.py --once` çağrılır: tek bir
tarama turu çalışır, `seen.json` güncellenirse repoya commit + push
edilir ve süreç çıkar.

### Secrets nasıl eklenir

1. GitHub'da repo sayfasında **Settings > Secrets and variables > Actions**
   sekmesine gidin.
2. **New repository secret** ile şu üç secret'ı ekleyin:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `EDGAR_IDENTITY`
3. Değerler yerel `.env` dosyanızdakiyle aynı olmalı.

### Elle test etme

**Actions** sekmesinden `sec-sentinel` workflow'unu seçip **Run workflow**
butonuyla zamanlamayı beklemeden elle tetikleyebilirsiniz.

### 60 gün kuralı

GitHub, bir repoda 60 gün boyunca hiç insan commit'i olmazsa o repodaki
zamanlanmış (`schedule`) workflow'ları otomatik olarak devre dışı bırakır.
Bu durumda **Actions** sekmesinden workflow'u tekrar etkinleştirmeniz
(veya elle bir commit atmanız) gerekir.

### Yerel/systemd kullanımı

GitHub Actions ile çalıştırma, yerel/systemd kullanımının yerine geçmez;
ikisi birbirinden bağımsızdır. Yukarıdaki 5. ve 6. adımlarda anlatılan
`python main.py` (polling) ve systemd servisi aynen geçerliliğini korur —
isterseniz botu yerelde sürekli çalışır halde tutabilir, isterseniz sadece
GitHub Actions'a bırakabilir, isterseniz ikisini aynı anda çalıştırmayabilirsiniz
(aynı anda ikisini çalıştırmak aynı chat'e çift bildirim gönderebilir).
