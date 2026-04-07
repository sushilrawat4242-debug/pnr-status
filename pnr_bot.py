import json
import logging
import requests
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 🔑 ===== PASTE YOUR KEYS HERE =====
TELEGRAM_TOKEN = "8427049559:AAFhAXiJED29D6IRqXKY7Ljf5XjqGbT02Gw"
RAPIDAPI_KEY = "36a9842a80msha50310f34107567p17bc15jsnd03625f34d0a"
# ==================================

CHECK_INTERVAL_MINUTES = 10
DATA_FILE = Path("pnr_data.json")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 📂 Load/save data
def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

tracked_pnrs = load_data()

# 🚂 Fetch PNR from RapidAPI
def fetch_pnr_status(pnr):
    url = f"https://irctc-indian-railway-pnr-status.p.rapidapi.com/getPNRStatus/{pnr}"

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "irctc-indian-railway-pnr-status.p.rapidapi.com",
        "Content-Type": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        raw = response.json()

        print("DEBUG FULL RESPONSE:", json.dumps(raw, indent=2))

        # Print first passenger fields for debugging
        passengers = []
        if "data" in raw:
            passengers = raw["data"].get("passengerList", [])
        elif "passengerList" in raw:
            passengers = raw.get("passengerList", [])
        if passengers:
            print("PASSENGER FIELDS:", json.dumps(passengers[0], indent=2))

        if not isinstance(raw, dict):
            return None

        if "data" in raw:
            return raw["data"]
        elif "passengerList" in raw or "PassengerStatus" in raw:
            return raw
        elif "Pnr" in raw or "pnr" in raw or "PnrNumber" in raw:
            return raw
        else:
            print("❌ Unknown structure. Keys:", list(raw.keys()))
            return None

    except Exception as e:
        logger.error(f"Error fetching PNR: {e}")
        return None


def format_message(pnr, data):
    passengers = (
        data.get("passengerList")
        or data.get("PassengerStatus")
        or data.get("Passengers")
        or []
    )

    train_name = data.get("trainName") or data.get("TrainName") or "N/A"
    train_no   = data.get("trainNumber") or data.get("TrainNo") or "N/A"
    source     = data.get("sourceStation") or data.get("From") or "N/A"
    dest       = data.get("destinationStation") or data.get("To") or "N/A"
    date       = data.get("dateOfJourney") or data.get("DepartureDate") or "N/A"
    chart      = data.get("chartPrepared") or data.get("ChartPrepared") or "N/A"

    msg  = f"🚂 *PNR: {pnr}*\n"
    msg += f"🚆 Train: {train_name} ({train_no})\n"
    msg += f"📍 From: {source}\n"
    msg += f"📍 To: {dest}\n"
    msg += f"📅 Date: {date}\n"
    msg += f"📋 Chart Prepared: {chart}\n\n"
    msg += "👥 *Passenger Status:*\n"

    if not passengers:
        msg += "• No passenger data found\n"
    else:
        for i, p in enumerate(passengers, 1):
            current = p.get("currentStatus") or p.get("CurrentStatus") or "Unknown"
            booking = p.get("bookingStatus") or p.get("BookingStatus") or "Unknown"
            coach   = p.get("currentCoachId") or p.get("coachId") or p.get("Coach") or ""
            berth   = p.get("currentBerthNo") or p.get("berthNo") or p.get("Berth") or ""
            seat    = p.get("seatNo") or p.get("SeatNo") or ""

            msg += f"\n👤 *Passenger {i}:*\n"
            msg += f"  • Booking: `{booking}`\n"
            msg += f"  • Current: `{current}`\n"
            if coach: msg += f"  • Coach: `{coach}`\n"
            if berth: msg += f"  • Berth No: `{berth}`\n"
            if seat:  msg += f"  • Seat No: `{seat}`\n"

    msg += f"\n🕐 Updated: {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
    return msg


def fingerprint(data):
    passengers = (
        data.get("passengerList")
        or data.get("PassengerStatus")
        or data.get("Passengers")
        or []
    )
    return "|".join([
        p.get("currentStatus")
        or p.get("CurrentStatus")
        or ""
        for p in passengers
    ])


# 📲 Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = "👋 *Welcome to PNR Status Bot!*\n\n"
    msg += "Available commands:\n"
    msg += "📌 /track <PNR> — Start tracking a PNR\n"
    msg += "📊 /status <PNR> — Check current status\n"
    msg += "🗑 /untrack <PNR> — Stop tracking a PNR\n"
    msg += "📋 /list — List all tracked PNRs\n"
    await update.message.reply_text(msg, parse_mode="Markdown")


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /track <PNR>\nExample: /track 4334410565")
        return

    pnr = context.args[0].strip()

    if len(pnr) != 10 or not pnr.isdigit():
        await update.message.reply_text("❌ PNR must be exactly 10 digits.")
        return

    await update.message.reply_text(f"🔍 Fetching status for PNR {pnr}...")

    data = fetch_pnr_status(pnr)
    if not data:
        await update.message.reply_text(
            "❌ Could not fetch PNR status.\n"
            "Please check:\n"
            "• PNR number is correct\n"
            "• Your RapidAPI subscription is active\n"
            "• Check terminal for DEBUG output"
        )
        return

    if chat_id not in tracked_pnrs:
        tracked_pnrs[chat_id] = {}

    tracked_pnrs[chat_id][pnr] = fingerprint(data)
    save_data(tracked_pnrs)

    await update.message.reply_text(
        "✅ *Tracking started!*\n\n" + format_message(pnr, data),
        parse_mode="Markdown"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /status <PNR>\nExample: /status 4334410565")
        return

    pnr = context.args[0].strip()

    if len(pnr) != 10 or not pnr.isdigit():
        await update.message.reply_text("❌ PNR must be exactly 10 digits.")
        return

    await update.message.reply_text(f"🔍 Fetching status for PNR {pnr}...")

    data = fetch_pnr_status(pnr)
    if not data:
        await update.message.reply_text(
            "❌ Could not fetch PNR status.\n"
            "Check terminal for DEBUG output."
        )
        return

    await update.message.reply_text(format_message(pnr, data), parse_mode="Markdown")


async def untrack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text("Usage: /untrack <PNR>")
        return

    pnr = context.args[0].strip()

    if chat_id in tracked_pnrs and pnr in tracked_pnrs[chat_id]:
        del tracked_pnrs[chat_id][pnr]
        save_data(tracked_pnrs)
        await update.message.reply_text(f"✅ Stopped tracking PNR {pnr}")
    else:
        await update.message.reply_text(f"❌ PNR {pnr} is not being tracked.")


async def list_pnrs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    if chat_id not in tracked_pnrs or not tracked_pnrs[chat_id]:
        await update.message.reply_text("📋 You have no PNRs being tracked.\nUse /track <PNR> to start.")
        return

    msg = "📋 *Your tracked PNRs:*\n\n"
    for pnr in tracked_pnrs[chat_id]:
        msg += f"• `{pnr}`\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


# 🔔 Background checker
async def check_updates(app):
    logger.info("🔄 Running scheduled PNR check...")
    for chat_id, pnrs in list(tracked_pnrs.items()):
        for pnr, old_fp in list(pnrs.items()):
            data = fetch_pnr_status(pnr)
            if not data:
                continue

            new_fp = fingerprint(data)

            if new_fp != old_fp:
                tracked_pnrs[chat_id][pnr] = new_fp
                save_data(tracked_pnrs)

                try:
                    await app.bot.send_message(
                        chat_id=int(chat_id),
                        text="🔔 *STATUS UPDATE!*\n\n" + format_message(pnr, data),
                        parse_mode="Markdown"
                    )
                    logger.info(f"✅ Sent update for PNR {pnr} to {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send update to {chat_id}: {e}")


# 🚀 MAIN
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("track", track))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("untrack", untrack))
    app.add_handler(CommandHandler("list", list_pnrs))

    scheduler = AsyncIOScheduler()

    async def start_scheduler(app):
        scheduler.add_job(
            check_updates,
            "interval",
            minutes=CHECK_INTERVAL_MINUTES,
            args=[app]
        )
        scheduler.start()
        logger.info(f"✅ Scheduler started — checking every {CHECK_INTERVAL_MINUTES} mins")

    app.post_init = start_scheduler

    print("✅ Bot running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()