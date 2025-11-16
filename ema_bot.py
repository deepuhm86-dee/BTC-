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
    df = pd.DataFrame(closes, columns=["close"])
    return df.ewm(span=period, adjust=False).mean().iloc[-2][0]

# === Synthetic 45m candles ===
def get_synthetic_45m_series():
    raw = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_15MINUTE, limit=200)
    df = pd.DataFrame(raw, columns=[
        'ts','open','high','low','close','vol',
        'ct','qav','nt','tb','tq','ignore'
    ])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    df[['open','high','low','close']] = df[['open','high','low','close']].astype(float)

    # group every 3×15m = 45m
    grouped = df.groupby(df.index // 3).agg({
        'ts':'first',
        'open':'first',
        'high':'max',
        'low':'min',
        'close':'last'
    }).reset_index(drop=True)

    return grouped

# === SIGNAL CHECK ===
def check_signal(label, candle, ema):
    low = candle['low']
    high = candle['high']
    candle_time = candle['ts']
    print(f"[{datetime.now()}] [{label}] H:{high} L:{low} EMA5:{ema:.2f}")

    # SELL
    if low > ema and candle_time != last_signal_times.get(f"{label}_SELL"):
        message = (
            f"🚀 SELL Signal\n\nTIME FRAME - {label}\n"
            f"Candle Time: {candle_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Low: {low}\nEMA5: {ema:.2f}"
        )
        print(f"✅ SELL Signal detected on {label}")
        if not DEBUG_MODE:
            send_telegram_message(message)
        last_signal_times[f"{label}_SELL"] = candle_time

    # BUY
    elif high < ema and candle_time != last_signal_times.get(f"{label}_BUY"):
        message = (
            f"🟢 BUY Signal\n\nTIME FRAME - {label}\n"
            f"Candle Time: {candle_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"High: {high}\nEMA5: {ema:.2f}"
        )
        print(f"✅ BUY Signal detected on {label}")
        if not DEBUG_MODE:
            send_telegram_message(message)
        last_signal_times[f"{label}_BUY"] = candle_time

    else:
        print(f"❌ No signal on {label}")

# === Round scheduling ===
def round_next(now, minutes):
    """Round current time up to nearest multiple of `minutes`."""
    discard = timedelta(minutes=now.minute % minutes,
                        seconds=now.second,
                        microseconds=now.microsecond)
    return now - discard + timedelta(minutes=minutes)

# === MAIN LOOP ===
if __name__ == "__main__":
    print("🚀 Bot started — monitoring BTCUSDT on 45m, 1h, and 4h...")

    next_45m = round_next(datetime.now(), 45)
    next_1h = round_next(datetime.now(), 60)
    next_4h = round_next(datetime.now(), 240)

    while True:
        now = datetime.now()

        # --- 45m synthetic ---
        if now >= next_45m:
            try:
                df45 = get_synthetic_45m_series()
                latest45 = df45.iloc[-2]  # last closed synthetic candle
                closes45 = df45['close'].tolist()
                ema45 = get_ema(closes45)
                check_signal("45 MIN", latest45, ema45)
            except Exception as e:
                print("⚠️ 45m error:", e)
            next_45m = round_next(now, 45)

        # --- 1h ---
        if now >= next_1h:
            try:
                candles1h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
                latest1h = candles1h[-2]
                candle = {
                    'ts': datetime.fromtimestamp(latest1h[0]/1000),
                    'high': float(latest1h[2]),
                    'low': float(latest1h[3])
                }
                closes1h = [float(c[4]) for c in candles1h]
                ema1h = get_ema(closes1h)
                check_signal("1 HOUR", candle, ema1h)
            except Exception as e:
                print("⚠️ 1h error:", e)
            next_1h = round_next(now, 60)

        # --- 4h ---
        if now >= next_4h:
            try:
                candles4h = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_4HOUR, limit=50)
                latest4h = candles4h[-2]
                candle = {
                    'ts': datetime.fromtimestamp(latest4h[0]/1000),
                    'high': float(latest4h[2]),
                    'low': float(latest4h[3])
                }
                closes4h = [float(c[4]) for c in candles4h]
                ema4h = get_ema(closes4h)
                check_signal("4 HOUR", candle, ema4h)
            except Exception as e:
                print("⚠️ 4h error:", e)
            next_4h = round_next(now, 240)

        time.sleep(30)
