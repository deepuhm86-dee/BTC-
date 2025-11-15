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
def get_ema(closes, period=5):
    df = pd.DataFrame(closes)
    return df.ewm(span=period, adjust=False).mean().iloc[-1][0]

# === SYNTHETIC 45m CANDLE ===
def get_synthetic_45m_candle():
    candles = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_15MINUTE, limit=4)
    batch = candles[-4:-1]  # last 3 closed 15m candles
    open_price = float(batch[0][1])
    high_price = max(float(c[2]) for c in batch)
    low_price = min(float(c[3]) for c in batch)
    close_price = float(batch[-1][4])
    timestamp = batch[0][0]
    return [timestamp, open_price, high_price, low_price, close_price]

# === SIGNAL CHECK ===
def check_signal(label, candles, close, ema, candle_time):
    print(f"[{datetime.now()}] [{label}] Close:{close} EMA5:{ema:.2f}")
    if close > ema and candle_time != last_signal_times.get(label):
        message = (
            f"🚀 SELL Signal\n\n"
            f"TIME FRAME - {label}\n"
            f"Candle Time: {candle_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Close: {close}\nEMA5: {ema:.2f}"
        )
        print(f"✅ Signal detected on {label}")
        if not DEBUG_MODE:
            send_telegram_message(message)
        last_signal_times[label] = candle_time
    else:
        print(f"❌ No signal on {label}")

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🚀 Bot started — monitoring BTCUSDT on 45m, 1h, and 4h...")

    while True:
        # --- 45m synthetic ---
        candle_45m = get_synthetic_45m_candle()
        close_45m = candle_45m[4]
        closes_45m = [close_45m]  # build rolling list if needed
        ema_45m = get_ema(closes_45m)
        time_45m = datetime.fromtimestamp(candle_45m[0] / 1000)
        check_signal("45 MIN", closes_45m, close_45m, ema_45m, time_45m)

        # --- 1h ---
        candles_1h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
        latest_1h = candles_1h[-2]
        close_1h = float(latest_1h[4])
        ema_1h = get_ema([float(c[4]) for c in candles_1h])
        time_1h = datetime.fromtimestamp(latest_1h[0] / 1000)
        check_signal("1 HOUR", candles_1h, close_1h, ema_1h, time_1h)

        # --- 4h ---
        candles_4h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_4HOUR, limit=50)
        latest_4h = candles_4h[-2]
        close_4h = float(latest_4h[4])
        ema_4h = get_ema([float(c[4]) for c in candles_4h])
        time_4h = datetime.fromtimestamp(latest_4h[0] / 1000)
        check_signal("4 HOUR", candles_4h, close_4h, ema_4h, time_4h)

        time.sleep(60)  # poll every minute
