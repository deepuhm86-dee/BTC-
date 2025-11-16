import os
import requests
import time
from datetime import datetime, timedelta
from binance.client import Client
import pandas as pd

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = 'BTCUSDT'
DEBUG_MODE = False

client = Client()
last_signal_times = {}

# === TELEGRAM ALERT ===
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("📨 Telegram sent successfully")
        else:
            print(f"❌ Telegram error ({r.status_code}): {r.text}")
    except Exception as e:
        print("Telegram exception:", e)

# === EMA CALCULATION ===
def get_ema(candles, period=5):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period + 1:
        return None
    df = pd.DataFrame(closes, columns=["close"])
    return df.ewm(span=period, adjust=False).mean().iloc[-2][0]  # align with closed candle

# === SIGNAL CHECK ===
def check_signal(label, candles):
    latest = candles[-2]  # last closed candle
    high = float(latest[2])
    low = float(latest[3])
    candle_time = datetime.fromtimestamp(latest[0] / 1000)
    ema = get_ema(candles)

    print(f"[{datetime.now()}] [{label}] H:{high} L:{low} EMA5:{ema:.2f}")

    # SELL
    if low > ema and candle_time != last_signal_times.get(f"{label}_SELL"):
        message = (
            f"🚀 ABOVE 5 EMA SELL Signal\n\n"
            f"TIME FRAME - {label}\n"
            f"Candle Time: {candle_time.strftime('%Y-%m-%d %H:%M')}"
        )
        print(f"✅ SELL Signal detected on {label}")
        if not DEBUG_MODE:
            send_telegram_message(message)
        last_signal_times[f"{label}_SELL"] = candle_time

    # BUY
    elif high < ema and candle_time != last_signal_times.get(f"{label}_BUY"):
        message = (
            f"🟢 BELOW 5 EMA BUY Signal\n\n"
            f"TIME FRAME - {label}\n"
            f"Candle Time: {candle_time.strftime('%Y-%m-%d %H:%M')}"
        )
        print(f"✅ BUY Signal detected on {label}")
        if not DEBUG_MODE:
            send_telegram_message(message)
        last_signal_times[f"{label}_BUY"] = candle_time

    else:
        print(f"❌ No signal on {label}")

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🚀 Bot started — monitoring BTCUSDT on 45m, 1h, and 4h...")

    next_45m = datetime.now()
    next_1h = datetime.now()
    next_4h = datetime.now()

    while True:
        now = datetime.now()

        # --- 45m ---
        if now >= next_45m:
            try:
                candles_45m = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_45MINUTE, limit=50)
                check_signal("45 MIN", candles_45m)
            except Exception as e:
                print("⚠️ 45m error:", e)
            next_45m += timedelta(minutes=45)

        # --- 1h ---
        if now >= next_1h:
            try:
                candles_1h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
                check_signal("1 HOUR", candles_1h)
            except Exception as e:
                print("⚠️ 1h error:", e)
            next_1h += timedelta(hours=1)

        # --- 4h ---
        if now >= next_4h:
            try:
                candles_4h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_4HOUR, limit=50)
                check_signal("4 HOUR", candles_4h)
            except Exception as e:
                print("⚠️ 4h error:", e)
            next_4h += timedelta(hours=4)

        time.sleep(30)
