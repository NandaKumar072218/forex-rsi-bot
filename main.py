import os
import time
import asyncio
import httpx
import csv
from datetime import datetime
import pytz

# ================================
# ENV CONFIG
# ================================

API_KEY = os.getenv("TWELVEDATA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = os.getenv("SYMBOLS", "XAUUSD").split(",")
TIMEFRAMES = os.getenv("TIMEFRAMES", "5min,15min").split(",")

RSI_UPPER = float(os.getenv("RSI_UPPER", 60))
RSI_LOWER = float(os.getenv("RSI_LOWER", 40))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

IST = pytz.timezone("Asia/Kolkata")

# ================================
# GLOBAL STATE
# ================================

last_alert_state = {}
telegram_cache = {}

# ================================
# HTTP CLIENT (REUSE CONNECTION)
# ================================

client = httpx.AsyncClient(timeout=10)

# ================================
# TELEGRAM SAFE SEND
# ================================

async def send_telegram(message, cooldown=30):
    try:
        now = time.time()

        if message in telegram_cache:
            if now - telegram_cache[message] < cooldown:
                return

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        await client.post(
            url,
            json={"chat_id": CHAT_ID, "text": message}
        )

        telegram_cache[message] = now

    except Exception:
        pass

# ================================
# CSV LOGGER
# ================================

def log_csv(symbol, timeframe, rsi, price, direction):

    try:
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

        filename = f"{symbol}_{datetime.now(IST).date()}.csv"

        file_exists = os.path.isfile(filename)

        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)

            if not file_exists:
                writer.writerow(
                    ["DateTime", "Symbol", "Timeframe", "RSI", "Price", "Direction"]
                )

            writer.writerow([now, symbol, timeframe, rsi, price, direction])

    except Exception:
        pass

# ================================
# FETCH RSI + PRICE
# ================================

async def fetch_rsi_price(symbol, timeframe):

    try:
        rsi_url = "https://api.twelvedata.com/rsi"

        params = {
            "symbol": symbol,
            "interval": timeframe,
            "time_period": 14,
            "series_type": "close",
            "apikey": API_KEY
        }

        r = await client.get(rsi_url, params=params)
        data = r.json()

        if "values" not in data:
            return None, None

        rsi = float(data["values"][0]["rsi"])

        price_url = "https://api.twelvedata.com/price"

        price_res = await client.get(
            price_url,
            params={"symbol": symbol, "apikey": API_KEY}
        )

        price = float(price_res.json()["price"])

        return rsi, price

    except Exception:
        return None, None

# ================================
# MAIN BOT LOOP
# ================================

async def bot_loop():

    print("🚀 Production Trading Bot Started")

    while True:

        try:
            now = datetime.now(IST)
            minute = now.minute

            for timeframe in TIMEFRAMES:

                # Candle close trigger
                if timeframe == "5min" and minute % 5 != 0:
                    continue

                if timeframe == "15min" and minute % 15 != 0:
                    continue

                for symbol in SYMBOLS:

                    rsi, price = await fetch_rsi_price(symbol, timeframe)

                    if rsi is None:
                        continue

                    key = f"{symbol}_{timeframe}"

                    prev_state = last_alert_state.get(key, "neutral")

                    # ABOVE ALERT
                    if rsi > RSI_UPPER and prev_state != "above":

                        msg = f"📈 {symbol} RSI ABOVE {RSI_UPPER}\nRSI: {rsi}\nPrice: {price}"

                        await send_telegram(msg)

                        log_csv(symbol, timeframe, rsi, price, "ABOVE")

                        last_alert_state[key] = "above"

                    # BELOW ALERT
                    elif rsi < RSI_LOWER and prev_state != "below":

                        msg = f"📉 {symbol} RSI BELOW {RSI_LOWER}\nRSI: {rsi}\nPrice: {price}"

                        await send_telegram(msg)

                        log_csv(symbol, timeframe, rsi, price, "BELOW")

                        last_alert_state[key] = "below"

                    else:
                        last_alert_state[key] = "neutral"

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception:
            await asyncio.sleep(5)

# ================================
# ENTRY POINT
# ================================

if __name__ == "__main__":
    asyncio.run(bot_loop())
