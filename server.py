import json
import time
import datetime
import urllib.request
import random
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

# ─── 設定 ─────────────────────────────────────────────────────────────────────
SYMBOLS = [
    ("BTC","BTC-USDT-SWAP"),("ETH","ETH-USDT-SWAP"),("SOL","SOL-USDT-SWAP"),
    ("DOGE","DOGE-USDT-SWAP"),("BNB","BNB-USDT-SWAP"),("XRP","XRP-USDT-SWAP"),
    ("ADA","ADA-USDT-SWAP"),("AVAX","AVAX-USDT-SWAP"),("LINK","LINK-USDT-SWAP"),
    ("ARB","ARB-USDT-SWAP"),("OP","OP-USDT-SWAP"),("MATIC","MATIC-USDT-SWAP"),
]
TIMEFRAMES    = [("15M","15m"),("1H","1H")]
SCAN_INTERVAL = 30       # 每 30 秒掃描
DEDUP_SECONDS = 7200     # 同幣同週期 2 小時內不重複
MAX_SIGNALS   = 100      # 最多保留 100 個
SIGNAL_TTL    = 3 * 24 * 3600  # 保留 3 天
MIN_SCORE     = 6        # 最低觸發分數（平衡品質與數量）

signals_store = []
store_lock    = threading.Lock()
last_update   = ""

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
RENDER_URL   = os.environ.get("RENDER_URL", "")

# ─── 時區工具 ─────────────────────────────────────────────────────────────────
def tw_now():
    tw = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return tw.strftime("%Y/%m/%d %H:%M")

def tw_now_full():
    tw = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
    return tw.strftime("%Y/%m/%d %H:%M:%S")

def tw_hour():
    return (datetime.datetime.utcnow().hour + 8) % 24

def get_session():
    h = tw_hour()
    if 8 <= h < 16:
        return "亞洲盤", "low"
    elif 15 <= h < 22:
        return "歐洲盤", "high"
    elif 20 <= h < 24 or 0 <= h < 4:
        return "美洲盤", "high"
    else:
        return "離市時段", "low"

# ─── HTTP 工具 ────────────────────────────────────────────────────────────────
def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print("err: " + str(e)[:60])
        return None

# ─── OKX API ──────────────────────────────────────────────────────────────────
def get_price(sym):
    d = fetch("https://www.okx.com/api/v5/market/ticker?instId=" + sym)
    if d and d.get("data"):
        return float(d["data"][0]["last"])
    return 0.0

def get_funding(sym):
    d = fetch("https://www.okx.com/api/v5/public/funding-rate?instId=" + sym)
    if d and d.get("data"):
        return round(float(d["data"][0]["fundingRate"]) * 100, 4)
    return 0.0

def get_lsr(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=" + ccy + "&period=5m")
    if d and d.get("data") and len(d["data"]) > 0:
        try:
            return round(float(d["data"][0][1]), 2)
        except Exception:
            return 1.0
    return 1.0

def get_oi(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=" + ccy + "&period=5m")
    if d and d.get("data") and len(d["data"]) > 0:
        try:
            return round(float(d["data"][0][1]) / 1000000, 2)
        except Exception:
            return 0.0
    return 0.0

def get_oi_change(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=" + ccy + "&period=5m&limit=6")
    if d and d.get("data") and len(d["data"]) >= 4:
        try:
            now  = float(d["data"][0][1])
            prev = float(d["data"][3][1])
            return round((now - prev) / prev * 100, 2) if prev > 0 else 0.0
        except Exception:
            return 0.0
    return 0.0

def get_klines(sym, bar, limit=100):
    d = fetch("https://www.okx.com/api/v5/market/candles?instId=" + sym + "&bar=" + bar + "&limit=" + str(limit))
    if not d or not d.get("data"):
        return []
    result = []
    for c in reversed(d["data"]):
        try:
            result.append({
                "h": float(c[2]), "l": float(c[3]),
                "c": float(c[4]), "v": float(c[5]),
            })
        except Exception:
            pass
    return result

# ─── 技術指標 ─────────────────────────────────────────────────────────────────
def calc_atr(candles, n=14):
    if len(candles) < n + 1:
        return 0
    trs = []
    for i in range(1, len(candles)):
        trs.append(max(
            candles[i]["h"] - candles[i]["l"],
            abs(candles[i]["h"] - candles[i-1]["c"]),
            abs(candles[i]["l"] - candles[i-1]["c"]),
        ))
    vals = trs[-n:]
    return sum(vals) / len(vals) if vals else 0

def calc_rsi(candles, n=14):
    if len(candles) < n + 1:
        return 50
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100
    return round(100 - 100 / (1 + ag / al), 1)

def calc_ema(closes, n):
    if not closes:
        return 0
    if len(closes) < n:
        return closes[-1]
    k = 2 / (n + 1)
    e = sum(closes[:n]) / n
    for v in closes[n:]:
        e = v * k + e * (1 - k)
    return e

def calc_bb(closes, n=20):
    if len(closes) < n:
        mid = closes[-1] if closes else 0
        return mid, mid, mid
    recent = closes[-n:]
    mid = sum(recent) / n
    std = (sum((x - mid) ** 2 for x in recent) / n) ** 0.5
    return round(mid + 2*std, 8), round(mid, 8), round(mid - 2*std, 8)

def calc_stoch_rsi(candles, n=14):
    if len(candles) < n * 2:
        return 50
    closes = [c["c"] for c in candles]
    rsi_vals = []
    for i in range(n, len(closes)):
        subset = [{"c": closes[j]} for j in range(i-n, i+1)]
        rsi_vals.append(calc_rsi(subset, n))
    if len(rsi_vals) < n:
        return 50
    recent = rsi_vals[-n:]
    lo = min(recent)
    hi = max(recent)
    if hi == lo:
        return 50
    return round((rsi_vals[-1] - lo) / (hi - lo) * 100, 1)

def detect_divergence(candles, n=10):
    if len(candles) < n * 2:
        return None
    recent_prices = [c["c"] for c in candles[-n:]]
    prev_prices   = [c["c"] for c in candles[-n*2:-n]]
    recent_rsi = calc_rsi(candles[-n-14:])
    prev_rsi   = calc_rsi(candles[-n*2-14:-n])
    price_up  = recent_prices[-1] > prev_prices[-1]
    rsi_up    = recent_rsi > prev_rsi
    if price_up and not rsi_up:
        return "BEARISH"
    if not price_up and rsi_up:
        return "BULLISH"
    return None

def get_htf_bias(sym):
    scores = {"LONG": 0, "SHORT": 0}
    for bar in ["1H", "4H"]:
        candles = get_klines(sym, bar, 60)
        if not candles or len(candles) < 30:
            continue
        closes = [c["c"] for c in candles]
        rsi    = calc_rsi(candles)
        ema20  = calc_ema(closes, 20)
        ema50  = calc_ema(closes, 50) if len(closes) >= 50 else ema20
        price  = closes[-1]
        if price > ema20 > ema50:
            scores["LONG"] += 2
        elif price < ema20 < ema50:
            scores["SHORT"] += 2
        if rsi > 55:
            scores["LONG"] += 1
        elif rsi < 45:
            scores["SHORT"] += 1
        time.sleep(0.1)
    if scores["LONG"] > scores["SHORT"]:
        return "LONG"
    if scores["SHORT"] > scores["LONG"]:
        return "SHORT"
    return "NEUTRAL"

# ─── 核心訊號分析 ─────────────────────────────────────────────────────────────
ROLES = {
    "LONG":  ["獵頭者", "先鋒者", "衝鋒者"],
    "SHORT": ["沉思者", "獵空者", "伏擊者"],
}

def analyze(name, sym, tf_label, tf_bar):
    print("  " + name + " " + tf_label, end=" ")

    price   = get_price(sym)
    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    oi_chg  = get_oi_change(sym)
    candles = get_klines(sym, tf_bar, 120)

    if not candles or price == 0:
        print("skip")
        return None

    closes     = [c["c"] for c in candles]
    atr_val    = calc_atr(candles)
    rsi_val    = calc_rsi(candles)
    stoch_rsi  = calc_stoch_rsi(candles)
    ema20      = calc_ema(closes, 20)
    ema50      = calc_ema(closes, 50) if len(closes) >= 50 else ema20
    ema200     = calc_ema(closes, 200) if len(closes) >= 200 else ema50
    bb_u, bb_m, bb_l = calc_bb(closes)
    divergence = detect_divergence(candles)
    vol_avg    = sum(c["v"] for c in candles[-21:-1]) / 20 if len(candles) > 20 else 1
    vol_ratio  = round(candles[-1]["v"] / vol_avg, 2) if vol_avg > 0 else 1.0
    htf_bias   = get_htf_bias(sym)
    session, session_liq = get_session()

    ls = 0
    ss = 0
    reasons_l = []
    reasons_s = []

    # ── 層1：資金費率（權重2）──
    if funding <= -0.03:
        ls += 2; reasons_l.append("資金費率極低" + str(funding) + "%")
    elif funding <= -0.01:
        ls += 1; reasons_l.append("資金費率負值" + str(funding) + "%")
    if funding >= 0.06:
        ss += 2; reasons_s.append("資金費率極高" + str(funding) + "%")
    elif funding >= 0.02:
        ss += 1; reasons_s.append("資金費率偏高" + str(funding) + "%")

    # ── 層2：多空比逆向（權重2）──
    if lsr <= 0.75:
        ls += 2; reasons_l.append("散戶極度做空 LSR:" + str(lsr))
    elif lsr <= 0.90:
        ls += 1; reasons_l.append("多空比偏空 LSR:" + str(lsr))
    if lsr >= 1.4:
        ss += 2; reasons_s.append("散戶極度做多 LSR:" + str(lsr))
    elif lsr >= 1.15:
        ss += 1; reasons_s.append("多空比偏多 LSR:" + str(lsr))

    # ── 層3：RSI（權重2）──
    if rsi_val <= 25:
        ls += 2; reasons_l.append("RSI嚴重超賣:" + str(rsi_val))
    elif rsi_val <= 40:
        ls += 1; reasons_l.append("RSI超賣:" + str(rsi_val))
    if rsi_val >= 75:
        ss += 2; reasons_s.append("RSI嚴重超買:" + str(rsi_val))
    elif rsi_val >= 60:
        ss += 1; reasons_s.append("RSI超買:" + str(rsi_val))

    # ── 層4：Stochastic RSI（權重1）──
    if stoch_rsi <= 20:
        ls += 1; reasons_l.append("StochRSI超賣:" + str(stoch_rsi))
    if stoch_rsi >= 80:
        ss += 1; reasons_s.append("StochRSI超買:" + str(stoch_rsi))

    # ── 層5：均線排列（權重2）──
    if price > ema20 > ema50:
        ls += 2; reasons_l.append("均線多頭排列")
    elif price < ema20 < ema50:
        ss += 2; reasons_s.append("均線空頭排列")

    # ── 層6：EMA200 大趨勢（權重1）──
    if price > ema200:
        ls += 1
    else:
        ss += 1

    # ── 層7：布林帶位置（權重1）──
    if price <= bb_l:
        ls += 1; reasons_l.append("觸碰布林下軌")
    if price >= bb_u:
        ss += 1; reasons_s.append("觸碰布林上軌")

    # ── 層8：成交量放大確認（權重1）──
    if vol_ratio >= 1.8:
        if price > closes[-2]:
            ls += 1; reasons_l.append("成交量放大" + str(vol_ratio) + "x看漲")
        else:
            ss += 1; reasons_s.append("成交量放大" + str(vol_ratio) + "x看跌")

    # ── 層9：OI 變化（權重1）──
    if oi_chg >= 8:
        if funding < 0:
            ls += 1; reasons_l.append("OI急增+空頭資金")
        else:
            ss += 1; reasons_s.append("OI急增+多頭資金")
    elif oi_chg <= -8:
        if ls > ss:
            ls += 1; reasons_l.append("OI急減空頭清倉")
        else:
            ss += 1; reasons_s.append("OI急減多頭清倉")

    # ── 層10：背離（反轉訊號，權重2）──
    if divergence == "BULLISH":
        ls += 2; reasons_l.append("RSI看漲背離（反轉機會）")
    elif divergence == "BEARISH":
        ss += 2; reasons_s.append("RSI看跌背離（反轉機會）")

    # ── 層11：高時間週期共鳴（權重3，最重要）──
    if htf_bias == "LONG":
        ls += 3; reasons_l.append("高週期多頭共鳴")
    elif htf_bias == "SHORT":
        ss += 3; reasons_s.append("高週期空頭共鳴")

    # ── 流動性加成（高流動性時段額外 +1）──
    if session_liq == "high":
        if ls > ss:
            ls += 1
        elif ss > ls:
            ss += 1

    print("L:" + str(ls) + " S:" + str(ss) + " HTF:" + htf_bias, end=" ")

    if ls < MIN_SCORE and ss < MIN_SCORE:
        print("條件不足(" + str(max(ls,ss)) + "/" + str(MIN_SCORE) + ")")
        return None

    direction = "LONG" if ls >= ss else "SHORT"
    score     = ls if direction == "LONG" else ss
    reasons   = reasons_l if direction == "LONG" else reasons_s

    # ── 判斷訊號類型：順勢 or 逆勢（反轉）──
    is_counter = False
    if direction == "LONG" and htf_bias == "SHORT":
        is_counter = True
    elif direction == "SHORT" and htf_bias == "LONG":
        is_counter = True
    if divergence and ((divergence == "BULLISH" and direction == "LONG") or
                       (divergence == "BEARISH" and direction == "SHORT")):
        is_counter = True

    signal_type = "反轉" if is_counter else "順勢"

    # ── SL 計算 ──
    # 順勢用 ATR*2.5，反轉用 ATR*2.0（止損更緊）
    if atr_val > 0:
        sl_dist = atr_val * (2.0 if is_counter else 2.5)
    else:
        sl_dist = price * (0.025 if is_counter else 0.03)

    trigger = price
    if direction == "LONG":
        sl = round(trigger - sl_dist, 8)
    else:
        sl = round(trigger + sl_dist, 8)

    # ── TP 計算（風報比）──
    # 順勢：1R/2R/3R/5R，反轉：0.8R/1.5R/2.5R/4R（目標較保守）
    if is_counter:
        ratios = [0.8, 1.5, 2.5, 4.0]
    else:
        ratios = [1.0, 2.0, 3.0, 5.0]

    tps = []
    for r in ratios:
        if direction == "LONG":
            tps.append(round(trigger + sl_dist * r, 8))
        else:
            tps.append(round(trigger - sl_dist * r, 8))

    risk_pct = round(abs(sl - trigger) / trigger * 100, 2)
    role     = random.choice(ROLES[direction])

    print("-> " + direction + " [" + signal_type + "] score:" + str(score) + " " + session)

    return {
        "id":           name + "-" + tf_label + "-" + str(int(time.time())),
        "symbol":       name,
        "timeframe":    tf_label,
        "direction":    direction,
        "role":         role,
        "signal_type":  signal_type,
        "session":      session,
        "trigger":      round(trigger, 8),
        "current":      round(trigger, 8),
        "sl":           sl,
        "risk_pct":     risk_pct,
        "tp1":          tps[0],
        "tp2":          tps[1],
        "tp3":          tps[2],
        "ftp":          tps[3],
        "pnl":          0.0,
        "reached_tp":   0,
        "active":       True,
        "funding":      funding,
        "lsr":          lsr,
        "oi":           oi,
        "oi_chg":       oi_chg,
        "rsi":          rsi_val,
        "stoch_rsi":    stoch_rsi,
        "htf_bias":     htf_bias,
        "vol_ratio":    vol_ratio,
        "divergence":   divergence,
        "score":        score,
        "chg24h":       0.0,
        "long_score":   ls,
        "short_score":  ss,
        "reasons":      reasons,
        "triggered_at": tw_now(),
        "timestamp":    int(time.time()),
        "ftp_reached_at": None,
        "result":       None,
    }

# ─── 盈虧更新 ─────────────────────────────────────────────────────────────────
SYM_MAP = {
    "BTC":"BTC-USDT-SWAP","ETH":"ETH-USDT-SWAP","SOL":"SOL-USDT-SWAP",
    "DOGE":"DOGE-USDT-SWAP","BNB":"BNB-USDT-SWAP","XRP":"XRP-USDT-SWAP",
    "ADA":"ADA-USDT-SWAP","AVAX":"AVAX-USDT-SWAP","LINK":"LINK-USDT-SWAP",
    "ARB":"ARB-USDT-SWAP","OP":"OP-USDT-SWAP","MATIC":"MATIC-USDT-SWAP",
}

def update_pnl(sig):
    p = get_price(SYM_MAP.get(sig["symbol"], sig["symbol"] + "-USDT-SWAP"))
    if not p:
        return sig
    sig["current"] = p
    t = sig["trigger"]
    pnl = (p - t) / t * 100 if sig["direction"] == "LONG" else (t - p) / t * 100
    sig["pnl"] = round(pnl, 2)

    prev_reached = sig.get("reached_tp", 0)
    for i, tp in enumerate([sig["tp1"], sig["tp2"], sig["tp3"], sig["ftp"]]):
        if sig["direction"] == "LONG" and p >= tp:
            sig["reached_tp"] = i + 1
        elif sig["direction"] == "SHORT" and p <= tp:
            sig["reached_tp"] = i + 1

    if sig.get("reached_tp", 0) == 4 and prev_reached < 4:
        sig["ftp_reached_at"] = tw_now()
        sig["result"] = "WIN"
        print("  🏆 FTP達成！" + sig["symbol"] + " " + sig["timeframe"] + " " + sig.get("signal_type",""))

    if sig["direction"] == "LONG" and p <= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
    elif sig["direction"] == "SHORT" and p >= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
    return sig

# ─── GitHub 持久化 ────────────────────────────────────────────────────────────
def github_load():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return []
    try:
        import base64
        url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/data/signals.json"
        req = urllib.request.Request(url, headers={
            "Authorization": "token " + GITHUB_TOKEN,
            "User-Agent": "sentiment-lens",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            meta = json.loads(r.read())
        content = base64.b64decode(meta["content"]).decode("utf-8")
        data = json.loads(content)
        sigs = data.get("signals", [])
        print("  GitHub 載入 " + str(len(sigs)) + " 個訊號")
        return sigs
    except Exception as e:
        print("  GitHub 載入失敗: " + str(e)[:60])
        return []

def github_save(signals):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        import base64
        wins   = [s for s in signals if s.get("result") == "WIN"]
        losses = [s for s in signals if s.get("result") == "LOSS"]
        total_closed = len(wins) + len(losses)
        win_rate = round(len(wins) / total_closed * 100, 1) if total_closed > 0 else 0

        data = {
            "signals":       signals,
            "updated_at":    tw_now_full() + " (台北時間)",
            "total":         len(signals),
            "ftp_count":     sum(1 for s in signals if s.get("reached_tp", 0) == 4),
            "win_count":     len(wins),
            "loss_count":    len(losses),
            "win_rate":      win_rate,
            "trend_wins":    sum(1 for s in wins if s.get("signal_type") == "順勢"),
            "counter_wins":  sum(1 for s in wins if s.get("signal_type") == "反轉"),
        }
        content_b64 = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")

        url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/data/signals.json"
        req_get = urllib.request.Request(url, headers={
            "Authorization": "token " + GITHUB_TOKEN,
            "User-Agent": "sentiment-lens",
        })
        sha = None
        try:
            with urllib.request.urlopen(req_get, timeout=10) as r:
                sha = json.loads(r.read()).get("sha")
        except Exception:
            pass

        payload = {"message": "update " + tw_now(), "content": content_b64}
        if sha:
            payload["sha"] = sha
        req_put = urllib.request.Request(url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "token " + GITHUB_TOKEN,
                "Content-Type":  "application/json",
                "User-Agent":    "sentiment-lens",
            }, method="PUT")
        with urllib.request.urlopen(req_put, timeout=15):
            pass
        print("  GitHub 儲存完成 WIN:" + str(len(wins)) + " LOSS:" + str(len(losses)) + " 勝率:" + str(win_rate) + "%")
    except Exception as e:
        print("  GitHub 儲存失敗: " + str(e)[:80])

# ─── 防休眠 ───────────────────────────────────────────────────────────────────
def keep_alive():
    if not RENDER_URL:
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(RENDER_URL + "/health", timeout=10)
            print("  keep-alive ping OK")
        except Exception:
            pass

# ─── 掃描引擎 ─────────────────────────────────────────────────────────────────
def scan_loop():
    global signals_store, last_update
    print("掃描引擎啟動...")
    loaded = github_load()
    with store_lock:
        signals_store = loaded

    save_counter = 0

    while True:
        try:
            print("\n" + "="*50)
            print(tw_now_full() + " (台北時間) | 時段:" + get_session()[0])

            with store_lock:
                existing = list(signals_store)

            cutoff  = int(time.time()) - SIGNAL_TTL
            updated = []
            for s in existing:
                if s.get("timestamp", 0) < cutoff:
                    continue
                if s.get("active", True) and s.get("result") is None:
                    s = update_pnl(s)
                    time.sleep(0.1)
                updated.append(s)

            new_sigs     = []
            dedup_cutoff = int(time.time()) - DEDUP_SECONDS

            for name, sym in SYMBOLS:
                for tf_label, tf_bar in TIMEFRAMES:
                    skip = False
                    for s in updated:
                        if (s["symbol"] == name and
                            s["timeframe"] == tf_label and
                            s.get("timestamp", 0) > dedup_cutoff):
                            skip = True
                            break
                    if skip:
                        continue
                    sig = analyze(name, sym, tf_label, tf_bar)
                    if sig:
                        new_sigs.append(sig)
                    time.sleep(0.3)

            all_sigs = new_sigs + updated
            all_sigs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            all_sigs = all_sigs[:MAX_SIGNALS]

            now_str = tw_now_full() + " (台北時間)"
            with store_lock:
                signals_store = all_sigs
                last_update   = now_str

            save_counter += 1
            if save_counter >= 10 or len(new_sigs) > 0:
                github_save(all_sigs)
                save_counter = 0

            wins   = sum(1 for s in all_sigs if s.get("result") == "WIN")
            losses = sum(1 for s in all_sigs if s.get("result") == "LOSS")
            total  = wins + losses
            wr     = round(wins / total * 100, 1) if total > 0 else 0
            print("新增:" + str(len(new_sigs)) + " 合計:" + str(len(all_sigs)) +
                  " WIN:" + str(wins) + " LOSS:" + str(losses) + " 勝率:" + str(wr) + "%")

        except Exception as e:
            print("錯誤: " + str(e))

        time.sleep(SCAN_INTERVAL)

# ─── HTTP 伺服器 ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/signals") or self.path == "/":
            with store_lock:
                wins   = sum(1 for s in signals_store if s.get("result") == "WIN")
                losses = sum(1 for s in signals_store if s.get("result") == "LOSS")
                total  = wins + losses
                data = {
                    "signals":    signals_store,
                    "updated_at": last_update,
                    "total":      len(signals_store),
                    "ftp_count":  sum(1 for s in signals_store if s.get("reached_tp", 0) == 4),
                    "win_count":  wins,
                    "loss_count": losses,
                    "win_rate":   round(wins / total * 100, 1) if total > 0 else 0,
                }
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

class ThreadedServer(socketserver.ThreadingMixIn, HTTPServer):
    pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=scan_loop, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    server = ThreadedServer(("0.0.0.0", port), Handler)
    print("伺服器啟動 port " + str(port))
    server.serve_forever()
