import requests
import pandas as pd
import time
import os
from datetime import datetime
import pytz
import csv

# =========================
# ENV CONFIG
# =========================

API_KEY = os.getenv("TWELVEDATA_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = os.getenv("SYMBOLS", "XAUUSD").split(",")
TIMEFRAMES = os.getenv("TIMEFRAMES", "5min,15min").split(",")

RSI_UPPER = float(os.getenv("RSI_UPPER", 60))
RSI_LOWER = float(os.getenv("RSI_LOWER", 40))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
FAILURE_LIMIT = int(os.getenv("FAILURE_LIMIT", 5))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", 120))

IST = pytz.timezone("Asia/Kolkata")

# =========================
# STATE TRACKERS
# =========================

api_calls_today = 0
failure_count = 0
last_alert_state = {}  # track last RSI state per symbol/timeframe


# =========================
# TELEGRAM FUNCTION
# =========================

def send_telegram(message):
    global failure_count
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message}
        requests.post(url, data=payload)
    except Exception:
        failure_count += 1


# =========================
# LOG TO CSV
# =========================

def log_to_csv(symbol, timeframe, rsi_value, price, direction):
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    filename = f"{symbol}_{datetime.now(IST).date()}.csv"

    file_exists = os.path.isfile(filename)

    with open(filename, mode="a", newline="") as file:
        writer = csv.writer(file)

        if not file_exists:
            writer.writerow(["DateTime_IST", "Symbol", "Timeframe", "RSI", "Price", "Direction"])

        writer.writerow([now, symbol, timeframe, rsi_value, price, direction])


# =========================
# FETCH RSI
# =========================

def fetch_rsi(symbol, timeframe):
    global api_calls_today, failure_count

    try:
        url = "https://api.twelvedata.com/rsi"
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "time_period": 14,
            "series_type": "close",
            "apikey": API_KEY
        }

        response = requests.get(url, params=params)
        api_calls_today += 1

        data = response.json()

        if "values" not in data:
            failure_count += 1
            return None, None

        rsi_value = float(data["values"][0]["rsi"])

        # Fetch price
        price_url = "https://api.twelvedata.com/price"
        price_params = {"symbol": symbol, "apikey": API_KEY}
        price_response = requests.get(price_url, params=price_params)
        price = float(price_response.json()["price"])

        return rsi_value, price

    except Exception:
        failure_count += 1
        return None, None


# =========================
# CIRCUIT BREAKER
# =========================

def check_circuit_breaker():
    global failure_count

    if failure_count >= FAILURE_LIMIT:
        print("⚠️ Too many failures. Cooling down...")
        time.sleep(COOLDOWN_SECONDS)
        failure_count = 0


# =========================
# MAIN LOOP
# =========================

def main():
    global last_alert_state

    print("🚀 RSI Alert Bot Started")

    while True:
        now = datetime.now(IST)
        minute = now.minute

        for timeframe in TIMEFRAMES:

            # Only run on candle close
            if timeframe == "5min" and minute % 5 != 0:
                continue
            if timeframe == "15min" and minute % 15 != 0:
                continue

            for symbol in SYMBOLS:

                rsi, price = fetch_rsi(symbol, timeframe)

                if rsi is None:
                    continue

                key = f"{symbol}_{timeframe}"

                previous_state = last_alert_state.get(key, "neutral")

                if rsi > RSI_UPPER and previous_state != "above":
                    message = f"📈 {symbol} RSI crossed ABOVE {RSI_UPPER} on {timeframe}\nRSI: {rsi}\nPrice: {price}"
                    send_telegram(message)
                    log_to_csv(symbol, timeframe, rsi, price, "ABOVE")
                    last_alert_state[key] = "above"

                elif rsi < RSI_LOWER and previous_state != "below":
                    message = f"📉 {symbol} RSI crossed BELOW {RSI_LOWER} on {timeframe}\nRSI: {rsi}\nPrice: {price}"
                    send_telegram(message)
                    log_to_csv(symbol, timeframe, rsi, price, "BELOW")
                    last_alert_state[key] = "below"

                elif RSI_LOWER <= rsi <= RSI_UPPER:
                    last_alert_state[key] = "neutral"

        check_circuit_breaker()
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()