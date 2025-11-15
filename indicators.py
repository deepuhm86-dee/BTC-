def get_ema(candles, period=5):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for price in closes[1:]:
        ema = price * k + ema * (1 - k)
    return ema
