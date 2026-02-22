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

SYMBOLS = os.getenv("SYMBOLS").split(",")
TIMEFRAMES = os.getenv("TIMEFRAMES", "5min,15min").split(",")

RSI_PERIOD = 14
RSI_UPPER = float(os.getenv("RSI_UPPER", 60))
RSI_LOWER = float(os.getenv("RSI_LOWER", 40))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))

IST = pytz.timezone("Asia/Kolkata")

# ================================
# GLOBAL STATE
# ================================

last_alert_state = {}
telegram_cache = {}
api_rate_remaining = "N/A"
rate_limit_warning_sent = False

client = httpx.AsyncClient(timeout=15)

# ================================
# RSI CALCULATION (Wilder Method)
# ================================

def calculate_rsi(closes, period=14):

    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change >= 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        gain = max(change, 0)
        loss = max(-change, 0)

        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)

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

    except Exception as e:
        print("Telegram Error:", e)

# ================================
# CSV LOGGER
# ================================

def log_csv(symbol, timeframe, rsi, price, direction):
    try:
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        safe_symbol = symbol.replace("/", "_").replace(":", "_")
        filename = f"{safe_symbol}_{datetime.now(IST).date()}.csv"
        file_exists = os.path.isfile(filename)

        with open(filename, "a", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(
                    ["DateTime", "Symbol", "Timeframe", "RSI", "Price", "Direction"]
                )
            writer.writerow([now, symbol, timeframe, rsi, price, direction])

    except Exception as e:
        print("CSV Error:", e)

# ================================
# FETCH TIME SERIES ONCE
# ================================

async def fetch_data(symbol, timeframe):

    global api_rate_remaining

    try:
        url = "https://api.twelvedata.com/time_series"

        params = {
            "symbol": symbol,
            "interval": timeframe,
            "outputsize": 100,
            "apikey": API_KEY
        }

        r = await client.get(url, params=params)

        api_rate_remaining = r.headers.get("X-RateLimit-Remaining", "N/A")

        data = r.json()

        if "values" not in data:
            print("TimeSeries Error:", data)
            return None, None

        closes = [float(x["close"]) for x in reversed(data["values"])]

        price = closes[-1]

        rsi = calculate_rsi(closes, RSI_PERIOD)

        return rsi, price

    except Exception as e:
        print("Fetch Error:", e)
        return None, None

# ================================
# MAIN LOOP
# ================================

async def bot_loop():

    global rate_limit_warning_sent

    print("🚀 Optimized Production RSI Bot Started")

    while True:
        try:
            now = datetime.now(IST)
            minute = now.minute

            for timeframe in TIMEFRAMES:

                if timeframe == "5min" and minute % 5 != 0:
                    continue

                if timeframe == "15min" and minute % 15 != 0:
                    continue

                for symbol in SYMBOLS:

                    rsi, price = await fetch_data(symbol, timeframe)

                    if rsi is None:
                        continue

                    key = f"{symbol}_{timeframe}"
                    prev_state = last_alert_state.get(key, "neutral")

                    # Rate Limit Warning
                    try:
                        remaining = int(api_rate_remaining)
                        if remaining < 20 and not rate_limit_warning_sent:
                            await send_telegram(
                                f"⚠️ API Remaining Low → {remaining}"
                            )
                            rate_limit_warning_sent = True
                    except:
                        pass

                    # ABOVE
                    if rsi > RSI_UPPER and prev_state != "above":

                        msg = (
                            f"📈 RSI ALERT (ABOVE)\n"
                            f"Symbol: {symbol}\n"
                            f"Timeframe: {timeframe}\n"
                            f"RSI: {rsi}\n"
                            f"Price: {price}\n"
                            f"API Remaining: {api_rate_remaining}"
                        )

                        await send_telegram(msg)
                        log_csv(symbol, timeframe, rsi, price, "ABOVE")

                        last_alert_state[key] = "above"

                    # BELOW
                    elif rsi < RSI_LOWER and prev_state != "below":

                        msg = (
                            f"📉 RSI ALERT (BELOW)\n"
                            f"Symbol: {symbol}\n"
                            f"Timeframe: {timeframe}\n"
                            f"RSI: {rsi}\n"
                            f"Price: {price}\n"
                            f"API Remaining: {api_rate_remaining}"
                        )

                        await send_telegram(msg)
                        log_csv(symbol, timeframe, rsi, price, "BELOW")

                        last_alert_state[key] = "below"

                    else:
                        last_alert_state[key] = "neutral"

            await asyncio.sleep(CHECK_INTERVAL)

        except Exception as e:
            print("Main Loop Error:", e)
            await asyncio.sleep(5)

# ================================
# ENTRY
# ================================

if __name__ == "__main__":
    asyncio.run(bot_loop())
