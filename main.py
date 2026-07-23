import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

import edgar
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sec-sentinel")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.error(
            "%s .env dosyasında tanımlı değil. Lütfen .env.example dosyasını "
            "referans alarak .env dosyasını doldurun. Çıkılıyor.",
            name,
        )
        sys.exit(1)
    return value


TELEGRAM_BOT_TOKEN = require_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID_RAW = require_env("TELEGRAM_CHAT_ID")
EDGAR_IDENTITY = require_env("EDGAR_IDENTITY")

try:
    TELEGRAM_CHAT_ID = int(TELEGRAM_CHAT_ID_RAW)
except ValueError:
    logger.error(
        "TELEGRAM_CHAT_ID sayısal bir değer olmalı (örn. 123456789). Çıkılıyor."
    )
    sys.exit(1)

edgar.set_identity(EDGAR_IDENTITY)

# --- Takip listesi ---
# (isim, CIK, izlenecek form tipleri listesi)
# Yeni bir kayıt eklemek için bu listeye tek bir satır eklemek yeterlidir.
WATCHLIST = [
    ("Berkshire Hathaway", "0001067983", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("BlackRock Inc", "0002012383", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Palantir Technologies", "0001321655", ["4", "4/A"]),
]

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
MAX_SEEN_RECORDS = 2000
INITIAL_SEED_MAX_COUNT = 50
INITIAL_SEED_MAX_DAYS = 90
MAX_MESSAGES_PER_CIK = 5
CIK_DELAY_SECONDS = 0.5
MESSAGE_DELAY_SECONDS = 1
SCAN_INTERVAL_SECONDS = 900
SCAN_FIRST_SECONDS = 15


def load_seen_state():
    """seen.json'u okur. Dosya yoksa veya bozuksa ilk çalıştırma olarak
    değerlendirir ve boş listeyle sessizce başlar."""
    if not os.path.exists(SEEN_FILE):
        return [], True
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        seen = data.get("seen", [])
        if not isinstance(seen, list):
            raise ValueError("'seen' alanı bir liste değil")
        return seen, False
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning(
            "seen.json bozuk veya okunamıyor (%s); sıfırdan sessizce başlatılıyor.", e
        )
        return [], True


def save_seen(seen_list):
    """seen.json'a atomik olarak yazar. Kayıt sayısı MAX_SEEN_RECORDS'u
    aşarsa en eski kayıtlar silinir."""
    if len(seen_list) > MAX_SEEN_RECORDS:
        del seen_list[: len(seen_list) - MAX_SEEN_RECORDS]
    seen_dir = os.path.dirname(SEEN_FILE) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".seen_", suffix=".tmp", dir=seen_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            json.dump({"seen": seen_list}, tmp_file)
        os.replace(tmp_path, SEEN_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


async def fetch_filings_for_cik(cik: str, forms: list):
    def _fetch():
        company = edgar.Company(cik)
        return company.get_filings(form=forms)

    return await asyncio.to_thread(_fetch)


async def fetch_recent_filings_for_cik(cik: str, forms: list):
    """Yalnızca son INITIAL_SEED_MAX_DAYS gün içindeki belgeleri getirir.
    İlk taramada 'görüldü' olarak damgalanan belgeler de her zaman bu
    pencerenin içinde kaldığından, düzenli taramayı bu pencereyle
    sınırlamak eski belgelerin sahte 'yeni' olarak görünmesini engeller."""

    def _fetch():
        start = (date.today() - timedelta(days=INITIAL_SEED_MAX_DAYS)).isoformat()
        end = date.today().isoformat()
        company = edgar.Company(cik)
        return company.get_filings(form=forms, date=(start, end))

    return await asyncio.to_thread(_fetch)


async def fetch_latest_filing(cik: str):
    def _fetch():
        company = edgar.Company(cik)
        filings = company.get_filings()
        if len(filings) == 0:
            return None
        return filings[0]

    return await asyncio.to_thread(_fetch)


def format_message(name: str, filing) -> str:
    filing_date = filing.filing_date
    if hasattr(filing_date, "isoformat"):
        date_str = filing_date.isoformat()
    else:
        date_str = str(filing_date)
    return (
        "🚨 YENİ SEC BİLDİRİMİ!\n"
        f"🏢 Kurum/Kişi: {name}\n"
        f"📄 Belge Türü: {filing.form}\n"
        f"📅 Tarih: {date_str}\n"
        f"🔗 Detay: {filing.url}"
    )


async def run_initial_seed(bot_data):
    logger.info(
        "seen.json bulunamadı ya da bozuk; ilk çalıştırma taraması başlıyor "
        "(hiçbir mesaj gönderilmeyecek)."
    )
    seen_list = bot_data["seen"]
    seen_set = bot_data["seen_set"]
    for name, cik, forms in WATCHLIST:
        try:
            filings = await fetch_filings_for_cik(cik, forms)
            last_n = list(filings[:INITIAL_SEED_MAX_COUNT])
            cutoff = date.today() - timedelta(days=INITIAL_SEED_MAX_DAYS)
            within_days = [f for f in filings if f.filing_date >= cutoff]
            chosen = within_days if len(within_days) <= len(last_n) else last_n

            added = 0
            for f in chosen:
                acc = f.accession_number
                if acc not in seen_set:
                    seen_list.append(acc)
                    seen_set.add(acc)
                    added += 1
            save_seen(seen_list)
            logger.info("%s (%s): %d belge 'görüldü' olarak damgalandı.", name, cik, added)
        except Exception as e:
            logger.exception("İlk tarama sırasında %s (%s) için hata oluştu", name, cik)
            bot_data["last_error"] = f"İlk tarama hatası - {name} ({cik}): {e}"
        await asyncio.sleep(CIK_DELAY_SECONDS)
    logger.info("İlk çalıştırma taraması tamamlandı.")


async def run_scan(bot, bot_data):
    seen_list = bot_data["seen"]
    seen_set = bot_data["seen_set"]

    for name, cik, forms in WATCHLIST:
        try:
            filings = await fetch_recent_filings_for_cik(cik, forms)
            new_filings = [f for f in filings if f.accession_number not in seen_set]
            new_filings.sort(key=lambda f: f.filing_date)

            to_send = new_filings[:MAX_MESSAGES_PER_CIK]
            remaining = len(new_filings) - len(to_send)

            for f in to_send:
                text = format_message(name, f)
                try:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
                except Exception as e:
                    logger.exception(
                        "Telegram mesajı gönderilemedi (%s, %s)", name, f.accession_number
                    )
                    bot_data["last_error"] = f"Telegram gönderim hatası - {name}: {e}"
                    await asyncio.sleep(MESSAGE_DELAY_SECONDS)
                    continue

                seen_list.append(f.accession_number)
                seen_set.add(f.accession_number)
                save_seen(seen_list)
                await asyncio.sleep(MESSAGE_DELAY_SECONDS)

            if remaining > 0:
                summary_text = f"+{remaining} belge daha ({name})"
                try:
                    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=summary_text)
                except Exception as e:
                    logger.exception("Özet mesajı gönderilemedi (%s)", name)
                    bot_data["last_error"] = f"Telegram gönderim hatası - {name} özet: {e}"
                await asyncio.sleep(MESSAGE_DELAY_SECONDS)
        except Exception as e:
            logger.exception("CIK taranırken hata oluştu: %s (%s)", name, cik)
            bot_data["last_error"] = f"Tarama hatası - {name} ({cik}): {e}"

        await asyncio.sleep(CIK_DELAY_SECONDS)


async def run_scan_cycle(bot, bot_data):
    """Tek bir tarama turu: seen.json yoksa sessiz damgalama, varsa normal
    tarama. Hem job_queue callback'i (scan_job) hem de --once modu bu
    ortak fonksiyonu kullanır."""
    if bot_data.get("first_run_pending"):
        await run_initial_seed(bot_data)
        bot_data["first_run_pending"] = False
    else:
        await run_scan(bot, bot_data)
    bot_data["last_scan_time"] = datetime.now()


async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    await run_scan_cycle(context.bot, context.application.bot_data)


async def start_command(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logger.info("chat_id: %s", chat_id)
    await update.message.reply_text(
        "SEC Radar Botu aktif. Sistem arka planda 13F, 13D ve Form 4 "
        "belgelerini tarıyor."
    )


async def test_command(update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    bot = context.bot
    for name, cik, _forms in WATCHLIST:
        try:
            filing = await fetch_latest_filing(cik)
            if filing is None:
                logger.warning("%s (%s) için hiç belge bulunamadı.", name, cik)
                await asyncio.sleep(CIK_DELAY_SECONDS)
                continue
            text = format_message(name, filing)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
            await asyncio.sleep(MESSAGE_DELAY_SECONDS)
        except Exception as e:
            logger.exception("/test sırasında %s (%s) için hata oluştu", name, cik)
            bot_data["last_error"] = f"/test hatası - {name} ({cik}): {e}"
        await asyncio.sleep(CIK_DELAY_SECONDS)


async def status_command(update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.application.bot_data
    last_scan_time = bot_data.get("last_scan_time")
    last_scan_str = (
        last_scan_time.strftime("%Y-%m-%d %H:%M:%S")
        if last_scan_time
        else "Henüz tarama yapılmadı"
    )
    seen_count = len(bot_data.get("seen", []))
    last_error = bot_data.get("last_error") or "Yok"
    text = (
        f"Son tarama zamanı: {last_scan_str}\n"
        f"Takip edilen CIK sayısı: {len(WATCHLIST)}\n"
        f"seen.json kayıt sayısı: {seen_count}\n"
        f"Son hata: {last_error}"
    )
    await update.message.reply_text(text)


async def run_once(bot_data):
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    async with bot:
        await run_scan_cycle(bot, bot_data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once",
        action="store_true",
        help="Tek bir tarama turu çalıştırıp çıkar; polling/job_queue başlatmaz.",
    )
    args = parser.parse_args()

    seen_list, is_first_run = load_seen_state()

    if args.once:
        bot_data = {
            "seen": seen_list,
            "seen_set": set(seen_list),
            "last_scan_time": None,
            "last_error": None,
            "first_run_pending": is_first_run,
        }
        try:
            asyncio.run(run_once(bot_data))
        except Exception:
            logger.exception("--once modunda beklenmeyen bir hata oluştu.")
            sys.exit(1)
        sys.exit(0)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.bot_data["seen"] = seen_list
    application.bot_data["seen_set"] = set(seen_list)
    application.bot_data["last_scan_time"] = None
    application.bot_data["last_error"] = None
    application.bot_data["first_run_pending"] = is_first_run

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("test", test_command))
    application.add_handler(CommandHandler("status", status_command))

    application.job_queue.run_repeating(
        scan_job, interval=SCAN_INTERVAL_SECONDS, first=SCAN_FIRST_SECONDS
    )

    logger.info("SEC Sentinel başlatılıyor...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
