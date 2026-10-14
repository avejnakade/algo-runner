"""
Saari settings yahin hain. API keys is file me KABHI mat likhna.
Keys sirf GitHub Secrets se aati hain (environment variables).
"""
import os


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y")


# ---------- Secrets (GitHub Secrets se) ----------
API_KEY = os.environ.get("COINDCX_API_KEY", "").strip().strip("\"' ")
API_SECRET = os.environ.get("COINDCX_API_SECRET", "").strip().strip("\"' ")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip().strip("\"' ")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip().strip("\"' ")

# ---------- Mode ----------
# MODE: run (normal) | selftest (sirf check, order nahi) | test_trade (chhota test trade)
MODE = os.environ.get("MODE", "run").strip() or "run"
# DRY_RUN=true  -> signal aaye to sirf Telegram pe batayega, order NAHI lagayega
DRY_RUN = _bool("DRY_RUN", True)
CONFIRM_TEST = os.environ.get("CONFIRM_TEST", "NO").strip()

# ---------- Strategy ----------
PAIR = "B-ETH_USDT"       # CoinDCX ETH perpetual futures (USDT margined)
EMA_FAST = 50
EMA_SLOW = 200
RISK_REWARD = 3
SWING_LOOKBACK = 10
TIMEFRAME_MIN = 15        # 5m candles se 15m banate hain

# ---------- Risk ----------
QTY_ETH = float(os.environ.get("QTY_ETH", "0.01"))     # lot size 0.01 ETH
LEVERAGE = int(os.environ.get("LEVERAGE", "50"))
MAX_TRADES_PER_DAY = 2
MAX_CONSECUTIVE_LOSSES = 2
MAX_SIGNAL_AGE_SEC = 8 * 60   # candle close ke 8 min baad tak hi entry (late run pe skip)

# SL kabhi Est. Liquidation Price ke bahar nahi jayega: entry se liquidation tak ke raaste ka
# max 80% tak hi SL rakhenge (20% buffer), taaki SL hit hone se pehle liquidation na ho.
LIQ_SL_FRACTION = float(os.environ.get("LIQ_SL_FRACTION", "0.8"))

# SL kahan lage: "ema" = EMA50 se thoda bahar (long: EMA-buffer, short: EMA+buffer), "swing" = pichli 10 candles ka swing low/high
SL_MODE = os.environ.get("SL_MODE", "ema").strip().lower()
SL_EMA_BUFFER = float(os.environ.get("SL_EMA_BUFFER", "3"))   # price points (ETH ke liye $3)
# Agar SL entry se is % se zyada paas ho to trade skip (0 = band). Fees ke saamne bahut chhota SL bekaar hota hai.
MIN_SL_PCT = float(os.environ.get("MIN_SL_PCT", "0"))

# Target kam se kam itne price points door hoga. Target distance = max(RISK_REWARD x SL distance, MIN_TARGET_POINTS)
MIN_TARGET_POINTS = float(os.environ.get("MIN_TARGET_POINTS", "15"))
