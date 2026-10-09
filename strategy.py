"""
Strategy rules (sirf CLOSED candles pe):
1. Trend: price > EMA50 > EMA200 => sirf LONG ; price < EMA50 < EMA200 => sirf SHORT
2. Entry: last closed candle ne EMA50 ko touch kiya (0.15% tolerance) aur trend side me band hui
   (long: bullish candle EMA50 ke upar close, short: bearish candle EMA50 ke neeche close)
3. SL: pichli 10 candles ka swing low (long) / swing high (short)
4. Target: SL distance ka 3x (1:3)
"""
import config


def ema(values: list, period: int) -> list:
    mult = 2 / (period + 1)
    out = [sum(values[:period]) / period]
    for v in values[period:]:
        out.append((v - out[-1]) * mult + out[-1])
    return out


def check_signal(candles: list):
    if len(candles) < config.EMA_SLOW + 5:
        return None

    closes = [c["close"] for c in candles]
    ema_fast = ema(closes, config.EMA_FAST)[-1]
    ema_slow = ema(closes, config.EMA_SLOW)[-1]
    last = candles[-1]
    price = last["close"]
    tol = ema_fast * 0.0015
    recent = candles[-config.SWING_LOOKBACK:]

    if price > ema_fast > ema_slow:
        if last["low"] <= ema_fast + tol and last["close"] > ema_fast and last["close"] > last["open"]:
            sl = min(c["low"] for c in recent)
            if sl < price:
                return {"side": "buy", "sl": sl, "ref_price": price, "candle_time": last["time"]}

    elif price < ema_fast < ema_slow:
        if last["high"] >= ema_fast - tol and last["close"] < ema_fast and last["close"] < last["open"]:
            sl = max(c["high"] for c in recent)
            if sl > price:
                return {"side": "sell", "sl": sl, "ref_price": price, "candle_time": last["time"]}

    return None
