"""
Har 15 minute me GitHub Actions ye file ek baar chalata hai.

Koi state file repo me save nahi hoti (repo public hai). Aaj ke trades, losses, aur
"is candle pe pehle hi trade ho chuka" - ye sab seedha CoinDCX ke order history se nikalta hai.

MODE:
  run         normal kaam (DRY_RUN=true ho to sirf signal batata hai, order nahi lagata)
  selftest    sirf check: API key, instrument, candles, signal. Koi order nahi.
  test_trade  ek chhota test trade (entry + SL/TP + exit) taaki poora flow verify ho. confirm=YES chahiye.
"""
import time
from datetime import datetime, timezone, timedelta

import config
import coindcx_client as cx
import notifier
import strategy
from coindcx_client import ApiError

IST = timezone(timedelta(hours=5, minutes=30))
LOSS_TYPES = ("stop_market", "stop_limit")
PERIOD_MS = config.TIMEFRAME_MIN * 60 * 1000


def now_ms() -> int:
    return int(time.time() * 1000)


def day_start_ms() -> int:
    n = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(n.timestamp() * 1000)


def ist_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, IST).strftime("%d-%b %H:%M IST")


def derive_state(orders: list, day_start: int):
    """CoinDCX order history se: aaj ke entries, trailing losses, aaj ke TP/SL exits."""
    mine = [o for o in orders if o.get("pair") == config.PAIR]
    entries = [o for o in mine
               if o.get("stage") in (None, "None", "default")
               and o.get("order_type") == "market_order"
               and int(o.get("created_at") or 0) >= day_start]
    exits = sorted([o for o in mine
                    if o.get("stage") == "tpsl_exit" and int(o.get("updated_at") or 0) >= day_start],
                   key=lambda o: int(o.get("updated_at") or 0))
    losses = 0
    for o in reversed(exits):
        if o.get("order_type") in LOSS_TYPES:
            losses += 1
        else:
            break
    return entries, losses, exits


def qty_for(inst: dict):
    inc = float(inst.get("quantity_increment") or 0.001)
    min_q = float(inst.get("min_quantity") or 0)
    qty = cx.floor_to_step(config.QTY_ETH, inc)   # kabhi upar round nahi: size tumhare QTY_ETH se bada nahi hoga
    return qty, min_q


def wait_for_position(timeout_s: int = 24):
    end = time.time() + timeout_s
    while time.time() < end:
        time.sleep(2)
        pos = cx.get_position(config.PAIR)
        if cx.is_open(pos):
            return pos
    return None


def emergency_exit(pos_id: str, reason: str):
    try:
        cx.exit_position(pos_id)
        notifier.send(f"ALERT: {reason}\nPosition turant band kar di gayi (bina SL ke nahi rakhi).")
    except Exception as e:
        notifier.send(f"ALERT BADA: {reason}\nPosition band bhi nahi ho payi ({str(e)[:100]}). "
                      f"CoinDCX app se TURANT manually band karo ya SL lagao!")


def liq_price_of(pos: dict, entry: float, long_: bool):
    """Position se Est. Liquidation Price. Na mile/galat ho to conservative estimate (leverage se)."""
    try:
        liq = float(pos.get("liquidation_price") or 0)
    except Exception:
        liq = 0.0
    if liq > 0 and ((long_ and liq < entry) or ((not long_) and liq > entry)):
        return liq, False
    dist = entry * 0.85 / config.LEVERAGE
    return (entry - dist if long_ else entry + dist), True


def open_trade(sig: dict, inst: dict):
    tick = float(inst.get("price_increment") or 0.01)
    long_ = sig["side"] == "buy"
    qty, min_q = qty_for(inst)
    if float(qty) <= 0 or float(qty) < min_q:
        notifier.send(f"Signal aaya par minimum lot {min_q} ETH (step {inst.get('quantity_increment')}) hai, "
                      f"aapka QTY_ETH {config.QTY_ETH} usse chhota hai. Trade nahi liya.")
        return
    max_lev = float((inst.get("max_leverage_long") if long_ else inst.get("max_leverage_short")) or 0)
    if max_lev and config.LEVERAGE > max_lev:
        notifier.send(f"Signal aaya par is side ke liye max leverage {max_lev}x hai, aapka LEVERAGE {config.LEVERAGE}x. "
                      f"Trade nahi liya. (Repo Variables me LEVERAGE badlo)")
        return

    sl_pct = abs(sig["ref_price"] - sig["sl"]) / sig["ref_price"] * 100
    if config.MIN_SL_PCT > 0 and sl_pct < config.MIN_SL_PCT:
        notifier.send(f"Signal skip: SL entry se sirf {sl_pct:.2f}% door hai (MIN_SL_PCT {config.MIN_SL_PCT}%). "
                      f"Itne paas SL fees me hi kat jaata hai.")
        return

    ref = cx.fmt(cx.round_to_step(sig["ref_price"], tick))
    cx.place_market_order(config.PAIR, sig["side"], cx.fmt(qty), config.LEVERAGE, ref)

    pos = wait_for_position()
    if not pos:
        notifier.send("ALERT: entry order gaya par position confirm nahi hui. CoinDCX app me check karo.")
        return

    entry = float(pos.get("avg_price") or sig["ref_price"])
    liq, liq_estimated = liq_price_of(pos, entry, long_)

    # SL: strategy ka, par Est. Liquidation Price ke andar (80% raaste tak) hi
    sl = float(cx.round_to_step(sig["sl"], tick))
    limit = entry - config.LIQ_SL_FRACTION * (entry - liq) if long_ else entry + config.LIQ_SL_FRACTION * (liq - entry)
    adjusted = (long_ and sl < limit) or ((not long_) and sl > limit)
    if adjusted:
        sl = float(cx.ceil_to_step(limit, tick)) if long_ else float(cx.floor_to_step(limit, tick))

    risk = abs(entry - sl)
    if risk <= 0 or (long_ and sl >= entry) or ((not long_) and sl <= entry):
        emergency_exit(pos["id"], "Fill price SL ke galat side par aa gaya")
        return
    # Target distance = max(3 x ASLI final SL distance, minimum target points)
    tp_dist = max(config.RISK_REWARD * risk, config.MIN_TARGET_POINTS)
    tp = entry + tp_dist if long_ else entry - tp_dist
    # Target door ki taraf round (taaki "kam se kam 15 point" hamesha pura rahe)
    tp_s = cx.fmt(cx.ceil_to_step(tp, tick)) if long_ else cx.fmt(cx.floor_to_step(tp, tick))
    sl_s = cx.fmt(cx.round_to_step(sl, tick))
    tp_dist = abs(float(tp_s) - entry)

    try:
        cx.create_tpsl(pos["id"], tp_s, sl_s)
    except ApiError as e:
        emergency_exit(pos["id"], f"SL/Target set nahi ho paya: {str(e)[:120]}")
        return

    note = ""
    if adjusted:
        note += f"\nSL liquidation ke bahar jaa raha tha, isliye strategy SL {sig['sl']} ki jagah {sl_s} lagaya."
    if liq_estimated:
        note += "\n(Liquidation price API se nahi mila, estimate use kiya.)"
    loss_est = risk * float(qty)
    try:
        fee_pct = 2 * float(inst.get("taker_fee")) * 1.18      # entry+exit market, 18% GST
        fee_note = f" | round-trip fees ~{fee_pct:.2f}% of notional"
    except Exception:
        fee_note = ""
    note += f"\nSL distance {risk / entry * 100:.2f}% ({config.SL_MODE.upper()} SL){fee_note}"
    notifier.send(f"Trade liya: {sig['side'].upper()} {config.PAIR} qty {cx.fmt(qty)} @ {config.LEVERAGE}x\n"
                  f"Entry ~{entry}\nSL {sl_s} ({risk:.1f} pt)\nTarget {tp_s} ({tp_dist:.1f} pt, RR 1:{tp_dist / risk:.1f})\n"
                  f"Est. Liq ~{round(liq, 2)} | SL hit pe loss ~{round(loss_est, 3)} USDT{note}")


def run_normal():
    inst = cx.get_instrument(config.PAIR)
    pos = cx.get_position(config.PAIR)
    orders = cx.list_orders("filled", 50)
    entries, losses, exits = derive_state(orders, day_start_ms())

    n = datetime.now(IST)
    if n.hour == 9 and n.minute < 15:
        notifier.send(f"Bot alive ({'DRY-RUN' if config.DRY_RUN else 'LIVE'}). "
                      f"Aaj ke trades {len(entries)}/{config.MAX_TRADES_PER_DAY}, losses (lagataar) {losses}")

    # Trade khuli hai: kuch nahi karna, bas SL/TP check
    if cx.is_open(pos):
        tp_ok = pos.get("take_profit_trigger") not in (None, "None", 0, 0.0)
        sl_ok = pos.get("stop_loss_trigger") not in (None, "None", 0, 0.0)
        if not (tp_ok and sl_ok):
            notifier.send("ALERT: Khuli position par SL/Target nahi dikh raha. CoinDCX app me check karo.")
        print("run: position open")
        return

    # Haal hi me band hui trade ka result bata do
    for o in exits:
        if int(o.get("updated_at") or 0) >= now_ms() - 15 * 60 * 1000:
            res = "LOSS (SL hit)" if o.get("order_type") in LOSS_TYPES else "WIN (Target hit)"
            notifier.send(f"Trade band: {res}, exit ~{o.get('avg_price')}\n"
                          f"Aaj ke trades {len(entries)}/{config.MAX_TRADES_PER_DAY}, lagataar losses {losses}")

    if len(entries) >= config.MAX_TRADES_PER_DAY:
        print("run: daily trade limit")
        return
    if losses >= config.MAX_CONSECUTIVE_LOSSES:
        print("run: consecutive loss limit")
        return

    candles = cx.aggregate_15m(cx.get_candles_5m(config.PAIR, 800), now_ms())
    sig = strategy.check_signal(candles)
    if not sig:
        print("run: no signal")
        return

    close_ms = sig["candle_time"] + PERIOD_MS
    if now_ms() - close_ms > config.MAX_SIGNAL_AGE_SEC * 1000:
        print("run: signal purana (late run), skip")
        return
    if any(int(o.get("created_at") or 0) >= close_ms for o in entries):
        print("run: is candle pe trade ho chuka")
        return

    if config.DRY_RUN:
        notifier.send(f"DRY-RUN signal: {sig['side'].upper()} ref {sig['ref_price']} SL {sig['sl']} "
                      f"(candle {ist_str(sig['candle_time'])}). Order NAHI lagaya.")
        print("run: dry-run signal")
        return

    open_trade(sig, inst)
    print("run: trade attempted")


def selftest():
    lines = [f"SELFTEST ({'DRY-RUN' if config.DRY_RUN else 'LIVE'}) pair {config.PAIR}"]
    inst = cx.get_instrument(config.PAIR)
    lines.append(f"Instrument: status={inst.get('status')} min_qty={inst.get('min_quantity')} "
                 f"qty_step={inst.get('quantity_increment')} tick={inst.get('price_increment')} "
                 f"max_lev={inst.get('max_leverage_long')} fee maker/taker={inst.get('maker_fee')}/{inst.get('taker_fee')} "
                 f"order_types={inst.get('order_types')}")
    qty, min_q = qty_for(inst)
    lines.append(f"QTY_ETH={config.QTY_ETH} -> use hoga {cx.fmt(qty)} | min lot OK: {float(qty) > 0 and float(qty) >= min_q}")

    c5p = cx.get_candles_5m(config.PAIR, 20)
    px = c5p[-1]["close"] if c5p else 0
    max_lev = inst.get("max_leverage_long")
    lines.append(f"Leverage {config.LEVERAGE}x (max {max_lev}) -> OK: {not max_lev or config.LEVERAGE <= float(max_lev)} | "
                 f"approx margin {round(float(qty) * px / config.LEVERAGE, 3)} USDT @ price {px}")
    pos = cx.get_position(config.PAIR)          # signed call = API key auth check
    lines.append(f"API key auth: OK | khuli position: {cx.is_open(pos)}")

    c5 = cx.get_candles_5m(config.PAIR, 800)
    aligned = all(c["time"] % 300000 == 0 for c in c5[-20:]) if c5 else False
    c15 = cx.aggregate_15m(c5, now_ms())
    lines.append(f"Candles: 5m={len(c5)} 15m(closed)={len(c15)} alignment_ok={aligned}")
    if c15:
        lines.append(f"Last closed 15m: {ist_str(c15[-1]['time'])} close={c15[-1]['close']}")
    sig = strategy.check_signal(c15)
    lines.append(f"Abhi signal: {sig['side'].upper() + ' SL ' + str(sig['sl']) if sig else 'koi nahi'}")
    entries, losses, _ = derive_state(cx.list_orders('filled', 50), day_start_ms())
    lines.append(f"Aaj entries {len(entries)}, lagataar losses {losses}")
    notifier.send("\n".join(lines))
    print("selftest done")


def test_trade():
    if config.CONFIRM_TEST != "YES":
        notifier.send("test_trade ke liye confirm input me YES likhna zaroori hai. Kuch nahi kiya.")
        return
    inst = cx.get_instrument(config.PAIR)
    if cx.is_open(cx.get_position(config.PAIR)):
        notifier.send("TEST roka: pehle se position khuli hai.")
        return
    tick = float(inst.get("price_increment") or 0.01)
    inc = float(inst.get("quantity_increment") or 0.001)
    qty = cx.ceil_to_step(max(config.QTY_ETH, float(inst.get("min_quantity") or 0)), inc)
    c15 = cx.aggregate_15m(cx.get_candles_5m(config.PAIR, 300), now_ms())
    ref = cx.fmt(cx.round_to_step(c15[-1]["close"], tick))

    cx.place_market_order(config.PAIR, "buy", cx.fmt(qty), config.LEVERAGE, ref)
    pos = wait_for_position()
    if not pos:
        notifier.send("TEST: order gaya par position nahi dikhi. App me check karo.")
        return
    entry = float(pos.get("avg_price") or ref)
    # Test ke SL/TP liquidation ke andar rakhne ke liye leverage ke hisaab se (1/leverage ka 40%)
    pct = 0.4 / config.LEVERAGE
    sl_s = cx.fmt(cx.round_to_step(entry * (1 - pct), tick))
    tp_s = cx.fmt(cx.round_to_step(entry * (1 + pct), tick))
    try:
        cx.create_tpsl(pos["id"], tp_s, sl_s)
    except ApiError as e:
        emergency_exit(pos["id"], f"TEST: SL/TP fail: {str(e)[:120]}")
        return
    time.sleep(3)
    p2 = cx.get_position(config.PAIR)
    tp_ok = p2 and p2.get("take_profit_trigger") not in (None, "None", 0, 0.0)
    sl_ok = p2 and p2.get("stop_loss_trigger") not in (None, "None", 0, 0.0)
    cx.exit_position(pos["id"])
    time.sleep(3)
    closed = not cx.is_open(cx.get_position(config.PAIR))
    notifier.send(f"TEST TRADE complete: entry {entry}, qty {cx.fmt(qty)}, "
                  f"SL set={bool(sl_ok)} TP set={bool(tp_ok)}, position band={closed}")
    print("test_trade done")


def main():
    if not config.API_KEY or not config.API_SECRET:
        print("API keys set nahi hain (GitHub Secrets check karo)")
        notifier.send("ALERT: COINDCX_API_KEY / SECRET set nahi hain.")
        return
    try:
        if config.MODE == "selftest":
            selftest()
        elif config.MODE == "test_trade":
            test_trade()
        else:
            run_normal()
    except ApiError as e:
        print("api error:", str(e)[:150])
        notifier.send(f"ALERT API error: {str(e)[:300]}")
    except Exception as e:
        print("bot error:", type(e).__name__)
        notifier.send(f"ALERT bot error: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
