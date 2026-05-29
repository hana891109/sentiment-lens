"""
Sentiment Lens - 完整優化版
根據 Trader-Alex 影片邏輯重新設計：
- 1H/4H/1D 三燈系統判斷大方向
- 只做順勢訊號（影片核心原則）
- R值保護（最小 2.5%）
- 每個幣種歷史勝率追蹤
- 目標勝率 70%、FTP 達成率 40%
"""

import json
import time
import datetime
import urllib.request
import random
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

# ═══════════════════════════════════════════════════════════
# 設定區
# ═══════════════════════════════════════════════════════════
SYMBOLS = [
    ("BTC","BTC-USDT-SWAP"),("ETH","ETH-USDT-SWAP"),("SOL","SOL-USDT-SWAP"),
    ("DOGE","DOGE-USDT-SWAP"),("BNB","BNB-USDT-SWAP"),("XRP","XRP-USDT-SWAP"),
    ("ADA","ADA-USDT-SWAP"),("AVAX","AVAX-USDT-SWAP"),("LINK","LINK-USDT-SWAP"),
    ("ARB","ARB-USDT-SWAP"),("OP","OP-USDT-SWAP"),("TRX","TRX-USDT-SWAP"),
    ("NEAR","NEAR-USDT-SWAP"),("APT","APT-USDT-SWAP"),("SUI","SUI-USDT-SWAP"),
    ("INJ","INJ-USDT-SWAP"),("FIL","FIL-USDT-SWAP"),("ATOM","ATOM-USDT-SWAP"),
]

TIMEFRAMES     = [("15M","15m"), ("1H","1H")]
SCAN_INTERVAL  = 30        # 每30秒掃描
DEDUP_SECONDS  = 14400     # 同幣同週期4小時不重複
MAX_SIGNALS    = 200       # 最多保留筆數
SIGNAL_TTL     = 7 * 24 * 3600  # 保留7天
MIN_SCORE      = 7         # 最低觸發分數（精準模式）
MIN_RISK_PCT   = 2.5       # 最小R值%（太小不做）
MIN_SL_PCT     = 0.03     # SL最小距離（價格的2.5%）

signals_store = []
store_lock    = threading.Lock()
last_update   = ""

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
RENDER_URL   = os.environ.get("RENDER_URL", "")

# ═══════════════════════════════════════════════════════════
# 時區工具
# ═══════════════════════════════════════════════════════════
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
        return "亞洲盤", "medium"
    elif 15 <= h < 22:
        return "歐洲盤", "high"
    elif 20 <= h <= 23 or 0 <= h < 4:
        return "美洲盤", "high"
    else:
        return "離市時段", "low"

# ═══════════════════════════════════════════════════════════
# HTTP 工具
# ═══════════════════════════════════════════════════════════
def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except Exception as e:
        print("  fetch err: " + str(e)[:50])
        return None

# ═══════════════════════════════════════════════════════════
# OKX API
# ═══════════════════════════════════════════════════════════
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

def get_klines(sym, bar, limit=150):
    d = fetch("https://www.okx.com/api/v5/market/candles?instId=" + sym
              + "&bar=" + bar + "&limit=" + str(limit))
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

# ═══════════════════════════════════════════════════════════
# 技術指標
# ═══════════════════════════════════════════════════════════
def calc_atr(candles, n=14):
    if len(candles) < n + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        trs.append(max(
            candles[i]["h"] - candles[i]["l"],
            abs(candles[i]["h"] - candles[i-1]["c"]),
            abs(candles[i]["l"] - candles[i-1]["c"]),
        ))
    vals = trs[-n:]
    return sum(vals) / len(vals) if vals else 0.0

def calc_rsi(candles, n=14):
    if len(candles) < n + 1:
        return 50.0
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + ag / al), 1)

def calc_ema(closes, n):
    if not closes:
        return 0.0
    if len(closes) < n:
        return closes[-1]
    k = 2.0 / (n + 1)
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

def calc_stoch_rsi(candles, rsi_n=14, stoch_n=14):
    if len(candles) < rsi_n + stoch_n + 1:
        return 50.0
    closes = [c["c"] for c in candles]
    rsi_series = []
    for i in range(rsi_n, len(closes)):
        sub = [{"c": closes[j]} for j in range(i - rsi_n, i + 1)]
        rsi_series.append(calc_rsi(sub, rsi_n))
    if len(rsi_series) < stoch_n:
        return 50.0
    recent = rsi_series[-stoch_n:]
    lo, hi = min(recent), max(recent)
    if hi == lo:
        return 50.0
    return round((rsi_series[-1] - lo) / (hi - lo) * 100, 1)

def detect_divergence(candles, lookback=20):
    if len(candles) < lookback * 2:
        return None
    half = lookback
    recent = candles[-half:]
    prev   = candles[-half*2:-half]
    rsi_r  = calc_rsi(candles[-half-14:]) if len(candles) >= half+14 else 50
    rsi_p  = calc_rsi(candles[-half*2-14:-half]) if len(candles) >= half*2+14 else 50
    price_r = recent[-1]["c"]
    price_p = prev[-1]["c"]
    price_up = price_r > price_p
    rsi_up   = rsi_r > rsi_p
    if price_up and not rsi_up and rsi_r > 60:
        return "BEARISH"
    if not price_up and rsi_up and rsi_r < 40:
        return "BULLISH"
    return None

# ═══════════════════════════════════════════════════════════
# 三燈系統（仿原版 1H/4H/1D）
# ═══════════════════════════════════════════════════════════
def get_tf_signal(sym, bar):
    """
    單一時間框架信號
    BULLISH / BEARISH / NEUTRAL / REVERSAL_UP / REVERSAL_DOWN
    """
    candles = get_klines(sym, bar, 150)
    if not candles or len(candles) < 50:
        return "NEUTRAL"

    closes = [c["c"] for c in candles]
    price  = closes[-1]
    rsi    = calc_rsi(candles)
    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200) if len(closes) >= 200 else ema50
    div    = detect_divergence(candles)

    if div == "BULLISH":
        return "REVERSAL_UP"
    if div == "BEARISH":
        return "REVERSAL_DOWN"

    # 強多頭：價格在所有均線之上，RSI > 55
    if price > ema20 > ema50 and rsi > 55:
        return "BULLISH"
    # 強空頭：價格在所有均線之下，RSI < 45
    if price < ema20 < ema50 and rsi < 45:
        return "BEARISH"

    return "NEUTRAL"

def get_three_lights(sym):
    """取得 1H/4H/1D 三燈"""
    lights = {}
    for tf, bar in [("1H","1H"), ("4H","4H"), ("1D","1D")]:
        lights[tf] = get_tf_signal(sym, bar)
        time.sleep(0.15)
    return lights

def analyze_lights(lights):
    """
    分析三燈方向和強度
    回傳 (direction, strength, is_reversal)
    strength: 0~3（幾個燈號同向）
    """
    bull = sum(1 for v in lights.values() if v in ["BULLISH","REVERSAL_UP"])
    bear = sum(1 for v in lights.values() if v in ["BEARISH","REVERSAL_DOWN"])
    rev  = any(v in ["REVERSAL_UP","REVERSAL_DOWN"] for v in lights.values())

    if bull >= 2:
        return "BULLISH", bull, rev
    if bear >= 2:
        return "BEARISH", bear, rev
    return "NEUTRAL", 0, rev

# ═══════════════════════════════════════════════════════════
# 幣種歷史勝率
# ═══════════════════════════════════════════════════════════
def get_symbol_winrate(all_signals, symbol, direction):
    related = [s for s in all_signals
               if s.get("symbol") == symbol
               and s.get("direction") == direction
               and s.get("result") in ["WIN","LOSS"]]
    if not related:
        return 0.0, 0
    wins = sum(1 for s in related if s.get("result") == "WIN")
    return round(wins / len(related) * 100, 1), len(related)

# ═══════════════════════════════════════════════════════════
# 核心訊號分析
# ═══════════════════════════════════════════════════════════
ROLES = {
    "LONG":  ["獵頭者"],
    "SHORT": ["沉思者"],
}

def analyze(name, sym, tf_label, tf_bar, all_signals):
    print("  " + name + " " + tf_label, end=" ... ")

    # ── 抓數據 ──
    price   = get_price(sym)
    if price == 0:
        print("skip(no price)")
        return None

    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bar, 150)

    if not candles or len(candles) < 30:
        print("skip(no candles)")
        return None

    closes    = [c["c"] for c in candles]
    atr_val   = calc_atr(candles)
    rsi_val   = calc_rsi(candles)
    stoch_rsi = calc_stoch_rsi(candles)
    ema20     = calc_ema(closes, 20)
    ema50     = calc_ema(closes, 50) if len(closes) >= 50 else ema20
    ema200    = calc_ema(closes, 200) if len(closes) >= 200 else ema50
    bb_u, bb_m, bb_l = calc_bb(closes)
    div       = detect_divergence(candles)
    vol_avg   = sum(c["v"] for c in candles[-21:-1]) / 20 if len(candles) > 20 else 1
    vol_ratio = round(candles[-1]["v"] / vol_avg, 2) if vol_avg > 0 else 1.0
    session, session_liq = get_session()

    # ── 三燈系統 ──
    lights = get_three_lights(sym)
    market_dir, light_strength, has_reversal = analyze_lights(lights)

    # ── 計分系統 ──
    ls = 0  # long score
    ss = 0  # short score
    reasons_l = []
    reasons_s = []

    # 層1：三燈（最重要，仿原版核心）權重最高
    if market_dir == "BULLISH":
        ls += light_strength * 2
        reasons_l.append("三燈看漲 " + str(light_strength) + "/3")
    elif market_dir == "BEARISH":
        ss += light_strength * 2
        reasons_s.append("三燈看跌 " + str(light_strength) + "/3")
    # 反轉信號額外加分
    if has_reversal:
        if market_dir == "BULLISH":
            ls += 1; reasons_l.append("含反轉結構")
        elif market_dir == "BEARISH":
            ss += 1; reasons_s.append("含反轉結構")

    # 層2：資金費率 權重2
    if funding <= -0.03:
        ls += 2; reasons_l.append("資金費率極低" + str(funding) + "%")
    elif funding <= -0.01:
        ls += 1; reasons_l.append("資金費率負值")
    if funding >= 0.06:
        ss += 2; reasons_s.append("資金費率極高" + str(funding) + "%")
    elif funding >= 0.02:
        ss += 1; reasons_s.append("資金費率偏高")

    # 層3：多空比（逆向散戶）權重2
    if lsr <= 0.75:
        ls += 2; reasons_l.append("散戶極度做空 LSR:" + str(lsr))
    elif lsr <= 0.90:
        ls += 1; reasons_l.append("多空比偏空")
    if lsr >= 1.4:
        ss += 2; reasons_s.append("散戶極度做多 LSR:" + str(lsr))
    elif lsr >= 1.15:
        ss += 1; reasons_s.append("多空比偏多")

    # 層4：RSI 權重2
    if rsi_val <= 25:
        ls += 2; reasons_l.append("RSI嚴重超賣:" + str(rsi_val))
    elif rsi_val <= 38:
        ls += 1; reasons_l.append("RSI超賣:" + str(rsi_val))
    if rsi_val >= 75:
        ss += 2; reasons_s.append("RSI嚴重超買:" + str(rsi_val))
    elif rsi_val >= 62:
        ss += 1; reasons_s.append("RSI超買:" + str(rsi_val))

    # 層5：StochRSI 權重1
    if stoch_rsi <= 15:
        ls += 1; reasons_l.append("StochRSI極度超賣:" + str(stoch_rsi))
    elif stoch_rsi <= 25:
        ls += 1
    if stoch_rsi >= 85:
        ss += 1; reasons_s.append("StochRSI極度超買:" + str(stoch_rsi))
    elif stoch_rsi >= 75:
        ss += 1

    # 層6：均線排列 權重2
    if price > ema20 > ema50:
        ls += 2; reasons_l.append("均線多頭排列")
    elif price < ema20 < ema50:
        ss += 2; reasons_s.append("均線空頭排列")

    # 層7：EMA200 大趨勢 權重1
    if price > ema200:
        ls += 1
    else:
        ss += 1

    # 層8：布林帶 權重1
    if price <= bb_l:
        ls += 1; reasons_l.append("觸碰布林下軌")
    if price >= bb_u:
        ss += 1; reasons_s.append("觸碰布林上軌")

    # 層9：RSI背離（反轉）權重2
    if div == "BULLISH":
        ls += 2; reasons_l.append("RSI看漲背離")
    elif div == "BEARISH":
        ss += 2; reasons_s.append("RSI看跌背離")

    # 層10：成交量確認 權重1
    if vol_ratio >= 2.0:
        if price > closes[-2]:
            ls += 1; reasons_l.append("成交量暴增看漲 " + str(vol_ratio) + "x")
        else:
            ss += 1; reasons_s.append("成交量暴增看跌 " + str(vol_ratio) + "x")

    # 層11：流動性時段 權重1
    if session_liq == "high":
        if ls > ss:
            ls += 1
        elif ss > ls:
            ss += 1

    print("L:" + str(ls) + " S:" + str(ss) + " " + market_dir, end=" ")

    # ── 門檻過濾 ──
    if ls < MIN_SCORE and ss < MIN_SCORE:
        print("-> 條件不足(" + str(max(ls,ss)) + "<" + str(MIN_SCORE) + ")")
        return None

    direction = "LONG" if ls >= ss else "SHORT"
    score     = ls if direction == "LONG" else ss
    reasons   = reasons_l if direction == "LONG" else reasons_s

    # ── 順勢/反轉判斷 ──
    is_counter = False
    if direction == "LONG" and market_dir == "BEARISH":
        is_counter = True
    elif direction == "SHORT" and market_dir == "BULLISH":
        is_counter = True
    if div is not None:
        is_counter = True
    signal_type = "反轉" if is_counter else "順勢"

    # ── SL 計算（確保足夠空間）──
    atr_mult = 2.0 if is_counter else 2.5
    sl_dist  = atr_val * atr_mult if atr_val > 0 else 0

    # 最小SL保護：至少 MIN_SL_PCT
    min_sl = price * MIN_SL_PCT
    if sl_dist < min_sl:
        sl_dist = min_sl

    trigger  = price
    sl       = round(trigger - sl_dist if direction == "LONG" else trigger + sl_dist, 8)
    risk_pct = round(abs(sl - trigger) / trigger * 100, 2)

    # ── R值過濾 ──
    if risk_pct < MIN_RISK_PCT:
        print("-> R值不足(" + str(risk_pct) + "%)")
        return None

    # ── TP 計算 ──
    # 順勢：1R/2R/3R/5R
    # 反轉：1R/1.5R/2.5R/4R（目標保守）
    ratios = [1.0, 1.5, 2.5, 4.0] if is_counter else [1.0, 2.0, 3.0, 5.0]
    tps = []
    for r in ratios:
        if direction == "LONG":
            tps.append(round(trigger + sl_dist * r, 8))
        else:
            tps.append(round(trigger - sl_dist * r, 8))

    # ── 歷史勝率 ──
    sym_wr, sym_count = get_symbol_winrate(all_signals, name, direction)

    role = random.choice(ROLES[direction])
    print("-> " + direction + "[" + signal_type + "] R:" + str(risk_pct) + "% score:" + str(score))

    return {
        "id":             name + "-" + tf_label + "-" + str(int(time.time())),
        "symbol":         name,
        "timeframe":      tf_label,
        "direction":      direction,
        "role":           role,
        "signal_type":    signal_type,
        "session":        session,
        "trigger":        round(trigger, 8),
        "current":        round(trigger, 8),
        "sl":             sl,
        "risk_pct":       risk_pct,
        "tp1":            tps[0],
        "tp2":            tps[1],
        "tp3":            tps[2],
        "ftp":            tps[3],
        "pnl":            0.0,
        "reached_tp":     0,
        "active":         True,
        "funding":        funding,
        "lsr":            lsr,
        "oi":             oi,
        "rsi":            rsi_val,
        "stoch_rsi":      stoch_rsi,
        "market_bias":    market_dir,
        "lights":         lights,
        "light_strength": light_strength,
        "vol_ratio":      vol_ratio,
        "divergence":     div,
        "score":          score,
        "long_score":     ls,
        "short_score":    ss,
        "reasons":        reasons,
        "sym_win_rate":   sym_wr,
        "sym_count":      sym_count,
        "chg24h":         0.0,
        "triggered_at":   tw_now(),
        "timestamp":      int(time.time()),
        "ftp_reached_at": None,
        "result":         None,
    }

# ═══════════════════════════════════════════════════════════
# 盈虧更新
# ═══════════════════════════════════════════════════════════
SYM_MAP = {
    "BTC":"BTC-USDT-SWAP","ETH":"ETH-USDT-SWAP","SOL":"SOL-USDT-SWAP",
    "DOGE":"DOGE-USDT-SWAP","BNB":"BNB-USDT-SWAP","XRP":"XRP-USDT-SWAP",
    "ADA":"ADA-USDT-SWAP","AVAX":"AVAX-USDT-SWAP","LINK":"LINK-USDT-SWAP",
    "ARB":"ARB-USDT-SWAP","OP":"OP-USDT-SWAP","TRX":"TRX-USDT-SWAP",
    "NEAR":"NEAR-USDT-SWAP","APT":"APT-USDT-SWAP","SUI":"SUI-USDT-SWAP",
    "INJ":"INJ-USDT-SWAP","FIL":"FIL-USDT-SWAP","ATOM":"ATOM-USDT-SWAP",
}

def update_pnl(sig):
    p = get_price(SYM_MAP.get(sig["symbol"], sig["symbol"] + "-USDT-SWAP"))
    if not p:
        return sig
    sig["current"] = p
    t   = sig["trigger"]
    pnl = (p-t)/t*100 if sig["direction"]=="LONG" else (t-p)/t*100
    sig["pnl"] = round(pnl, 2)

    prev_tp = sig.get("reached_tp", 0)
    for i, tp in enumerate([sig["tp1"],sig["tp2"],sig["tp3"],sig["ftp"]]):
        if sig["direction"]=="LONG" and p >= tp:
            sig["reached_tp"] = i + 1
        elif sig["direction"]=="SHORT" and p <= tp:
            sig["reached_tp"] = i + 1

    if sig.get("reached_tp",0) == 4 and prev_tp < 4:
        sig["ftp_reached_at"] = tw_now()
        sig["result"] = "WIN"
        print("  🏆 FTP！" + sig["symbol"] + " " + sig["direction"] +
              " pnl:" + str(sig["pnl"]) + "%")

    if sig["direction"]=="LONG" and p <= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
            print("  ❌ 止損 " + sig["symbol"] + " pnl:" + str(sig["pnl"]) + "%")
    elif sig["direction"]=="SHORT" and p >= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
            print("  ❌ 止損 " + sig["symbol"] + " pnl:" + str(sig["pnl"]) + "%")
    return sig

# ═══════════════════════════════════════════════════════════
# GitHub 持久化儲存
# ═══════════════════════════════════════════════════════════
def github_load():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  未設定GitHub，跳過載入")
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
        sigs = json.loads(content).get("signals", [])
        print("  GitHub載入 " + str(len(sigs)) + " 筆訊號")
        return sigs
    except Exception as e:
        print("  GitHub載入失敗: " + str(e)[:60])
        return []

def github_save(signals):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        import base64
        wins    = [s for s in signals if s.get("result") == "WIN"]
        losses  = [s for s in signals if s.get("result") == "LOSS"]
        closed  = len(wins) + len(losses)
        wr      = round(len(wins)/closed*100, 1) if closed > 0 else 0.0

        # 各幣種統計
        sym_stats = {}
        for s in signals:
            if s.get("result") not in ["WIN","LOSS"]:
                continue
            key = s["symbol"] + "_" + s["direction"]
            if key not in sym_stats:
                sym_stats[key] = {"wins":0,"losses":0,"pnl":0.0}
            if s["result"] == "WIN":
                sym_stats[key]["wins"] += 1
            else:
                sym_stats[key]["losses"] += 1
            sym_stats[key]["pnl"] = round(sym_stats[key]["pnl"] + s.get("pnl",0), 2)

        data = {
            "signals":      signals,
            "updated_at":   tw_now_full() + " (台北時間)",
            "total":        len(signals),
            "active":       sum(1 for s in signals if s.get("active",True) and not s.get("result")),
            "ftp_count":    sum(1 for s in signals if s.get("reached_tp",0)==4),
            "win_count":    len(wins),
            "loss_count":   len(losses),
            "win_rate":     wr,
            "trend_wins":   sum(1 for s in wins if s.get("signal_type")=="順勢"),
            "counter_wins": sum(1 for s in wins if s.get("signal_type")=="反轉"),
            "sym_stats":    sym_stats,
        }

        content_b64 = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("utf-8")

        url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/data/signals.json"
        sha = None
        try:
            req_get = urllib.request.Request(url, headers={
                "Authorization": "token " + GITHUB_TOKEN,
                "User-Agent": "sentiment-lens",
            })
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
        with urllib.request.urlopen(req_put, timeout=20):
            pass
        print("  GitHub儲存完成 勝率:" + str(wr) + "% W:" + str(len(wins)) + " L:" + str(len(losses)))
    except Exception as e:
        print("  GitHub儲存失敗: " + str(e)[:80])

# ═══════════════════════════════════════════════════════════
# 防休眠
# ═══════════════════════════════════════════════════════════
def keep_alive():
    if not RENDER_URL:
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(RENDER_URL + "/health", timeout=10)
            print("  keep-alive OK")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════
# 主掃描引擎
# ═══════════════════════════════════════════════════════════
def scan_loop():
    global signals_store, last_update
    print("=" * 55)
    print("  Sentiment Lens 掃描引擎啟動")
    print("=" * 55)

    loaded = github_load()
    with store_lock:
        signals_store = loaded

    save_counter = 0

    while True:
        try:
            print("\n" + "─" * 55)
            sn, _ = get_session()
            print(tw_now_full() + " (台北) | " + sn)

            with store_lock:
                existing = list(signals_store)

            # 清除過期訊號
            cutoff  = int(time.time()) - SIGNAL_TTL
            updated = []
            for s in existing:
                if s.get("timestamp", 0) < cutoff:
                    continue
                if s.get("active", True) and s.get("result") is None:
                    s = update_pnl(s)
                    time.sleep(0.1)
                updated.append(s)

            # 掃描新訊號
            new_sigs     = []
            dedup_cutoff = int(time.time()) - DEDUP_SECONDS

            for name, sym in SYMBOLS:
                for tf_label, tf_bar in TIMEFRAMES:
                    # 去重檢查
                    already = any(
                        s["symbol"] == name and
                        s["timeframe"] == tf_label and
                        s.get("timestamp", 0) > dedup_cutoff
                        for s in updated
                    )
                    if already:
                        continue

                    sig = analyze(name, sym, tf_label, tf_bar, updated)
                    if sig:
                        new_sigs.append(sig)
                    time.sleep(0.3)

            all_sigs = new_sigs + updated
            all_sigs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            all_sigs = all_sigs[:MAX_SIGNALS]

            with store_lock:
                signals_store = all_sigs
                last_update   = tw_now_full() + " (台北時間)"

            # 定期存入GitHub
            save_counter += 1
            if save_counter >= 10 or len(new_sigs) > 0:
                github_save(all_sigs)
                save_counter = 0

            # 統計輸出
            wins   = sum(1 for s in all_sigs if s.get("result") == "WIN")
            losses = sum(1 for s in all_sigs if s.get("result") == "LOSS")
            active = sum(1 for s in all_sigs if s.get("active",True) and not s.get("result"))
            closed = wins + losses
            wr     = round(wins/closed*100, 1) if closed > 0 else 0
            print("新增:" + str(len(new_sigs)) +
                  " 活躍:" + str(active) +
                  " 合計:" + str(len(all_sigs)) +
                  " W:" + str(wins) +
                  " L:" + str(losses) +
                  " 勝率:" + str(wr) + "%")

        except Exception as e:
            print("掃描錯誤: " + str(e))

        time.sleep(SCAN_INTERVAL)

# ═══════════════════════════════════════════════════════════
# HTTP API 伺服器
# ═══════════════════════════════════════════════════════════
class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/signals") or self.path == "/":
            with store_lock:
                wins   = sum(1 for s in signals_store if s.get("result") == "WIN")
                losses = sum(1 for s in signals_store if s.get("result") == "LOSS")
                active = sum(1 for s in signals_store if s.get("active",True) and not s.get("result"))
                closed = wins + losses
                data   = {
                    "signals":      signals_store,
                    "updated_at":   last_update,
                    "total":        len(signals_store),
                    "active_count": active,
                    "ftp_count":    sum(1 for s in signals_store if s.get("reached_tp",0)==4),
                    "win_count":    wins,
                    "loss_count":   losses,
                    "win_rate":     round(wins/closed*100,1) if closed > 0 else 0,
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

# ═══════════════════════════════════════════════════════════
# 啟動
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=scan_loop, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    server = ThreadedServer(("0.0.0.0", port), Handler)
    print("API伺服器啟動 port:" + str(port))
    server.serve_forever()
