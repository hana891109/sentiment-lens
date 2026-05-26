"""
Sentiment Lens - 訊號引擎（GitHub Actions 雲端版）
完全免費，不需要電腦一直開機
由 GitHub Actions 每 15 分鐘自動執行
"""

import json, time, datetime, urllib.request, os, random

# ─── 設定 ─────────────────────────────────────────────────────────────────────
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT",
    "ARBUSDT", "SUIUSDT", "PEPEUSDT", "BNBUSDT",
    "XRPUSDT", "AVAXUSDT", "LINKUSDT", "ADAUSDT",
]

TIMEFRAMES = [("15M", "15m"), ("1H", "1h")]

CONFIG = {
    "lsr_long_threshold":   1.10,
    "lsr_short_threshold":  0.90,
    "funding_long":        -0.01,
    "funding_short":        0.01,
    "atr_sl_multiplier":    1.5,
    "tp_ratios":         [1, 2, 3, 5],
    "max_signals":          50,
    "signal_ttl_hours":     48,
}

OUTPUT_FILE = "public/signals.json"

# ─── HTTP ──────────────────────────────────────────────────────────────────────
def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  ⚠ {url.split('/')[-1].split('?')[0]}: {e}")
        return None

# ─── Binance API ──────────────────────────────────────────────────────────────
def get_funding(sym):
    d = fetch(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}")
    return round(float(d["lastFundingRate"]) * 100, 4) if d else 0.0

def get_lsr(sym):
    d = fetch(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={sym}&period=5m&limit=1")
    return round(float(d[0]["longShortRatio"]), 2) if d and len(d) > 0 else 1.0

def get_oi(sym):
    d = fetch(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}")
    return round(float(d["openInterest"]) / 1_000_000, 2) if d else 0.0

def get_klines(sym, interval, limit=50):
    d = fetch(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={interval}&limit={limit}")
    if not d: return []
    return [{"o": float(c[1]), "h": float(c[2]), "l": float(c[3]), "c": float(c[4]), "v": float(c[5])} for c in d]

def get_price(sym):
    d = fetch(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}")
    return float(d["price"]) if d else 0.0

def get_24h(sym):
    d = fetch(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}")
    return round(float(d.get("priceChangePercent", 0)), 2) if d else 0.0

# ─── 技術指標 ─────────────────────────────────────────────────────────────────
def atr(candles, n=14):
    if len(candles) < n + 1: return 0
    trs = [max(c["h"]-c["l"], abs(c["h"]-candles[i-1]["c"]), abs(c["l"]-candles[i-1]["c"]))
           for i, c in enumerate(candles) if i > 0]
    return sum(trs[-n:]) / n

def ema(vals, n):
    if not vals: return 0
    k, e = 2/(n+1), sum(vals[:n])/n if len(vals)>=n else vals[0]
    for v in vals[n:]: e = v*k + e*(1-k)
    return e

def rsi(candles, n=14):
    if len(candles) < n+1: return 50
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[-n:])/n, sum(losses[-n:])/n
    return round(100 - 100/(1+ag/al) if al != 0 else 100, 1)

# ─── 訊號分析 ─────────────────────────────────────────────────────────────────
ROLES = {"LONG": ["獵頭者","先鋒者","衝鋒者"], "SHORT": ["沉思者","獵空者","伏擊者"]}

def analyze(sym, tf_label, tf_bin):
    print(f"  {sym} {tf_label}", end=" ")
    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bin)
    price   = get_price(sym)
    chg24h  = get_24h(sym)

    if not candles or price == 0:
        print("→ 跳過")
        return None

    a       = atr(candles)
    closes  = [c["c"] for c in candles]
    ema20   = ema(closes, 20)
    ema50   = ema(closes, 50) if len(closes) >= 50 else ema20
    rsi_val = rsi(candles)
    vol_avg = sum(c["v"] for c in candles[-20:]) / 20
    vol_surge = candles[-1]["v"] > vol_avg * 1.5

    ls, ss = 0, 0
    reasons_l, reasons_s = [], []

    if funding <= CONFIG["funding_long"]:
        ls += 2; reasons_l.append(f"資金費率{funding}%極低")
    if funding >= CONFIG["funding_short"]:
        ss += 2; reasons_s.append(f"資金費率{funding}%極高")
    if lsr <= CONFIG["lsr_long_threshold"]:
        ls += 2; reasons_l.append(f"多空比{lsr}散戶過空")
    if lsr >= CONFIG["lsr_short_threshold"]:
        ss += 2; reasons_s.append(f"多空比{lsr}散戶過多")
    if ema20 > ema50: ls += 1
    else:             ss += 1
    if rsi_val < 30:  ls += 2; reasons_l.append(f"RSI{rsi_val}超賣")
    if rsi_val > 70:  ss += 2; reasons_s.append(f"RSI{rsi_val}超買")
    if vol_surge:
        if chg24h > 0: ls += 1
        else:          ss += 1

    print(f"L:{ls} S:{ss}", end=" ")

if ls < 1 and ss < 1:
        print(f"→ 條件不足")
        return None

    direction = "LONG" if ls >= ss else "SHORT"
    sl_dist   = a * CONFIG["atr_sl_multiplier"] or price * 0.02
    trigger   = price
    sl  = round(trigger - sl_dist if direction=="LONG" else trigger + sl_dist, 8)
    tps = [round(trigger + sl_dist*r if direction=="LONG" else trigger - sl_dist*r, 8)
           for r in CONFIG["tp_ratios"]]

    print(f"→ ✅ {direction}")
    return {
        "id":          f"{sym}-{tf_label}-{int(time.time())}",
        "symbol":      sym.replace("USDT",""),
        "timeframe":   tf_label,
        "direction":   direction,
        "role":        random.choice(ROLES[direction]),
        "trigger":     round(trigger,8),
        "current":     round(trigger,8),
        "sl":          sl,
        "risk_pct":    round(abs(sl-trigger)/trigger*100, 2),
        "tp1":tps[0], "tp2":tps[1], "tp3":tps[2], "ftp":tps[3],
        "pnl":         0.0,
        "reached_tp":  0,
        "active":      True,
        "funding":     funding,
        "lsr":         lsr,
        "oi":          oi,
        "rsi":         rsi_val,
        "chg24h":      chg24h,
        "long_score":  ls,
        "short_score": ss,
        "reasons":     reasons_l if direction=="LONG" else reasons_s,
        "triggered_at": datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M"),
        "timestamp":   int(time.time()),
    }

# ─── 盈虧更新 ─────────────────────────────────────────────────────────────────
def update_pnl(sig):
    p = get_price(sig["symbol"]+"USDT")
    if not p: return sig
    sig["current"] = p
    t   = sig["trigger"]
    pnl = (p-t)/t*100 if sig["direction"]=="LONG" else (t-p)/t*100
    sig["pnl"] = round(pnl, 2)
    for i, tp in enumerate([sig["tp1"],sig["tp2"],sig["tp3"],sig["ftp"]]):
        if (sig["direction"]=="LONG" and p>=tp) or (sig["direction"]=="SHORT" and p<=tp):
            sig["reached_tp"] = i+1
    if (sig["direction"]=="LONG" and p<=sig["sl"]) or (sig["direction"]=="SHORT" and p>=sig["sl"]):
        sig["active"] = False
    return sig

# ─── 主流程 ───────────────────────────────────────────────────────────────────
def load():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            return json.load(f).get("signals", [])
    return []

def save(signals):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "signals":    signals,
            "updated_at": datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M UTC"),
            "total":      len(signals),
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 儲存 {len(signals)} 個訊號")

def main():
    print("="*50)
    print(f"  Sentiment Lens · {datetime.datetime.utcnow().strftime('%Y/%m/%d %H:%M')} UTC")
    print("="*50)

    existing = load()
    cutoff   = int(time.time()) - CONFIG["signal_ttl_hours"]*3600
    updated  = []
    print(f"\n📊 更新 {len(existing)} 個現有訊號...")
    for s in existing:
        if s.get("timestamp",0) < cutoff: continue
        if s.get("active", True):
            s = update_pnl(s)
            time.sleep(0.2)
        updated.append(s)

    print(f"\n🔍 掃描新訊號...")
    new_sigs     = []
    dedup_cutoff = int(time.time()) - 3600
    for sym in SYMBOLS:
        for tf_label, tf_bin in TIMEFRAMES:
            if any(s["symbol"]==sym.replace("USDT","") and s["timeframe"]==tf_label
                   and s.get("timestamp",0)>dedup_cutoff for s in updated):
                continue
            sig = analyze(sym, tf_label, tf_bin)
            if sig: new_sigs.append(sig)
            time.sleep(0.4)

    all_sigs = sorted(new_sigs+updated, key=lambda x: x.get("timestamp",0), reverse=True)
    all_sigs = all_sigs[:CONFIG["max_signals"]]
    save(all_sigs)
    print(f"🆕 新增 {len(new_sigs)} 個 | 合計 {len(all_sigs)} 個")

if __name__ == "__main__":
    main()
