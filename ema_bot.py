import os
import sys
import time
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd
from binance.client import Client

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"

client = Client()
last_signal_times = {}

# === LOGGING ===
def log(msg):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {msg}", flush=True)

def warn(msg):
    log(f"⚠️ {msg}")

def fail(msg):
    log(f"ERROR: {msg}")
    sys.exit(1)

def assert_env():
    missing = []
    if not TELEGRAM_TOKEN: missing.append("TELEGRAM_TOKEN")
    if not TELEGRAM_CHAT_ID: missing.append("TELEGRAM_CHAT_ID")
    if missing:
        warn(f"Missing env vars: {', '.join(missing)} (Telegram sending will fail)")
    log(f"ENV | SYMBOL={SYMBOL} DEBUG_MODE={DEBUG_MODE}")

# === TELEGRAM ALERT ===
def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        warn("Telegram vars missing; skipping send")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            log("Telegram sent")
        else:
            warn(f"Telegram error ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        warn(f"Telegram exception: {e}")

# === EMA CALCULATION (aligned to last closed) ===
def ema_last_closed(closes, period=5):
    if len(closes) < period + 1:
        return None
    df = pd.DataFrame(closes, columns=["close"])
    ema_series = df["close"].ewm(span=period, adjust=False).mean()
    # use second-last for closed candle alignment
    return float(ema_series.iloc[-2])

# === Binance fetch helpers ===
def fetch_klines(interval, limit=200):
    try:
        data = client.get_klines(symbol=SYMBOL, interval=interval, limit=limit)
        if not data or len(data) == 0:
            warn(f"No klines for interval {interval}")
            return None
        return data
    except Exception as e:
        warn(f"Binance get_klines error ({interval}): {e}")
        return None

# === Synthetic 45m aggregation (3×15m) ===
def get_synthetic_45m_df():
    raw = fetch_klines(Client.KLINE_INTERVAL_15MINUTE, limit=240)
    if raw is None:
        return None
    df = pd.DataFrame(raw, columns=[
        'ts','open','high','low','close','vol',
        'ct','qav','nt','tb','tq','ignore'
    ])
    # convert types
    df['ts'] = pd.to_datetime(df['ts'], unit='ms')
    for col in ['open','high','low','close']:
        df[col] = df[col].astype(float)

    # Ensure we only use closed candles (exclude the last if still open)
    # Binance returns open time in 'ts' and close time in 'ct'; we take up to -1 safely
    if len(df) < 6:  # need at least 6×15m to produce 2×45m closed
        warn("Too few 15m candles to synthesize 45m")
        return None

    # Group 3 consecutive 15m into 45m; use integer index to avoid time gaps
    df = df.reset_index(drop=True)
    grouped = df.groupby(df.index // 3).agg({
        'ts':'first',
        'open':'first',
        'high':'max',
        'low':'min',
        'close':'last'
    }).reset_index(drop=True)

    if len(grouped) < 2:
        warn("Not enough 45m synthetic candles (need at least 2 closed)")
        return None

    return grouped

# === Signal evaluation ===
def check_signal(label, candle, ema):
    if ema is None:
        warn(f"{label}: EMA unavailable (series too short)")
        return

    low = float(candle['low'])
    high = float(candle['high'])
    ts = candle['ts']  # pandas Timestamp
    log(f"{label} | H:{high:.2f} L:{low:.2f} EMA5:{ema:.2f}")

    # SELL: low > ema (no-touch from below), dedupe by timestamp
    if low > ema and last_signal_times.get(f"{label}_SELL") != ts:
        msg = (
            f"🚀 SELL Signal\n\nTIME FRAME: {label}\n"
            f"Candle Time: {ts.strftime('%Y-%m-%d %H:%M')}\n"
            f"Low: {low:.2f}\nEMA5: {ema:.2f}"
        )
        log(f"{label}: SELL detected")
        if not DEBUG_MODE:
            send_telegram_message(msg)
        last_signal_times[f"{label}_SELL"] = ts
        return

    # BUY: high < ema (no-touch from above)
    if high < ema and last_signal_times.get(f"{label}_BUY") != ts:
        msg = (
            f"🟢 BUY Signal\n\nTIME FRAME: {label}\n"
            f"Candle Time: {ts.strftime('%Y-%m-%d %H:%M')}\n"
            f"High: {high:.2f}\nEMA5: {ema:.2f}"
        )
        log(f"{label}: BUY detected")
        if not DEBUG_MODE:
            send_telegram_message(msg)
        last_signal_times[f"{label}_BUY"] = ts
        return

    log(f"{label}: No signal")

# === Precise scheduling (round up to nearest multiple) ===
def round_next(now, minutes):
    discard = timedelta(minutes=now.minute % minutes,
                        seconds=now.second,
                        microseconds=now.microsecond)
    return now - discard + timedelta(minutes=minutes)

# === MAIN LOOP ===
if __name__ == "__main__":
    log("Bot start — monitoring BTCUSDT on 45m (synthetic), 1h, 4h")
    assert_env()

    next_45m = round_next(datetime.now(), 45)
    next_1h = round_next(datetime.now(), 60)
    next_4h = round_next(datetime.now(), 240)

    while True:
        now = datetime.now()
        # --- 45m synthetic ---
        if now >= next_45m:
            try:
                df45 = get_synthetic_45m_df()
                if df45 is not None:
                    latest45 = df45.iloc[-2]  # last CLOSED synthetic candle
                    closes45 = df45['close'].tolist()
                    ema45 = ema_last_closed(closes45, period=5)
                    check_signal("45 MIN", latest45, ema45)
            except Exception as e:
                warn(f"45m block error: {e}")
            next_45m = round_next(now, 45)

        # --- 1h ---
        if now >= next_1h:
            try:
                data1h = fetch_klines(Client.KLINE_INTERVAL_1HOUR, limit=60)
                if data1h:
                    latest1h = data1h[-2]  # closed candle
                    ts = datetime.fromtimestamp(latest1h[0]/1000)
                    candle1h = {'ts': ts, 'high': float(latest1h[2]), 'low': float(latest1h[3])}
                    closes1h = [float(c[4]) for c in data1h]
                    ema1h = ema_last_closed(closes1h, period=5)
                    check_signal("1 HOUR", candle1h, ema1h)
            except Exception as e:
                warn(f"1h block error: {e}")
            next_1h = round_next(now, 60)

        # --- 4h ---
        if now >= next_4h:
            try:
                data4h = fetch_klines(Client.KLINE_INTERVAL_4HOUR, limit=60)
                if data4h:
                    latest4h = data4h[-2]  # closed candle
                    ts = datetime.fromtimestamp(latest4h[0]/1000)
                    candle4h = {'ts': ts, 'high': float(latest4h[2]), 'low': float(latest4h[3])}
                    closes4h = [float(c[4]) for c in data4h]
                    ema4h = ema_last_closed(closes4h, period=5)
                    check_signal("4 HOUR", candle4h, ema4h)
            except Exception as e:
                warn(f"4h block error: {e}")
            next_4h = round_next(now, 240)

        time.sleep(30)

      
