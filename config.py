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
API_KEY = os.environ.get("COINDCX_API_KEY", "")
API_SECRET = os.environ.get("COINDCX_API_SECRET", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

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
QTY_ETH = float(os.environ.get("QTY_ETH", "0.001"))   # 1 lot = 0.001 ETH
LEVERAGE = int(os.environ.get("LEVERAGE", "5"))
MAX_TRADES_PER_DAY = 2
MAX_CONSECUTIVE_LOSSES = 2
MAX_SIGNAL_AGE_SEC = 8 * 60   # candle close ke 8 min baad tak hi entry (late run pe skip)
