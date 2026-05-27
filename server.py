import json
import time
import datetime
import urllib.request
import urllib.parse
import random
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

SYMBOLS = [
    ("BTC","BTC-USDT-SWAP"),("ETH","ETH-USDT-SWAP"),("SOL","SOL-USDT-SWAP"),
    ("DOGE","DOGE-USDT-SWAP"),("BNB","BNB-USDT-SWAP"),("XRP","XRP-USDT-SWAP"),
    ("ADA","ADA-USDT-SWAP"),("AVAX","AVAX-USDT-SWAP"),("LINK","LINK-USDT-SWAP"),
    ("ARB","ARB-USDT-SWAP"),
]
TIMEFRAMES    = [("15M","15m"),("1H","1H")]
SCAN_INTERVAL = 30
MAX_SIGNALS   = 200
SIGNAL_TTL    = 7 * 24 * 3600  # 保留 7 天
signals_store = []
store_lock    = threading.Lock()
last_update   = ""

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
RENDER_URL   = os.environ.get("RENDER_URL", "")

TW_OFFSET = 8 * 3600

def tw_now():
    utc = datetime.datetime.utcnow()
    tw  = utc + datetime.timedelta(hours=8)
    return tw.strftime("%Y/%m/%d %H:%M")

def tw_now_full():
    utc = datetime.datetime.utcnow()
    tw  = utc + datetime.timedelta(hours=8)
    return tw.strftime("%Y/%m/%d %H:%M:%S")

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print("err: " + str(e)[:60])
        return None

def get_price(sym):
    d = fetch("https://www.okx.com/api/v5/market/ticker?instId=" + sym)
    if d and d.get("data"):
        return float(d["data"][0]["last"])
    return 0.0

def get_funding(sym):
    d = fetch("https://www.okx.com/api/v5/public/funding-rate?instId=" + sym)
    if d and d.get("data"):
        return round(float(d["data"][0]["fundingRate"])*100, 4)
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
            return round(float(d["data"][0][1])/1000000, 2)
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
            result.append({"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),"v":float(c[5])})
        except Exception:
            pass
    return result

def calc_atr(candles, n=14):
    if len(candles) < n+1:
        return 0
    trs = []
    for i in range(1, len(candles)):
        trs.append(max(
            candles[i]["h"]-candles[i]["l"],
            abs(candles[i]["h"]-candles[i-1]["c"]),
            abs(candles[i]["l"]-candles[i-1]["c"])
        ))
    vals = trs[-n:]
    return sum(vals)/len(vals) if vals else 0

def calc_rsi(candles, n=14):
    if len(candles) < n+1:
        return 50
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    if al == 0:
        return 100
    return round(100 - 100/(1+ag/al), 1)

def calc_ema(closes, n):
    if len(closes) < n:
        return closes[-1] if closes else 0
    k = 2/(n+1)
    e = sum(closes[:n])/n
    for v in closes[n:]:
        e = v*k + e*(1-k)
    return e

def calc_bb(closes, n=20):
    if len(closes) < n:
        mid = closes[-1]
        return mid, mid, mid
    recent = closes[-n:]
    mid = sum(recent)/n
    std = (sum((x-mid)**2 for x in recent)/n)**0.5
    return round(mid+2*std,8), round(mid,8), round(mid-2*std,8)

def get_htf_bias(sym):
    scores = {"LONG":0, "SHORT":0}
    for bar in ["1H","4H"]:
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
        if rsi > 50:
            scores["LONG"] += 1
        else:
            scores["SHORT"] += 1
        time.sleep(0.1)
    if scores["LONG"] > scores["SHORT"]:
        return "LONG"
    if scores["SHORT"] > scores["LONG"]:
        return "SHORT"
    return "NEUTRAL"

ROLES = {
    "LONG":  ["獵頭者","先鋒者","衝鋒者"],
    "SHORT": ["沉思者","獵空者","伏擊者"],
}

def analyze(name, sym, tf_label, tf_bar):
    print("  " + name + " " + tf_label, end=" ")
    price   = get_price(sym)
    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bar, 100)
    if not candles or price == 0:
        print("skip")
        return None
    closes    = [c["c"] for c in candles]
    atr_val   = calc_atr(candles)
    rsi_val   = calc_rsi(candles)
    ema20     = calc_ema(closes, 20)
    ema50     = calc_ema(closes, 50) if len(closes) >= 50 else ema20
    bb_u, bb_m, bb_l = calc_bb(closes)
    vol_avg   = sum(c["v"] for c in candles[-21:-1]) / 20 if len(candles) > 20 else 1
    vol_ratio = round(candles[-1]["v"] / vol_avg, 2) if vol_avg > 0 else 1.0
    htf_bias  = get_htf_bias(sym)
    ls = 0
    ss = 0
    reasons_l = []
    reasons_s = []
    if funding <= -0.02:
        ls += 2; reasons_l.append("資金費率極低"+str(funding)+"%")
    elif funding < 0:
        ls += 1
    if funding >= 0.05:
        ss += 2; reasons_s.append("資金費率極高"+str(funding)+"%")
    elif funding > 0:
        ss += 1
    if lsr <= 0.8:
        ls += 2; reasons_l.append("散戶極度做空 LSR:"+str(lsr))
    elif lsr <= 0.95:
        ls += 1
    if lsr >= 1.3:
        ss += 2; reasons_s.append("散戶極度做多 LSR:"+str(lsr))
    elif lsr >= 1.1:
        ss += 1
    if rsi_val <= 30:
        ls += 2; reasons_l.append("RSI超賣:"+str(rsi_val))
    elif rsi_val <= 45:
        ls += 1
    if rsi_val >= 70:
        ss += 2; reasons_s.append("RSI超買:"+str(rsi_val))
    elif rsi_val >= 55:
        ss += 1
    if price > ema20 > ema50:
        ls += 2; reasons_l.append("均線多頭排列")
    elif price < ema20 < ema50:
        ss += 2; reasons_s.append("均線空頭排列")
    if price <= bb_l:
        ls += 1; reasons_l.append("觸碰布林下軌")
    if price >= bb_u:
        ss += 1; reasons_s.append("觸碰布林上軌")
    if vol_ratio >= 1.5:
        if price > closes[-2]:
            ls += 1
        else:
            ss += 1
    if htf_bias == "LONG":
        ls += 3; reasons_l.append("高週期多頭共鳴")
    elif htf_bias == "SHORT":
        ss += 3; reasons_s.append("高週期空頭共鳴")
    print("L:"+str(ls)+" S:"+str(ss)+" HTF:"+htf_bias, end=" ")
    if ls < 5 and ss < 5:
        print("條件不足")
        return None
    direction = "LONG" if ls >= ss else "SHORT"
    sl_dist   = atr_val*2.0 if atr_val > 0 else price*0.025
    trigger   = price
    sl        = round(trigger-sl_dist if direction=="LONG" else trigger+sl_dist, 8)
    tps       = [round(trigger+sl_dist*r if direction=="LONG" else trigger-sl_dist*r, 8) for r in [1,2,3,5]]
    risk_pct  = round(abs(sl-trigger)/trigger*100, 2)
    score     = ls if direction=="LONG" else ss
    reasons   = reasons_l if direction=="LONG" else reasons_s
    role      = random.choice(ROLES[direction])
    print("-> " + direction + " score:" + str(score))
    return {
        "id": name+"-"+tf_label+"-"+str(int(time.time())),
        "symbol": name, "timeframe": tf_label, "direction": direction, "role": role,
        "trigger": round(trigger,8), "current": round(trigger,8), "sl": sl,
        "risk_pct": risk_pct, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2], "ftp": tps[3],
        "pnl": 0.0, "reached_tp": 0, "active": True,
        "funding": funding, "lsr": lsr, "oi": oi, "rsi": rsi_val,
        "htf_bias": htf_bias, "vol_ratio": vol_ratio, "score": score, "chg24h": 0.0,
        "long_score": ls, "short_score": ss, "reasons": reasons,
        "triggered_at": tw_now(),
        "timestamp": int(time.time()),
        "ftp_reached_at": None,
        "result": None,
    }

SYM_MAP = {
    "BTC":"BTC-USDT-SWAP","ETH":"ETH-USDT-SWAP","SOL":"SOL-USDT-SWAP",
    "DOGE":"DOGE-USDT-SWAP","BNB":"BNB-USDT-SWAP","XRP":"XRP-USDT-SWAP",
    "ADA":"ADA-USDT-SWAP","AVAX":"AVAX-USDT-SWAP","LINK":"LINK-USDT-SWAP",
    "ARB":"ARB-USDT-SWAP",
}

def update_pnl(sig):
    p = get_price(SYM_MAP.get(sig["symbol"], sig["symbol"]+"-USDT-SWAP"))
    if not p:
        return sig
    sig["current"] = p
    t = sig["trigger"]
    pnl = (p-t)/t*100 if sig["direction"]=="LONG" else (t-p)/t*100
    sig["pnl"] = round(pnl, 2)
    prev_reached = sig.get("reached_tp", 0)
    for i, tp in enumerate([sig["tp1"],sig["tp2"],sig["tp3"],sig["ftp"]]):
        if sig["direction"]=="LONG" and p >= tp:
            sig["reached_tp"] = i+1
        elif sig["direction"]=="SHORT" and p <= tp:
            sig["reached_tp"] = i+1
    if sig.get("reached_tp",0) == 4 and prev_reached < 4:
        sig["ftp_reached_at"] = tw_now()
        sig["result"] = "WIN"
        print("  🏆 FTP 達成！" + sig["symbol"] + " " + sig["timeframe"])
    if sig["direction"]=="LONG" and p <= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
    elif sig["direction"]=="SHORT" and p >= sig["sl"]:
        sig["active"] = False
        if not sig.get("result"):
            sig["result"] = "LOSS"
    return sig

# ─── GitHub 持久化儲存 ────────────────────────────────────────────────────────
def github_load():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("  GitHub 未設定，跳過載入")
        return []
    try:
        url = "https://api.github.com/repos/" + GITHUB_REPO + "/contents/data/signals.json"
        req = urllib.request.Request(url, headers={
            "Authorization": "token " + GITHUB_TOKEN,
            "User-Agent": "sentiment-lens",
        })
        with urllib.request.urlopen(req, timeout=10) as r:
            meta = json.loads(r.read())
        import base64
        content = base64.b64decode(meta["content"]).decode("utf-8")
        data = json.loads(content)
        sigs = data.get("signals", [])
        print("  從 GitHub 載入 " + str(len(sigs)) + " 個訊號")
        return sigs
    except Exception as e:
        print("  GitHub 載入失敗: " + str(e)[:60])
        return []

def github_save(signals):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        import base64
        data = {
            "signals":    signals,
            "updated_at": tw_now_full() + " (台北時間)",
            "total":      len(signals),
            "ftp_count":  sum(1 for s in signals if s.get("reached_tp",0)==4),
            "win_count":  sum(1 for s in signals if s.get("result")=="WIN"),
            "loss_count": sum(1 for s in signals if s.get("result")=="LOSS"),
        }
        content_str  = json.dumps(data, ensure_ascii=False, indent=2)
        content_b64  = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
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
        payload = {"message": "update signals " + tw_now(), "content": content_b64}
        if sha:
            payload["sha"] = sha
        body = json.dumps(payload).encode("utf-8")
        req_put = urllib.request.Request(url, data=body, headers={
            "Authorization": "token " + GITHUB_TOKEN,
            "Content-Type":  "application/json",
            "User-Agent":    "sentiment-lens",
        }, method="PUT")
        with urllib.request.urlopen(req_put, timeout=15) as r:
            pass
        print("  已儲存到 GitHub")
    except Exception as e:
        print("  GitHub 儲存失敗: " + str(e)[:80])

# ─── 防休眠 ping ──────────────────────────────────────────────────────────────
def keep_alive():
    if not RENDER_URL:
        return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(RENDER_URL + "/health", timeout=10)
            print("  ping 成功，保持活躍")
        except Exception:
            pass

# ─── 掃描引擎 ─────────────────────────────────────────────────────────────────
def scan_loop():
    global signals_store, last_update
    print("掃描引擎啟動...")
    loaded = github_load()
    with store_lock:
        signals_store = loaded

    while True:
        try:
            print("\n" + "="*50)
            print(tw_now_full() + " (台北時間)")
            with store_lock:
                existing = list(signals_store)
            cutoff  = int(time.time()) - SIGNAL_TTL
            updated = []
            for s in existing:
                if s.get("timestamp",0) < cutoff:
                    continue
                if s.get("active", True) and s.get("result") is None:
                    s = update_pnl(s)
                    time.sleep(0.1)
                updated.append(s)
            new_sigs     = []
            dedup_cutoff = int(time.time()) - 1800
            for name, sym in SYMBOLS:
                for tf_label, tf_bar in TIMEFRAMES:
                    skip = False
                    for s in updated:
                        if s["symbol"]==name and s["timeframe"]==tf_label and s.get("timestamp",0)>dedup_cutoff:
                            skip = True
                            break
                    if skip:
                        continue
                    sig = analyze(name, sym, tf_label, tf_bar)
                    if sig:
                        new_sigs.append(sig)
                    time.sleep(0.3)
            all_sigs = new_sigs + updated
            all_sigs.sort(key=lambda x: x.get("timestamp",0), reverse=True)
            all_sigs = all_sigs[:MAX_SIGNALS]
            now_str = tw_now_full() + " (台北時間)"
            with store_lock:
                signals_store = all_sigs
                last_update   = now_str
            github_save(all_sigs)
            print("新增"+str(len(new_sigs))+" 合計"+str(len(all_sigs)))
        except Exception as e:
            print("錯誤: " + str(e))
        time.sleep(SCAN_INTERVAL)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    def do_GET(self):
        if self.path.startswith("/signals") or self.path == "/":
            with store_lock:
                data = {
                    "signals":    signals_store,
                    "updated_at": last_update,
                    "total":      len(signals_store),
                    "ftp_count":  sum(1 for s in signals_store if s.get("reached_tp",0)==4),
                    "win_count":  sum(1 for s in signals_store if s.get("result")=="WIN"),
                    "loss_count": sum(1 for s in signals_store if s.get("result")=="LOSS"),
                }
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Access-Control-Allow-Headers","*")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","*")
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
