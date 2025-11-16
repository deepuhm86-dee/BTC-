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
    ema = df["close"].ewm(span=period, adjust=False).mean().iloc[-2]
    return float(ema)

# === SIGNAL CHECK ===
def check_signal(label, high, low, candle_time, ema):
    print(f"[{datetime.now()}] [{label}] H:{high:.2f} L:{low:.2f} EMA5:{ema:.2f}")

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

# === SYNTHETIC 45m CANDLE ===
def get_synthetic_45m():
    candles_15m = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_15MINUTE, limit=6)
    if len(candles_15m) < 4:
        print("⚠️ Not enough 15m candles for 45m synthesis")
        return None, None, None, None

    batch = candles_15m[-4:-1]  # last 3 closed 15m candles
    open_price = float(batch[0][1])
    high_price = max(float(c[2]) for c in batch)
    low_price = min(float(c[3]) for c in batch)
    close_price = float(batch[-1][4])
    candle_time = datetime.fromtimestamp(batch[0][0] / 1000)

    closes = [float(c[4]) for c in candles_15m]
    ema = get_ema(candles_15m)

    return high_price, low_price, candle_time, ema

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🚀 Bot started — monitoring BTCUSDT on 45m (synthetic), 1h, and 4h...")

    next_45m = datetime.now()
    next_1h = datetime.now()
    next_4h = datetime.now()

    while True:
        now = datetime.now()

        # --- 45m synthetic ---
        if now >= next_45m:
            try:
                high, low, candle_time, ema = get_synthetic_45m()
                if ema:
                    check_signal("45 MIN", high, low, candle_time, ema)
            except Exception as e:
                print("⚠️ 45m error:", e)
            next_45m += timedelta(minutes=45)

        # --- 1h native ---
        if now >= next_1h:
            try:
                candles_1h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
                latest = candles_1h[-2]
                high = float(latest[2])
                low = float(latest[3])
                candle_time = datetime.fromtimestamp(latest[0] / 1000)
                ema = get_ema(candles_1h)
                if ema:
                    check_signal("1 HOUR", high, low, candle_time, ema)
            except Exception as e:
                print("⚠️ 1h error:", e)
            next_1h += timedelta(hours=1)

        # --- 4h native ---
        if now >= next_4h:
            try:
                candles_4h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_4HOUR, limit=50)
                latest = candles_4h[-2]
                high = float(latest[2])
                low = float(latest[3])
                candle_time = datetime.fromtimestamp(latest[0] / 1000)
                ema = get_ema(candles_4h)
                if ema:
                    check_signal("4 HOUR", high, low, candle_time, ema)
            except Exception as e:
                print("⚠️ 4h error:", e)
            next_4h += timedelta(hours=4)

        time.sleep(30)
