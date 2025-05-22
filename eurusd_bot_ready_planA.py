import logging
import asyncio
import yfinance as yf
import pandas as pd
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import Message
from datetime import datetime, timedelta

# ========== CONFIG ==========
TELEGRAM_BOT_TOKEN = "7923000946:AAEx8TZsaIl6GL7XUwPGEM6a6-mBNfKwUz8"
TELEGRAM_USER_ID = 7469299312
PAIRS = ["EURUSD=X", "USDCHF=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]
INTERVAL = "5m"
PERIOD = "2d"
CHECK_EVERY_SECONDS = 300
WARNING_THRESHOLD_MINUTES = 10
# ============================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

last_activity_time = datetime.utcnow()

def fetch_data(pair):
    data = yf.download(pair, period=PERIOD, interval=INTERVAL)
    if data.empty or "Close" not in data:
        raise ValueError(f"No data for {pair}")
    close = data["Close"]

    data["EMA20"] = close.ewm(span=20, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    data["RSI"] = 100 - (100 / (1 + rs))
    std = close.rolling(window=20).std()
    data["UpperBB"] = data["EMA20"] + 2 * std
    data["LowerBB"] = data["EMA20"] - 2 * std

    macd_fast = close.ewm(span=12, adjust=False).mean()
    macd_slow = close.ewm(span=26, adjust=False).mean()
    data["MACD"] = macd_fast - macd_slow
    data["Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()

    data.dropna(inplace=True)
    return data

def evaluate_strategies(df):
    last = df.iloc[-1]
    signals = []

    if last["Close"] > last["EMA20"] and last["RSI"] < 30:
        signals.append("RSI & EMA Buy")
    if last["Close"] < last["EMA20"] and last["RSI"] > 70:
        signals.append("RSI & EMA Sell")

    if last["MACD"] > last["Signal"]:
        signals.append("MACD Buy")
    if last["MACD"] < last["Signal"]:
        signals.append("MACD Sell")

    if last["Close"] < last["LowerBB"]:
        signals.append("Bollinger Buy")
    if last["Close"] > last["UpperBB"]:
        signals.append("Bollinger Sell")

    return signals, round(last["Close"], 5)

async def send_signal(pair):
    global last_activity_time
    try:
        df = fetch_data(pair)
        signals, price = evaluate_strategies(df)

        signal_type = None
        if len([s for s in signals if "Buy" in s]) >= 2:
            signal_type = "Buy"
        elif len([s for s in signals if "Sell" in s]) >= 2:
            signal_type = "Sell"

        if signal_type:
            agreed = len([s for s in signals if signal_type in s])
            tp1 = round(price + 0.0020, 5) if signal_type == "Buy" else round(price - 0.0020, 5)
            tp2 = round(price + 0.0040, 5) if signal_type == "Buy" else round(price - 0.0040, 5)
            tp3 = round(price + 0.0060, 5) if signal_type == "Buy" else round(price - 0.0060, 5)
            sl = round(price - 0.0020, 5) if signal_type == "Buy" else round(price + 0.0020, 5)

            message = (
                f"📊 <b>{pair.replace('=X', '')} Signal</b>\n"
                f"<b>Type:</b> {signal_type}\n"
                f"<b>Entry:</b> {price}\n"
                f"<b>TP1:</b> {tp1}\n"
                f"<b>TP2:</b> {tp2}\n"
                f"<b>TP3:</b> {tp3}\n"
                f"<b>SL:</b> {sl}\n"
                f"<b>Agreed Strategies:</b> {agreed}/4"
            )
            await bot.send_message(chat_id=TELEGRAM_USER_ID, text=message)

        last_activity_time = datetime.utcnow()

    except Exception as e:
        logging.error(f"Error for {pair}: {e}")

async def check_loop():
    while True:
        for pair in PAIRS:
            await send_signal(pair)
        await asyncio.sleep(CHECK_EVERY_SECONDS)

async def monitor_loop():
    global last_activity_time
    while True:
        now = datetime.utcnow()
        if now - last_activity_time > timedelta(minutes=WARNING_THRESHOLD_MINUTES):
            await bot.send_message(chat_id=TELEGRAM_USER_ID, text="⚠️ Warning: Bot seems to be stuck or delayed!")
        await asyncio.sleep(60)

@dp.message(Command("status"))
async def handle_status(message: Message):
    if message.from_user.id == TELEGRAM_USER_ID:
        await message.answer("✅ Bot is still running and monitoring the market.")

async def main():
    asyncio.create_task(check_loop())
    asyncio.create_task(monitor_loop())
    logging.info("✅ Bot and web server fully started.")
    # keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot, startup=main))

