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
    # 1-VarlikYoneticisi/Banka
    ("Aegon", "0000769218", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("AllianceBernstein", "0000825313", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Ameriprise", "0000820027", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("BBVA", "0000842180", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Bank of America", "0000070858", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Bank of New York Mellon", "0001390777", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Barclays", "0000312069", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Charles Schwab", "0000316709", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Citigroup", "0000831001", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Deutsche Bank", "0001159508", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Franklin Resources", "0000038777", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Goldman Sachs", "0000886982", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("HSBC", "0001089113", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Invesco", "0000914208", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("JPMorgan Chase", "0000019617", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Jefferies", "0000096223", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("LPL Financial", "0001397911", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Lazard", "0001311370", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Manulife", "0001086888", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("MetLife", "0001099219", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Morgan Stanley", "0000895421", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Northern Trust", "0000073124", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Principal Financial", "0001126328", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Prudential", "0001137774", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Raymond James", "0000720005", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Santander", "0000891478", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Stifel", "0000720672", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Sun Life", "0001097362", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("T. Rowe Price", "0001113169", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("TD Bank", "0000947263", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("UBS Group", "0001610520", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Wells Fargo", "0000072971", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    # 2-HedgeFon/OzelSermaye
    ("Apollo Global", "0001858681", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Ares Management", "0001176948", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Blackstone", "0001393818", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Brookfield Asset Management", "0001937926", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("Carlyle Group", "0001527166", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("KKR", "0001404912", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    ("TPG", "0001880661", ["13F-HR", "13F-HR/A", "SC 13D", "SC 13D/A"]),
    # 3-Teknoloji/Sanayi
    ("3M", "0000066740", ["4", "4/A"]),
    ("AMD", "0000002488", ["4", "4/A"]),
    ("AT&T", "0000732717", ["4", "4/A"]),
    ("AbbVie", "0001551152", ["4", "4/A"]),
    ("Abbott", "0000001800", ["4", "4/A"]),
    ("Adobe", "0000796343", ["4", "4/A"]),
    ("Alphabet (Google)", "0001652044", ["4", "4/A"]),
    ("Amazon", "0001018724", ["4", "4/A"]),
    ("Amgen", "0000318154", ["4", "4/A"]),
    ("Apple", "0000320193", ["4", "4/A"]),
    ("Biogen", "0000875045", ["4", "4/A"]),
    ("Boeing", "0000012927", ["4", "4/A"]),
    ("Boston Scientific", "0000885725", ["4", "4/A"]),
    ("Broadcom", "0001730168", ["4", "4/A"]),
    ("Caterpillar", "0000018230", ["4", "4/A"]),
    ("Chevron", "0000093410", ["4", "4/A"]),
    ("Cisco", "0000858877", ["4", "4/A"]),
    ("Coca-Cola", "0000021344", ["4", "4/A"]),
    ("Comcast", "0001166691", ["4", "4/A"]),
    ("ConocoPhillips", "0001163165", ["4", "4/A"]),
    ("Costco", "0000909832", ["4", "4/A"]),
    ("Cummins", "0000026172", ["4", "4/A"]),
    ("Danaher", "0000313616", ["4", "4/A"]),
    ("Deere & Co", "0000315189", ["4", "4/A"]),
    ("Disney", "0001744489", ["4", "4/A"]),
    ("Dominion Energy", "0000715957", ["4", "4/A"]),
    ("Duke Energy", "0001326160", ["4", "4/A"]),
    ("EOG Resources", "0000821189", ["4", "4/A"]),
    ("Eaton", "0001551182", ["4", "4/A"]),
    ("Eli Lilly", "0000059478", ["4", "4/A"]),
    ("Emerson", "0000032604", ["4", "4/A"]),
    ("ExxonMobil", "0000034088", ["4", "4/A"]),
    ("Ford", "0000037996", ["4", "4/A"]),
    ("GE Aerospace", "0000040545", ["4", "4/A"]),
    ("General Dynamics", "0000040533", ["4", "4/A"]),
    ("General Motors", "0001467858", ["4", "4/A"]),
    ("Gilead Sciences", "0000882095", ["4", "4/A"]),
    ("Home Depot", "0000354950", ["4", "4/A"]),
    ("Honeywell", "0000773840", ["4", "4/A"]),
    ("IBM", "0000051143", ["4", "4/A"]),
    ("Illumina", "0001110803", ["4", "4/A"]),
    ("Intel", "0000050863", ["4", "4/A"]),
    ("Johnson & Johnson", "0000200406", ["4", "4/A"]),
    ("L3Harris", "0000202058", ["4", "4/A"]),
    ("Lockheed Martin", "0000936468", ["4", "4/A"]),
    ("Marathon", "0001510295", ["4", "4/A"]),
    ("Medtronic", "0001613103", ["4", "4/A"]),
    ("Merck", "0000310158", ["4", "4/A"]),
    ("Meta (Facebook)", "0001326801", ["4", "4/A"]),
    ("Microsoft", "0000789019", ["4", "4/A"]),
    ("Netflix", "0001065280", ["4", "4/A"]),
    ("NextEra Energy", "0000753308", ["4", "4/A"]),
    ("Northrop Grumman", "0001133421", ["4", "4/A"]),
    ("Nvidia", "0001045810", ["4", "4/A"]),
    ("Occidental Petroleum", "0000797468", ["4", "4/A"]),
    ("Oracle", "0001341439", ["4", "4/A"]),
    ("P&G", "0000080424", ["4", "4/A"]),
    ("Parker-Hannifin", "0000076334", ["4", "4/A"]),
    ("PepsiCo", "0000077476", ["4", "4/A"]),
    ("Pfizer", "0000078003", ["4", "4/A"]),
    ("Phillips 66", "0001534701", ["4", "4/A"]),
    ("Qualcomm", "0000804328", ["4", "4/A"]),
    ("Regeneron", "0000872589", ["4", "4/A"]),
    ("Salesforce", "0001108524", ["4", "4/A"]),
    ("Southern Company", "0000092122", ["4", "4/A"]),
    ("Stellantis", "0001605484", ["4", "4/A"]),
    ("Stryker", "0000310764", ["4", "4/A"]),
    ("T-Mobile", "0001283699", ["4", "4/A"]),
    ("Target", "0000027419", ["4", "4/A"]),
    ("Tesla", "0001318605", ["4", "4/A"]),
    ("Thermo Fisher Scientific", "0000097745", ["4", "4/A"]),
    ("Valero", "0001035002", ["4", "4/A"]),
    ("Verizon", "0000732712", ["4", "4/A"]),
    ("Vertex Pharmaceuticals", "0000875320", ["4", "4/A"]),
    ("Walmart", "0000104169", ["4", "4/A"]),
    ("Xcel Energy", "0000072903", ["4", "4/A"]),
    # 5-YeniNesilSirket
    ("Airbnb", "0001559720", ["4", "4/A"]),
    ("Atlassian", "0001650372", ["4", "4/A"]),
    ("Block (Square)", "0001512673", ["4", "4/A"]),
    ("Booking Holdings", "0001075531", ["4", "4/A"]),
    ("Circle", "0001876042", ["4", "4/A"]),
    ("Cloudflare", "0001477333", ["4", "4/A"]),
    ("CrowdStrike", "0001535527", ["4", "4/A"]),
    ("DoorDash", "0001792789", ["4", "4/A"]),
    ("Electronic Arts", "0000712515", ["4", "4/A"]),
    ("Expedia", "0001324424", ["4", "4/A"]),
    ("Fortinet", "0001262039", ["4", "4/A"]),
    ("HubSpot", "0001404655", ["4", "4/A"]),
    ("Instacart", "0001579091", ["4", "4/A"]),
    ("Lyft", "0001759509", ["4", "4/A"]),
    ("MercadoLibre", "0001099590", ["4", "4/A"]),
    ("Nubank", "0001691493", ["4", "4/A"]),
    ("PagSeguro", "0001712807", ["4", "4/A"]),
    ("Palo Alto Networks", "0001327567", ["4", "4/A"]),
    ("PayPal", "0001633917", ["4", "4/A"]),
    ("Robinhood", "0001783879", ["4", "4/A"]),
    ("Roblox", "0001315098", ["4", "4/A"]),
    ("Sea Limited", "0001703399", ["4", "4/A"]),
    ("ServiceNow", "0001373715", ["4", "4/A"]),
    ("Shopify", "0001594805", ["4", "4/A"]),
    ("Snowflake", "0001640147", ["4", "4/A"]),
    ("Spotify", "0001639920", ["4", "4/A"]),
    ("StoneCo", "0001745431", ["4", "4/A"]),
    ("Take-Two Interactive", "0000946581", ["4", "4/A"]),
    ("Uber", "0001543151", ["4", "4/A"]),
    ("Unity Software", "0001810806", ["4", "4/A"]),
    ("Workday", "0001327811", ["4", "4/A"]),
    ("Zscaler", "0001713683", ["4", "4/A"]),
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
