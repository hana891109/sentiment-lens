import json
import time
import datetime
import urllib.request
import os
import random

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT","BNBUSDT","XRPUSDT","ADAUSDT","AVAXUSDT"]
TIMEFRAMES = [("15M","15m"),("1H","1h")]
OUTPUT_FILE = "public/signals.json"

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print("  error: " + str(e))
        return None

def get_price(sym):
    d = fetch("https://api.binance.com/api/v3/ticker/price?symbol=" + sym)
    return float(d["price"]) if d else 0.0

def get_funding(sym):
    d = fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=" + sym)
    return round(float(d["lastFundingRate"]) * 100, 4) if d else 0.0

def get_lsr(sym):
    d = fetch("https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=" + sym + "&period=5m&limit=1")
    return round(float(d[0]["longShortRatio"]), 2) if d and len(d) > 0 else 1.0

def get_oi(sym):
    d = fetch("https://fapi.binance.com/fapi/v1/openInterest?symbol=" + sym)
    return round(float(d["openInterest"]) / 1000000, 2) if d else 0.0

def get_klines(sym, interval):
    d = fetch("https://fapi.binance.com/fapi/v1/klines?symbol=" + sym + "&interval=" + interval + "&limit=50")
    if not d:
        return []
    result = []
    for c in d:
        result.append({"h": float(c[2]), "l": float(c[3]), "c": float(c[4]), "v": float(c[5])})
    return result

def calc_atr(candles):
    if len(candles) < 2:
        return 0
    trs = []
    for i in range(1, len(candles)):
        trs.append(candles[i]["h"] - candles[i]["l"])
    return sum(trs[-14:]) / len(trs[-14:]) if trs else 0

def calc_rsi(candles):
    if len(candles) < 15:
        return 50
    closes = [c["c"] for c in candles]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    ag = sum(gains[-14:]) / 14
    al = sum(losses[-14:]) / 14
    if al == 0:
        return 100
    return round(100 - 100 / (1 + ag / al), 1)

def analyze(sym, tf_label, tf_bin):
    print("  " + sym + " " + tf_label, end=" ")
    price = get_price(sym)
    funding = get_funding(sym)
    lsr = get_lsr(sym)
    oi = get_oi(sym)
    candles = get_klines(sym, tf_bin)

    if not candles or price == 0:
        print("-> skip")
        return None

    atr_val = calc_atr(candles)
    rsi_val = calc_rsi(candles)

    ls = 0
    ss = 0

    if funding < 0:
        ls += 1
    else:
        ss += 1

    if lsr < 1.0:
        ls += 1
    else:
        ss += 1

    if rsi_val < 45:
        ls += 1
    if rsi_val > 55:
        ss += 1

    if ls >= ss:
        direction = "LONG"
    else:
        direction = "SHORT"

    if atr_val > 0:
        sl_dist = atr_val * 1.5
    else:
        sl_dist = price * 0.02

    trigger = price

    if direction == "LONG":
        sl = round(trigger - sl_dist, 8)
    else:
        sl = round(trigger + sl_dist, 8)

    tps = []
    for r in [1, 2, 3, 5]:
        if direction == "LONG":
            tps.append(round(trigger + sl_dist * r, 8))
        else:
            tps.append(round(trigger - sl_dist * r, 8))

    risk_pct = round(abs(sl - trigger) / trigger * 100, 2)

    long_roles = ["獵頭者", "先鋒者", "衝鋒者"]
    short_roles = ["沉思者", "獵空者", "伏擊者"]

    if direction == "LONG":
        role = random.choice(long_roles)
    else:
        role = random.choice(short_roles)

    now_str = datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M")
    print("-> " + direction)

    return {
        "id": sym + "-" + tf_label + "-" + str(int(time.time())),
        "symbol": sym.replace("USDT", ""),
        "timeframe": tf_label,
        "direction": direction,
        "role": role,
        "trigger": round(trigger, 8),
        "current": round(trigger, 8),
        "sl": sl,
        "risk_pct": risk_pct,
        "tp1": tps[0],
        "tp2": tps[1],
        "tp3": tps[2],
        "ftp": tps[3],
        "pnl": 0.0,
        "reached_tp": 0,
        "active": True,
        "funding": funding,
        "lsr": lsr,
        "oi": oi,
        "rsi": rsi_val,
        "chg24h": 0.0,
        "long_score": ls,
        "short_score": ss,
        "reasons": [],
        "triggered_at": now_str,
        "timestamp": int(time.time()),
    }

def update_pnl(sig):
    p = get_price(sig["symbol"] + "USDT")
    if not p:
        return sig
    sig["current"] = p
    t = sig["trigger"]
    if sig["direction"] == "LONG":
        pnl = (p - t) / t * 100
    else:
        pnl = (t - p) / t * 100
    sig["pnl"] = round(pnl, 2)
    for i, tp in enumerate([sig["tp1"], sig["tp2"], sig["tp3"], sig["ftp"]]):
        if sig["direction"] == "LONG" and p >= tp:
            sig["reached_tp"] = i + 1
        elif sig["direction"] == "SHORT" and p <= tp:
            sig["reached_tp"] = i + 1
    if sig["direction"] == "LONG" and p <= sig["sl"]:
        sig["active"] = False
    elif sig["direction"] == "SHORT" and p >= sig["sl"]:
        sig["active"] = False
    return sig

def load():
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as f:
                return json.load(f).get("signals", [])
        except Exception:
            return []
    return []

def save(signals):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    data = {
        "signals": signals,
        "updated_at": datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M UTC"),
        "total": len(signals),
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("saved " + str(len(signals)) + " signals")

def main():
    print("Sentiment Lens - " + datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M") + " UTC")

    existing = load()
    cutoff = int(time.time()) - 48 * 3600
    updated = []
    for s in existing:
        if s.get("timestamp", 0) < cutoff:
            continue
        if s.get("active", True):
            s = update_pnl(s)
            time.sleep(0.2)
        updated.append(s)

    print("scanning...")
    new_sigs = []
    dedup_cutoff = int(time.time()) - 3600

    for sym in SYMBOLS:
        for tf_label, tf_bin in TIMEFRAMES:
            skip = False
            for s in updated:
                if s["symbol"] == sym.replace("USDT","") and s["timeframe"] == tf_label and s.get("timestamp",0) > dedup_cutoff:
                    skip = True
                    break
            if skip:
                continue
            sig = analyze(sym, tf_label, tf_bin)
            if sig:
                new_sigs.append(sig)
            time.sleep(0.3)

    all_sigs = new_sigs + updated
    all_sigs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    all_sigs = all_sigs[:50]
    save(all_sigs)
    print("done. new=" + str(len(new_sigs)) + " total=" + str(len(all_sigs)))

if __name__ == "__main__":
    main()
