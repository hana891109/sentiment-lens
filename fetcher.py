import json, time, datetime, urllib.request, os, random

SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","DOGEUSDT","BNBUSDT","XRPUSDT","ADAUSDT","AVAXUSDT"]
TIMEFRAMES = [("15M","15m"),("1H","1h")]
OUTPUT_FILE = "public/signals.json"

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  error: {e}")
        return None

def get_price(sym):
    d = fetch(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}")
    return float(d["price"]) if d else 0.0

def get_funding(sym):
    d = fetch(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
    return round(float(d["lastFundingRate"])*100, 4) if d else 0.0

def get_lsr(sym):
    d = fetch(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={sym}&period=5m&limit=1")
    return round(float(d[0]["longShortRatio"]), 2) if d and len(d)>0 else 1.0

def get_oi(sym):
    d = fetch(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
    return round(float(d["openInterest"])/1_000_000, 2) if d else 0.0

def get_klines(sym, interval, limit=50):
    d = fetch(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}")
    if not d: return []
    return [{"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),"v":float(c[5])} for c in d]

def calc_atr(candles, n=14):
    if len(candles) < 2: return 0
    trs = [candles[i]["h"]-candles[i]["l"] for i in range(1,len(candles))]
    return sum(trs[-n:])/len(trs[-n:]) if trs else 0

def calc_rsi(candles, n=14):
    if len(candles) < n+1: return 50
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-n:])/n
    al = sum(losses[-n:])/n
    return round(100-100/(1+ag/al),1) if al!=0 else 100

ROLES = {"LONG":["獵頭者","先鋒者","衝鋒者"],"SHORT":["沉思者","獵空者","伏擊者"]}

def analyze(sym, tf_label, tf_bin):
    print(f"  {sym} {tf_label}", end=" ")
    price   = get_price(sym)
    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bin)

    if not candles or price == 0:
        print("-> skip")
        return None

    atr_val = calc_atr(candles)
    rsi_val = calc_rsi(candles)

    ls, ss = 0, 0

    # 資金費率
    if funding < 0: ls += 1
    else: ss += 1

    # 多空比
    if lsr < 1.0: ls += 1
    else: ss += 1

    # RSI
    if rsi_val < 45: ls += 1
    if rsi_val > 55: ss += 1

    direction = "LONG" if ls >= ss else "SHORT"
    sl_dist   = atr_val * 1.5 if atr_val > 0 else price * 0.02
    trigger   = price
    sl        = round(trigger-sl_dist if direction=="LONG" else trigger+sl_dist, 8)
    tps       = [round(trigger+sl_dist*r if direction=="LONG" else trigger-sl_dist*r, 8) for r in [1,2,3,5]]
    risk_pct  = round(abs(sl-trigger)/trigger*100, 2)

    print(f"-> {direction} (L:{ls} S:{ss})")
    return {
        "id":          f"{sym}-{tf_label}-{int(time.time())}",
        "symbol":      sym.replace("USDT",""),
        "timeframe":   tf_label,
        "direction":   direction,
        "role":        random.choice(ROLES[direction]),
        "trigger":     round(trigger,8),
        "current":     round(trigger,8),
        "sl":          sl,
        "risk_pct":    risk_pct,
        "tp1":tps[0],  "tp2":tps[1], "tp3":tps[2], "ftp":tps[3],
        "pnl":         0.0,
        "reached_tp":  0,
        "active":      True,
        "funding":     funding,
        "lsr":         lsr,
        "oi":          oi,
        "rsi":         rsi_val,
        "chg24h":      0.0,
        "long_score":  ls,
        "short_score": ss,
