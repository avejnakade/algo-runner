"""
CoinDCX Futures API se baat karne wala hissa.
Official doc: CoinDCX Futures API (HMAC-SHA256, POST body JSON).
Koi secret kabhi print/log nahi hota.
"""
import hashlib
import hmac
import json
import time
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

import requests

import config

BASE = "https://api.coindcx.com"
PUBLIC = "https://public.coindcx.com"
TIMEOUT = (5, 20)
FUT = "/exchange/v1/derivatives/futures"


class ApiError(Exception):
    pass


def _sign(body_str: str) -> str:
    return hmac.new(config.API_SECRET.encode(), body_str.encode(), hashlib.sha256).hexdigest()


def _post(path: str, body: dict):
    body = dict(body)
    body["timestamp"] = int(time.time() * 1000)
    body_str = json.dumps(body, separators=(",", ":"))
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": config.API_KEY,
        "X-AUTH-SIGNATURE": _sign(body_str),
    }
    try:
        r = requests.post(BASE + path, data=body_str, headers=headers, timeout=TIMEOUT)
        try:
            data = r.json()
        except Exception:
            data = {"error": (r.text or "")[:200]}
        return r.status_code, data
    except Exception as e:
        return 0, {"error": type(e).__name__}


def _get(url: str, params: dict = None):
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        try:
            data = r.json()
        except Exception:
            data = {"error": (r.text or "")[:200]}
        return r.status_code, data
    except Exception as e:
        return 0, {"error": type(e).__name__}


# ---------- Rounding helpers (tick / quantity increment) ----------
def round_to_step(value: float, step: float) -> Decimal:
    s = Decimal(str(step))
    if s <= 0:
        return Decimal(str(value))
    return (Decimal(str(value)) / s).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * s


def ceil_to_step(value: float, step: float) -> Decimal:
    s = Decimal(str(step))
    if s <= 0:
        return Decimal(str(value))
    return (Decimal(str(value)) / s).to_integral_value(rounding=ROUND_CEILING) * s


def floor_to_step(value: float, step: float) -> Decimal:
    s = Decimal(str(step))
    if s <= 0:
        return Decimal(str(value))
    return (Decimal(str(value)) / s).to_integral_value(rounding=ROUND_FLOOR) * s


def fmt(d: Decimal) -> str:
    return format(d.normalize(), "f")


# ---------- Public data ----------
def get_instrument(pair: str) -> dict:
    st, data = _get(f"{BASE}{FUT}/data/instrument", {"pair": pair})
    inst = data.get("instrument") if isinstance(data, dict) else None
    if not inst:
        raise ApiError(f"instrument details nahi mili (http {st})")
    return inst


def get_candles_5m(pair: str, want: int = 800, chunk: int = 400) -> list:
    """5 minute candles (purani se nayi). time = ms me candle ka open time."""
    out = {}
    to = int(time.time())
    for _ in range(6):
        frm = to - chunk * 300
        st, data = _get(f"{PUBLIC}/market_data/candlesticks",
                        {"pair": pair, "from": frm, "to": to, "resolution": "5", "pcode": "f"})
        rows = data.get("data") if isinstance(data, dict) else None
        if not rows:
            break
        for c in rows:
            t = int(c["time"])
            out[t] = {"time": t, "open": float(c["open"]), "high": float(c["high"]),
                      "low": float(c["low"]), "close": float(c["close"])}
        to = frm
        if len(out) >= want:
            break
    return sorted(out.values(), key=lambda c: c["time"])


def aggregate_15m(c5: list, now_ms: int) -> list:
    """5m candles se SIRF POORI BANDH 15m candles banata hai (adhoori candle hata deta hai)."""
    period = config.TIMEFRAME_MIN * 60 * 1000
    per_bucket = config.TIMEFRAME_MIN // 5
    buckets = {}
    for c in c5:
        buckets.setdefault((c["time"] // period) * period, []).append(c)
    out = []
    for b in sorted(buckets):
        if b + period > now_ms:        # abhi chal rahi candle
            continue
        items = sorted(buckets[b], key=lambda x: x["time"])
        if len(items) < per_bucket:    # data adhoora
            continue
        out.append({
            "time": b,
            "open": items[0]["open"],
            "high": max(i["high"] for i in items),
            "low": min(i["low"] for i in items),
            "close": items[-1]["close"],
        })
    return out


# ---------- Private (signed) ----------
def list_positions() -> list:
    st, data = _post(f"{FUT}/positions", {"page": "1", "size": "50"})
    if not isinstance(data, list):
        raise ApiError(f"positions fetch fail (http {st}): {str(data)[:150]}")
    return data


def get_position(pair: str):
    """Open position (active_pos != 0) ho to dict, warna None. (Position record ka id TPSL ke liye chahiye.)"""
    for p in list_positions():
        if p.get("pair") == pair:
            return p
    return None


def is_open(pos) -> bool:
    try:
        return bool(pos) and abs(float(pos.get("active_pos", 0))) > 0
    except Exception:
        return False


def list_orders(status: str = "filled", size: int = 50) -> list:
    seen, out = set(), []
    for side in ("buy", "sell"):
        st, data = _post(f"{FUT}/orders", {"status": status, "side": side, "page": "1", "size": str(size)})
        if not isinstance(data, list):
            raise ApiError(f"orders fetch fail (http {st}): {str(data)[:150]}")
        for o in data:
            if o.get("id") not in seen:
                seen.add(o.get("id"))
                out.append(o)
    return out


def place_market_order(pair: str, side: str, qty: str, leverage: int, ref_price: str):
    body = {"order": {
        "side": side, "pair": pair, "order_type": "market_order",
        "price": ref_price, "total_quantity": float(qty), "leverage": leverage,
        "notification": "no_notification", "time_in_force": "good_till_cancel",
        "hidden": False, "post_only": False}}
    st, data = _post(f"{FUT}/orders/create", body)
    if isinstance(data, list) and data and data[0].get("id"):
        return data[0]
    raise ApiError(f"order reject (http {st}): {str(data)[:200]}")


def create_tpsl(position_id: str, tp_price: str, sl_price: str) -> dict:
    body = {"id": position_id,
            "take_profit": {"stop_price": tp_price, "order_type": "take_profit_market"},
            "stop_loss": {"stop_price": sl_price, "order_type": "stop_market"}}
    st, data = _post(f"{FUT}/positions/create_tpsl", body)
    ok_sl = isinstance(data, dict) and isinstance(data.get("stop_loss"), dict) and data["stop_loss"].get("id")
    ok_tp = isinstance(data, dict) and isinstance(data.get("take_profit"), dict) and data["take_profit"].get("id")
    if not (ok_sl and ok_tp):
        raise ApiError(f"TP/SL set nahi hua (http {st}): {str(data)[:200]}")
    return data


def exit_position(position_id: str) -> dict:
    st, data = _post(f"{FUT}/positions/exit", {"id": position_id})
    if not (isinstance(data, dict) and data.get("code") == 200):
        raise ApiError(f"position exit fail (http {st}): {str(data)[:150]}")
    return data
