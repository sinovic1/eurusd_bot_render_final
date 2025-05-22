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
WARNING_THRESHOLD_MINUTES = 10
# ============================

bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

last_activity_time = datetime.utcnow()

def fetch_data(pair):
    data = yf.download(pair, period=PERIOD, interval=INTERVAL, auto_adjust=True)
    if data.empty:
        raise ValueError(f"❌ No data for {pair}")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [col[0] for col in data.columns]

    close = data["Close"]
    data["EMA20"] = close.ewm(span=20, adjust=False).mean()
    data["EMA50"] = close.ewm(span=50, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    data["RSI"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()

    # Bollinger Bands
    sma = close.rolling(window=20).mean()
    std = close.rolling(window=20).std()
    data["Upper"] = sma + (std * 2)
    data["Lower"] = sma - (std * 2)

    data = data.tail(100).dropna()
    return data

def generate_signal(df):
    last = df.iloc[-1]
    entry = round(last["Close"], 5)
    tp1 = round(entry + 0.0015, 5) if entry else None
    tp2 = round(entry + 0.0030, 5) if entry else None
    tp3 = round(entry + 0.0045, 5) if entry else None
    sl = round(entry - 0.0020, 5) if entry else None

    confirmations = []

    # Strategies
    if last["Close"] > last["EMA20"]:
        confirmations.append("EMA20")
    if last["RSI"] < 30:
        confirmations.append("RSI")
    if last["MACD"] > last["Signal"]:
        confirmations.append("MACD")
    if last["Close"] < last["Lower"]:
        confirmations.append("Bollinger")

    if len(confirmations) >= 2:
        return "Buy", entry, [tp1, tp2, tp3], sl, confirmations
    elif last["Close"] < last["EMA20"] and last["RSI"] > 70 and last["MACD"] < last["Signal"] and last["Close"] > last["Upper"]:
        tp1 = round(entry - 0.0015, 5)
        tp2 = round(entry - 0.0030, 5)
        tp3 = round(entry - 0.0045, 5)
        sl = round(entry + 0.0020, 5)
        return "Sell", entry, [tp1, tp2, tp3], sl, ["EMA20", "RSI", "MACD", "Bollinger"]
    return None, None, None, None, []

async def check_signals():
    global last_activity_time
    for pair in PAIRS:
        try:
            df = fetch_data(pair)
            strategy, entry, tps, sl, confirmed = generate_signal(df)
            if strategy:
                message = (
                    f"📊 <b>{pair.replace('=X', '')} Signal</b>\n"
                    f"🕒 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"📈 <b>Type:</b> {strategy}\n"
                    f"💵 <b>Entry:</b> {entry}\n"
                    f"🎯 <b>Take Profits:</b> {tps[0]}, {tps[1]}, {tps[2]}\n"
                    f"🛑 <b>Stop Loss:</b> {sl}\n"
                    f"✅ <b>Confirmed by:</b> {', '.join(confirmed)}"
                )
                await bot.send_message(chat_id=TELEGRAM_USER_ID, text=message)
                last_activity_time = datetime.utcnow()
            else:
                logging.info(f"No valid signal for {pair} at this moment.")
        except Exception as e:
            logging.error(f"❌ Error checking {pair}: {e}")

async def monitor_loop():
    global last_activity_time
    while True:
        await asyncio.sleep(WARNING_THRESHOLD_MINUTES * 60)
        now = datetime.utcnow()
        if now - last_activity_time > timedelta(minutes=WARNING_THRESHOLD_MINUTES + 1):
            await bot.send_message(TELEGRAM_USER_ID, "⚠️ Warning: No signal activity detected in the last 10+ minutes.")
            last_activity_time = now

@dp.message(Command(commands=["status"]))
async def status_handler(message: Message):
    await message.answer("✅ Bot is running and monitoring all pairs.")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(monitor_loop())
    while True:
        await check_signals()
        await asyncio.sleep(300)  # every 5 minutes

if __name__ == "__main__":
    dp.startup.register(lambda _: logging.info("✅ Bot and web server started."))
    asyncio.run(dp.start_polling(bot, main()))

