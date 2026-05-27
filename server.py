import json
import time
import datetime
import urllib.request
import random
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver

SYMBOLS = [
    ("BTC", "BTC-USDT-SWAP"),
    ("ETH", "ETH-USDT-SWAP"),
    ("SOL", "SOL-USDT-SWAP"),
    ("DOGE","DOGE-USDT-SWAP"),
    ("BNB", "BNB-USDT-SWAP"),
    ("XRP", "XRP-USDT-SWAP"),
    ("ADA", "ADA-USDT-SWAP"),
    ("AVAX","AVAX-USDT-SWAP"),
    ("LINK","LINK-USDT-SWAP"),
    ("ARB", "ARB-USDT-SWAP"),
]

TIMEFRAMES    = [("15M","15m"),("1H","1H")]
SCAN_INTERVAL = 30
MAX_SIGNALS   = 80
SIGNAL_TTL    = 48 * 3600

signals_store = []
store_lock    = threading.Lock()
last_update   = ""

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
    if d and d.get("data"): return float(d["data"][0]["last"])
    return 0.0

def get_funding(sym):
    d = fetch("https://www.okx.com/api/v5/public/funding-rate?instId=" + sym)
    if d and d.get("data"): return round(float(d["data"][0]["fundingRate"])*100, 4)
    return 0.0

def get_lsr(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=" + ccy + "&period=5m")
    if d and d.get("data") and len(d["data"]) > 0:
        try: return round(float(d["data"][0][1]), 2)
        except: return 1.0
    return 1.0

def get_oi(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=" + ccy + "&period=5m")
    if d and d.get("data") and len(d["data"]) > 0:
        try: return round(float(d["data"][0][1])/1000000, 2)
        except: return 0.0
    return 0.0

def get_klines(sym, bar, limit=100):
    d = fetch("https://www.okx.com/api/v5/market/candles?instId=" + sym + "&bar=" + bar + "&limit=" + str(limit))
    if not d or not d.get("data"): return []
    result = []
    for c in reversed(d["data"]):
        try: result.append({"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),"v":float(c[5])})
        except: pass
    return result

def calc_atr(candles, n=14):
    if len(candles) < n+1: return 0
    trs = [max(candles[i]["h"]-candles[i]["l"], abs(candles[i]["h"]-candles[i-1]["c"]), abs(candles[i]["l"]-candles[i-1]["c"])) for i in range(1,len(candles))]
    vals = trs[-n:]
    return sum(vals)/len(vals) if vals else 0

def calc_rsi(candles, n=14):
    if len(candles) < n+1: return 50
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-n:])/n
    al = sum(losses[-n:])/n
    return round(100-100/(1+ag/al),1) if al!=0 else 100

def calc_ema(closes, n):
    if len(closes) < n: return closes[-1] if closes else 0
    k = 2/(n+1)
    e = sum(closes[:n])/n
    for v in closes[n:]: e = v*k + e*(1-k)
    return e

def calc_bb(closes, n=20):
    if len(closes) < n: mid=closes[-1]; return mid,mid,mid
    recent = closes[-n:]
    mid = sum(recent)/n
    std = (sum((x-mid)**2 for x in recent)/n)**0.5
    return round(mid+2*std,8), round(mid,8), round(mid-2*std,8)

def get_htf_bias(sym):
    scores = {"LONG":0,"SHORT":0}
    for bar in ["1H","4H"]:
        candles = get_klines(sym, bar, 60)
        if not candles or len(candles) < 30: continue
        closes = [c["c"] for c in candles]
        rsi    = calc_rsi(candles)
        ema20  = calc_ema(closes, 20)
        ema50  = calc_ema(closes, 50) if len(closes)>=50 else ema20
        price  = closes[-1]
        if price > ema20 > ema50: scores["LONG"] += 2
        elif price < ema20 < ema50: scores["SHORT"] += 2
        if rsi > 50: scores["LONG"] += 1
        else: scores["SHORT"] += 1
        time.sleep(0.1)
    if scores["LONG"] > scores["SHORT"]: return "LONG"
    if scores["SHORT"] > scores["LONG"]: return "SHORT"
    return "NEUTRAL"

ROLES = {"LONG":["獵頭者","先鋒者","衝鋒者"],"SHORT":["沉思者","獵空者","伏擊者"]}

def analyze(name, sym, tf_label, tf_bar):
    print("  " + name + " " + tf_label, end=" ")
    price   = get_price(sym)
    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bar, 100)
    if not candles or price == 0: print("skip"); return None

    closes   = [c["c"] for c in candles]
    atr_val  = calc_atr(candles)
    rsi_val  = calc_rsi(candles)
    ema20    = calc_ema(closes, 20)
    ema50    = calc_ema(closes, 50) if len(closes)>=50 else ema20
    bb_u, bb_m, bb_l = calc_bb(closes)
    vol_ratio = round(candles[-1]["v"] / (sum(c["v"] for c in candles[-21:-1])/20), 2) if len(candles)>20 else 1.0
    htf_bias = get_htf_bias(sym)

    ls = ss = 0
    reasons_l = []
    reasons_s = []

    if funding <= -0.02: ls+=2; reasons_l.append("資金費率極低"+str(funding)+"%")
    elif funding < 0: ls+=1
    if funding >= 0.05: ss+=2; reasons_s.append("資金費率極高"+str(funding)+"%")
    elif funding > 0: ss+=1

    if lsr <= 0.8: ls+=2; reasons_l.append("散戶極度做空 LSR:"+str(lsr))
    elif lsr <= 0.95: ls+=1
    if lsr >= 1.3: ss+=2; reasons_s.append("散戶極度做多 LSR:"+str(lsr))
    elif lsr >= 1.1: ss+=1

    if rsi_val <= 30: ls+=2; reasons_l.append("RSI超賣:"+str(rsi_val))
    elif rsi_val <= 45: ls+=1
    if rsi_val >= 70: ss+=2; reasons_s.append("RSI超買:"+str(rsi_val))
    elif rsi_val >= 55: ss+=1

    if price > ema20 > ema50: ls+=2; reasons_l.append("均線多頭排列")
    elif price < ema20 < ema50: ss+=2; reasons_s.append("均線空頭排列")

    if price <= bb_l: ls+=1; reasons_l.append("觸碰布林下軌")
    if price >= bb_u: ss+=1; reasons_s.append("觸碰布林上軌")

    if vol_ratio >= 1.5:
        if price > closes[-2]: ls+=1
        else: ss+=1

    if htf_bias == "LONG": ls+=3; reasons_l.append("高週期多頭共鳴")
    elif htf_bias == "SHORT": ss+=3; reasons_s.append("高週期空頭共鳴")

    print("L:"+str(ls)+" S:"+str(ss)+" HTF:"+htf_bias, end=" ")

    if ls < 5 and ss < 5: print("條件不足"); return None

    direction = "LONG" if ls >= ss else "SHORT"
    sl_dist   = atr_val*2.0 if atr_val>0 else price*0.025
    trigger   = price
    sl        = round(trigger-sl_dist if direction=="LONG" else trigger+sl_dist, 8)
    tps       = [round(trigger+sl_dist*r if direction=="LONG" else trigger-sl_dist*r, 8) for r in [1,2,3,5]]
    risk_pct  = round(abs(sl-trigger)/trigger*100, 2)
    score     = ls if direction=="LONG" else ss
    reasons   = reasons_l if direction=="LONG" else reasons_s
    role      = random.choice(ROLES[direction])
    now_str   = datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M")

    print("-> " + direction + " score:" + str(score))
    return {
        "id":sym+"-"+tf_label+"-"+str(int(time.time())),
        "symbol":name,"timeframe":tf_label,"direction":direction,"role":role,
        "trigger":round(trigger,8),"current":round(trigger,8),"sl":sl,
        "risk_pct":risk_pct,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"ftp":tps[3],
        "pnl":0.0,"reached_tp":0,"active":True,"funding":funding,"lsr":lsr,"oi":oi,
        "rsi":rsi_val,"htf_bias":htf_bias,"vol_ratio":vol_ratio,"score":score,
        "chg24h":0.0,"long_score":ls,"short_score":ss,"reasons":reasons,
        "triggered_at":now_str,"timestamp":int(time.time()),
    }

def update_pnl(sig):
    sym_map = {"BTC":"BTC-USDT-SWAP","ETH":"ETH-USDT-SWAP","SOL":"SOL-USDT-SWAP","DOGE":"DOGE-USDT-SWAP","BNB":"BNB-USDT-SWAP","XRP":"XRP-USDT-SWAP","ADA":"ADA-USDT-SWAP","AVAX":"AVAX-USDT-SWAP","LINK":"LINK-USDT-SWAP","ARB":"ARB-USDT-SWAP"}
    p = get_price(sym_map.get(sig["symbol"], sig["symbol"]+"-USDT-SWAP"))
    if not p: return sig
    sig["current"] = p
    t = sig["trigger"]
    pnl = (p-t)/t*100 if sig["direction"]=="LONG" else (t-p)/t*100
    sig["pnl"] = round(pnl,2)
    for i,tp in enumerate([sig["tp1"],sig["tp2"],sig["tp3"],sig["ftp"]]):
        if (sig["direction"]=="LONG" and p>=tp) or (sig["direction"]=="SHORT" and p<=tp): sig["reached_tp"]=i+1
    if (sig["direction"]=="LONG" and p<=sig["sl"]) or (sig["direction"]=="SHORT" and p>=sig["sl"]): sig["active"]=False
    return sig

def scan_loop():
    global signals_store, last_update
    print("掃描引擎啟動...")
    while True:
        try:
            print("\n" + "="*50)
            print(datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC"))
            with store_lock: existing = list(signals_store)
            cutoff  = int(time.time()) - SIGNAL_TTL
            updated = []
            for s in existing:
                if s.get("timestamp",0) < cutoff: continue
                if s.get("active",True): s=update_pnl(s); time.sleep(0.1)
                updated.append(s)
            new_sigs     = []
            dedup_cutoff = int(time.time()) - 1800
            for name,sym in SYMBOLS:
                for tf_label,tf_bar in TIMEFRAMES:
                    if any(s["symbol"]==name and s["timeframe"]==tf_label and s.get("timestamp",0)>dedup_cutoff for s in updated): continue
                    sig = analyze(name,sym,tf_label,tf_bar)
                    if sig: new_sigs.append(sig)
                    time.sleep(0.3)
            all_sigs = sorted(new_sigs+updated, key=lambda x:x.get("timestamp",0), reverse=True)[:MAX_SIGNALS]
            now_str  = datetime.datetime.utcnow().strftime("%Y/%m/%d %H:%M:%S UTC")
            with store_lock: signals_store=all_sigs; last_update=now_str
            print("新增"+str(len(new_sigs))+" 合計"+str(len(all_sigs)))
        except Exception as e:
            print("錯誤: "+str(e))
        time.sleep(SCAN_INTERVAL)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
    def do_GET(self):
        if self.path in ["/signals","/"]:
            with store_lock: data={"signals":signals_store,"updated_at":last_update,"total":len(signals_store)}
            body = json.dumps(data,ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin","*")
            self.send_header("Access-Control-Allow-Headers","*")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path=="/health":
            self.send_response(200); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","*")
        self.end_headers()

class ThreadedServer(socketserver.ThreadingMixIn, HTTPServer): pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=scan_loop, daemon=True).start()
    server = ThreadedServer(("0.0.0.0", port), Handler)
    print("伺服器啟動 port " + str(port))
    server.serve_forever()
