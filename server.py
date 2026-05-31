"""
Sentiment Lens - 合併版伺服器
波段訊號：/signals
日內訊號：/intraday
同一個 Render 服務，兩個獨立掃描引擎
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
# 共用設定
# ═══════════════════════════════════════════════════════════
SYMBOLS = [
    ("BTC","BTC-USDT-SWAP"),("ETH","ETH-USDT-SWAP"),("SOL","SOL-USDT-SWAP"),
    ("DOGE","DOGE-USDT-SWAP"),("BNB","BNB-USDT-SWAP"),("XRP","XRP-USDT-SWAP"),
    ("ADA","ADA-USDT-SWAP"),("AVAX","AVAX-USDT-SWAP"),("LINK","LINK-USDT-SWAP"),
    ("ARB","ARB-USDT-SWAP"),("OP","OP-USDT-SWAP"),("TRX","TRX-USDT-SWAP"),
    ("NEAR","NEAR-USDT-SWAP"),("APT","APT-USDT-SWAP"),("SUI","SUI-USDT-SWAP"),
    ("INJ","INJ-USDT-SWAP"),("FIL","FIL-USDT-SWAP"),("ATOM","ATOM-USDT-SWAP"),
]

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO  = os.environ.get("GITHUB_REPO", "")
RENDER_URL   = os.environ.get("RENDER_URL", "")

# ─── 波段設定 ──────────────────────────────────────────────
SWING_TIMEFRAMES   = [("15M","15m"),("1H","1H")]
SWING_SCAN         = 60        # 每60秒掃描
SWING_DEDUP        = 14400     # 4小時去重
SWING_MAX          = 200
SWING_TTL          = 7*24*3600
SWING_MIN_SCORE    = 7
SWING_MIN_RISK     = 2.5
SWING_MIN_SL       = 0.03

# ─── 日內設定 ──────────────────────────────────────────────
INTRADAY_MODES = [
    ("超短線","1m","3m",  5,  0.5, 0.8),
    ("短線",  "5m","15m", 20, 1.0, 1.2),
    ("半日",  "15m","30m",60, 1.5, 1.8),
]
INTRADAY_SCAN  = 30
INTRADAY_MAX   = 300
INTRADAY_TTL   = 1*24*3600
INTRADAY_MIN_SCORE = 5

# ─── 全域儲存 ──────────────────────────────────────────────
swing_store    = []
intraday_store = []
swing_lock     = threading.Lock()
intraday_lock  = threading.Lock()
swing_update   = ""
intraday_update= ""

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
    if 8 <= h < 16:    return "亞洲盤", "medium"
    elif 15 <= h < 22: return "歐洲盤", "high"
    elif 20 <= h <= 23 or 0 <= h < 4: return "美洲盤", "high"
    else: return "離市時段", "low"

# ═══════════════════════════════════════════════════════════
# HTTP 工具
# ═══════════════════════════════════════════════════════════
def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except Exception as e:
        print("  err:" + str(e)[:50])
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
        return round(float(d["data"][0]["fundingRate"])*100, 4)
    return 0.0

def get_lsr(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy="+ccy+"&period=5m")
    if d and d.get("data") and len(d["data"])>0:
        try: return round(float(d["data"][0][1]),2)
        except: return 1.0
    return 1.0

def get_oi(sym):
    ccy = sym.split("-")[0]
    d = fetch("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy="+ccy+"&period=5m")
    if d and d.get("data") and len(d["data"])>0:
        try: return round(float(d["data"][0][1])/1000000,2)
        except: return 0.0
    return 0.0

def get_klines(sym, bar, limit=150):
    d = fetch("https://www.okx.com/api/v5/market/candles?instId="+sym+"&bar="+bar+"&limit="+str(limit))
    if not d or not d.get("data"): return []
    result = []
    for c in reversed(d["data"]):
        try:
            result.append({
                "h":float(c[2]),"l":float(c[3]),
                "c":float(c[4]),"v":float(c[5]),
            })
        except: pass
    return result

# ═══════════════════════════════════════════════════════════
# 技術指標（共用）
# ═══════════════════════════════════════════════════════════
def calc_atr(candles, n=14):
    if len(candles)<n+1: return 0.0
    trs = [max(candles[i]["h"]-candles[i]["l"],
               abs(candles[i]["h"]-candles[i-1]["c"]),
               abs(candles[i]["l"]-candles[i-1]["c"]))
           for i in range(1,len(candles))]
    vals = trs[-n:]
    return sum(vals)/len(vals) if vals else 0.0

def calc_rsi(candles, n=14):
    if len(candles)<n+1: return 50.0
    closes = [c["c"] for c in candles]
    gains  = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses = [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-n:])/n
    al = sum(losses[-n:])/n
    if al==0: return 100.0
    return round(100.0-100.0/(1.0+ag/al),1)

def calc_ema(closes, n):
    if not closes: return 0.0
    if len(closes)<n: return closes[-1]
    k = 2.0/(n+1)
    e = sum(closes[:n])/n
    for v in closes[n:]: e = v*k+e*(1-k)
    return e

def calc_bb(closes, n=20):
    if len(closes)<n: mid=closes[-1] if closes else 0; return mid,mid,mid
    recent = closes[-n:]
    mid = sum(recent)/n
    std = (sum((x-mid)**2 for x in recent)/n)**0.5
    return round(mid+2*std,8), round(mid,8), round(mid-2*std,8)

def calc_stoch_rsi(candles, rsi_n=14, stoch_n=14):
    if len(candles)<rsi_n+stoch_n+1: return 50.0
    closes = [c["c"] for c in candles]
    rsi_series = []
    for i in range(rsi_n, len(closes)):
        sub = [{"c":closes[j]} for j in range(i-rsi_n,i+1)]
        rsi_series.append(calc_rsi(sub, rsi_n))
    if len(rsi_series)<stoch_n: return 50.0
    recent = rsi_series[-stoch_n:]
    lo,hi = min(recent),max(recent)
    if hi==lo: return 50.0
    return round((rsi_series[-1]-lo)/(hi-lo)*100,1)

def detect_divergence(candles, lookback=20):
    if len(candles)<lookback*2: return None
    half = lookback
    rsi_r = calc_rsi(candles[-half-14:]) if len(candles)>=half+14 else 50
    rsi_p = calc_rsi(candles[-half*2-14:-half]) if len(candles)>=half*2+14 else 50
    price_r = candles[-1]["c"]
    price_p = candles[-half]["c"]
    price_up = price_r > price_p
    rsi_up   = rsi_r > rsi_p
    if price_up and not rsi_up and rsi_r>60: return "BEARISH"
    if not price_up and rsi_up and rsi_r<40: return "BULLISH"
    return None

def calc_vwap(candles):
    if not candles: return 0.0
    tv,tp = 0.0,0.0
    for c in candles:
        typ = (c["h"]+c["l"]+c["c"])/3
        tp += typ*c["v"]; tv += c["v"]
    return round(tp/tv,8) if tv>0 else 0.0

def calc_momentum(candles, n=10):
    if len(candles)<n+1: return 0.0
    closes = [c["c"] for c in candles]
    return round((closes[-1]-closes[-n-1])/closes[-n-1]*100,3)

def calc_vol_spike(candles, n=20):
    if len(candles)<n+1: return 1.0
    avg = sum(c["v"] for c in candles[-n-1:-1])/n
    return round(candles[-1]["v"]/avg,2) if avg>0 else 1.0

def find_liquidity(candles, n=20):
    if len(candles)<n: return 0.0,0.0
    recent = candles[-n:]
    highs,lows = [],[]
    for i in range(1,len(recent)-1):
        if recent[i]["h"]>recent[i-1]["h"] and recent[i]["h"]>recent[i+1]["h"]:
            highs.append(recent[i]["h"])
        if recent[i]["l"]<recent[i-1]["l"] and recent[i]["l"]<recent[i+1]["l"]:
            lows.append(recent[i]["l"])
    return (max(highs) if highs else 0.0),(min(lows) if lows else 0.0)

# ═══════════════════════════════════════════════════════════
# 三燈系統（波段專用）
# ═══════════════════════════════════════════════════════════
def get_tf_signal(sym, bar):
    candles = get_klines(sym, bar, 150)
    if not candles or len(candles)<50: return "NEUTRAL"
    closes = [c["c"] for c in candles]
    price  = closes[-1]
    rsi    = calc_rsi(candles)
    ema20  = calc_ema(closes,20)
    ema50  = calc_ema(closes,50)
    div    = detect_divergence(candles)
    if div=="BULLISH": return "REVERSAL_UP"
    if div=="BEARISH": return "REVERSAL_DOWN"
    if price>ema20>ema50 and rsi>55: return "BULLISH"
    if price<ema20<ema50 and rsi<45: return "BEARISH"
    return "NEUTRAL"

def get_three_lights(sym):
    lights = {}
    for tf,bar in [("1H","1H"),("4H","4H"),("1D","1D")]:
        lights[tf] = get_tf_signal(sym,bar)
        time.sleep(0.12)
    return lights

def analyze_lights(lights):
    bull = sum(1 for v in lights.values() if v in ["BULLISH","REVERSAL_UP"])
    bear = sum(1 for v in lights.values() if v in ["BEARISH","REVERSAL_DOWN"])
    rev  = any(v in ["REVERSAL_UP","REVERSAL_DOWN"] for v in lights.values())
    if bull>=2: return "BULLISH", bull, rev
    if bear>=2: return "BEARISH", bear, rev
    return "NEUTRAL", 0, rev

# ═══════════════════════════════════════════════════════════
# 高週期偏向（日內專用）
# ═══════════════════════════════════════════════════════════
def get_htf_bias(sym):
    scores = {"LONG":0,"SHORT":0}
    for bar in ["15m","1H"]:
        candles = get_klines(sym,bar,50)
        if not candles or len(candles)<20: continue
        closes = [c["c"] for c in candles]
        rsi   = calc_rsi(candles)
        ema9  = calc_ema(closes,9)
        ema21 = calc_ema(closes,21)
        price = closes[-1]
        if price>ema9>ema21 and rsi>52: scores["LONG"]+=2
        elif price<ema9<ema21 and rsi<48: scores["SHORT"]+=2
        elif rsi>55: scores["LONG"]+=1
        elif rsi<45: scores["SHORT"]+=1
        time.sleep(0.1)
    if scores["LONG"]>scores["SHORT"]: return "LONG"
    if scores["SHORT"]>scores["LONG"]: return "SHORT"
    return "NEUTRAL"

def get_symbol_winrate(signals, symbol, direction):
    related = [s for s in signals
               if s.get("symbol")==symbol
               and s.get("direction")==direction
               and s.get("result") in ["WIN","LOSS"]]
    if not related: return 0.0,0
    wins = sum(1 for s in related if s.get("result")=="WIN")
    return round(wins/len(related)*100,1), len(related)

# ═══════════════════════════════════════════════════════════
# 波段訊號分析
# ═══════════════════════════════════════════════════════════
SWING_ROLES = {"LONG":["獵頭者"],"SHORT":["沉思者"]}

def analyze_swing(name, sym, tf_label, tf_bar, all_signals):
    print("  [波段]" + name + " " + tf_label, end=" ")
    price = get_price(sym)
    if price==0: print("skip"); return None

    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    oi      = get_oi(sym)
    candles = get_klines(sym, tf_bar, 150)
    if not candles or len(candles)<30: print("skip"); return None

    closes    = [c["c"] for c in candles]
    atr_val   = calc_atr(candles)
    rsi_val   = calc_rsi(candles)
    stoch_rsi = calc_stoch_rsi(candles)
    ema20     = calc_ema(closes,20)
    ema50     = calc_ema(closes,50) if len(closes)>=50 else ema20
    ema200    = calc_ema(closes,200) if len(closes)>=200 else ema50
    bb_u,bb_m,bb_l = calc_bb(closes)
    div       = detect_divergence(candles)
    vol_avg   = sum(c["v"] for c in candles[-21:-1])/20 if len(candles)>20 else 1
    vol_ratio = round(candles[-1]["v"]/vol_avg,2) if vol_avg>0 else 1.0
    session, session_liq = get_session()

    lights = get_three_lights(sym)
    market_dir, light_strength, has_rev = analyze_lights(lights)

    ls=0; ss=0; rl=[]; rs=[]

    # 三燈（最重要）
    if market_dir=="BULLISH":
        ls+=light_strength*2; rl.append("三燈看漲"+str(light_strength)+"/3")
    elif market_dir=="BEARISH":
        ss+=light_strength*2; rs.append("三燈看跌"+str(light_strength)+"/3")
    if has_rev:
        if market_dir=="BULLISH": ls+=1; rl.append("含反轉結構")
        elif market_dir=="BEARISH": ss+=1; rs.append("含反轉結構")

    # 資金費率
    if funding<=-0.03: ls+=2; rl.append("資金費率極低"+str(funding)+"%")
    elif funding<=-0.01: ls+=1
    if funding>=0.06: ss+=2; rs.append("資金費率極高"+str(funding)+"%")
    elif funding>=0.02: ss+=1

    # 多空比
    if lsr<=0.75: ls+=2; rl.append("散戶極度做空 LSR:"+str(lsr))
    elif lsr<=0.90: ls+=1
    if lsr>=1.4: ss+=2; rs.append("散戶極度做多 LSR:"+str(lsr))
    elif lsr>=1.15: ss+=1

    # RSI
    if rsi_val<=25: ls+=2; rl.append("RSI嚴重超賣:"+str(rsi_val))
    elif rsi_val<=38: ls+=1; rl.append("RSI超賣:"+str(rsi_val))
    if rsi_val>=75: ss+=2; rs.append("RSI嚴重超買:"+str(rsi_val))
    elif rsi_val>=62: ss+=1; rs.append("RSI超買:"+str(rsi_val))

    # StochRSI
    if stoch_rsi<=15: ls+=1; rl.append("StochRSI超賣")
    if stoch_rsi>=85: ss+=1; rs.append("StochRSI超買")

    # 均線
    if price>ema20>ema50: ls+=2; rl.append("均線多頭排列")
    elif price<ema20<ema50: ss+=2; rs.append("均線空頭排列")

    # EMA200
    if price>ema200: ls+=1
    else: ss+=1

    # 布林帶
    if price<=bb_l: ls+=1; rl.append("觸碰布林下軌")
    if price>=bb_u: ss+=1; rs.append("觸碰布林上軌")

    # 背離
    if div=="BULLISH": ls+=2; rl.append("RSI看漲背離")
    elif div=="BEARISH": ss+=2; rs.append("RSI看跌背離")

    # 成交量
    if vol_ratio>=2.0:
        if price>closes[-2]: ls+=1; rl.append("成交量暴增看漲")
        else: ss+=1; rs.append("成交量暴增看跌")

    # 流動性時段
    if session_liq=="high":
        if ls>ss: ls+=1
        elif ss>ls: ss+=1

    print("L:"+str(ls)+" S:"+str(ss)+" "+market_dir, end=" ")

    if ls<SWING_MIN_SCORE and ss<SWING_MIN_SCORE:
        print("條件不足"); return None

    direction = "LONG" if ls>=ss else "SHORT"
    score     = ls if direction=="LONG" else ss
    reasons   = rl if direction=="LONG" else rs

    is_counter = (
        (direction=="LONG" and market_dir=="BEARISH") or
        (direction=="SHORT" and market_dir=="BULLISH") or
        (div is not None)
    )
    signal_type = "反轉" if is_counter else "順勢"

    min_sl  = price * SWING_MIN_SL
    sl_dist = max(atr_val*(2.0 if is_counter else 2.5), min_sl)
    trigger = price
    sl      = round(trigger-sl_dist if direction=="LONG" else trigger+sl_dist, 8)
    risk_pct= round(abs(sl-trigger)/trigger*100,2)

    if risk_pct < SWING_MIN_RISK:
        print("R值不足"); return None

    ratios  = [1.0,1.5,2.5,4.0] if is_counter else [1.0,2.0,3.0,5.0]
    tps     = [round(trigger+sl_dist*r if direction=="LONG" else trigger-sl_dist*r,8) for r in ratios]
    sym_wr, sym_cnt = get_symbol_winrate(all_signals, name, direction)
    role    = SWING_ROLES[direction][0]

    print("-> "+direction+"["+signal_type+"] R:"+str(risk_pct)+"% score:"+str(score))
    return {
        "id":name+"-"+tf_label+"-"+str(int(time.time())),
        "symbol":name,"timeframe":tf_label,"direction":direction,"role":role,
        "signal_type":signal_type,"session":session,
        "trigger":round(trigger,8),"current":round(trigger,8),"sl":sl,
        "risk_pct":risk_pct,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"ftp":tps[3],
        "pnl":0.0,"reached_tp":0,"active":True,
        "funding":funding,"lsr":lsr,"oi":oi,"rsi":rsi_val,
        "stoch_rsi":stoch_rsi,"market_bias":market_dir,"lights":lights,
        "vol_ratio":vol_ratio,"divergence":div,"score":score,
        "long_score":ls,"short_score":ss,"reasons":reasons,
        "sym_win_rate":sym_wr,"sym_count":sym_cnt,"chg24h":0.0,
        "triggered_at":tw_now(),"timestamp":int(time.time()),
        "ftp_reached_at":None,"result":None,
    }

# ═══════════════════════════════════════════════════════════
# 日內訊號分析
# ═══════════════════════════════════════════════════════════
def analyze_intraday(name, sym, mode_name, entry_bar, ref_bar, min_r, sl_pct):
    price = get_price(sym)
    if price==0: return None

    funding = get_funding(sym)
    lsr     = get_lsr(sym)
    candles = get_klines(sym, entry_bar, 100)
    if not candles or len(candles)<20: return None

    closes    = [c["c"] for c in candles]
    atr_val   = calc_atr(candles)
    rsi_val   = calc_rsi(candles)
    ema9      = calc_ema(closes,9)
    ema21     = calc_ema(closes,21)
    vwap      = calc_vwap(candles)
    momentum  = calc_momentum(candles)
    vol_spike = calc_vol_spike(candles)
    liq_high, liq_low = find_liquidity(candles)
    or_high   = max(c["h"] for c in candles[:6]) if len(candles)>=6 else 0.0
    or_low    = min(c["l"] for c in candles[:6]) if len(candles)>=6 else 0.0
    htf_bias  = get_htf_bias(sym)
    session, session_liq = get_session()

    ls=0; ss=0; rl=[]; rs=[]

    # VWAP（日內核心）
    vwap_dist = round((price-vwap)/vwap*100,2) if vwap>0 else 0
    if price>vwap: ls+=2; rl.append("價格在VWAP上方+"+str(abs(vwap_dist))+"%")
    else: ss+=2; rs.append("價格在VWAP下方-"+str(abs(vwap_dist))+"%")

    # 高週期方向
    if htf_bias=="LONG": ls+=3; rl.append("高週期多頭")
    elif htf_bias=="SHORT": ss+=3; rs.append("高週期空頭")

    # EMA排列
    if price>ema9>ema21: ls+=2; rl.append("EMA多頭排列")
    elif price<ema9<ema21: ss+=2; rs.append("EMA空頭排列")

    # RSI
    if rsi_val<=30: ls+=2; rl.append("RSI超賣:"+str(rsi_val))
    elif rsi_val<=42: ls+=1
    if rsi_val>=70: ss+=2; rs.append("RSI超買:"+str(rsi_val))
    elif rsi_val>=58: ss+=1

    # 開盤區間突破
    if or_high>0 and price>or_high: ls+=2; rl.append("突破開盤高點")
    if or_low>0 and price<or_low:   ss+=2; rs.append("跌破開盤低點")

    # 流動性掃蕩
    if liq_low>0 and price<=liq_low*1.002: ls+=2; rl.append("流動性低點掃蕩")
    if liq_high>0 and price>=liq_high*0.998: ss+=2; rs.append("流動性高點掃蕩")

    # 動能
    if momentum>=0.5: ls+=1; rl.append("正動能+"+str(momentum)+"%")
    elif momentum<=-0.5: ss+=1; rs.append("負動能"+str(momentum)+"%")

    # 成交量爆量
    if vol_spike>=2.0:
        if price>closes[-2]: ls+=1; rl.append("成交量爆量"+str(vol_spike)+"x")
        else: ss+=1; rs.append("成交量爆量"+str(vol_spike)+"x")

    # 資金費率
    if funding<=-0.02: ls+=1; rl.append("資金費率負值")
    if funding>=0.05:  ss+=1; rs.append("資金費率極高")

    # 多空比
    if lsr<=0.8:  ls+=1; rl.append("散戶過度做空")
    if lsr>=1.4:  ss+=1; rs.append("散戶過度做多")

    # 時段加成
    if session_liq=="high":
        if ls>ss: ls+=1
        elif ss>ls: ss+=1

    if ls<INTRADAY_MIN_SCORE and ss<INTRADAY_MIN_SCORE:
        return None

    direction = "LONG" if ls>=ss else "SHORT"
    score     = ls if direction=="LONG" else ss
    reasons   = rl if direction=="LONG" else rs

    min_sl  = price*(sl_pct/100)
    sl_dist = max(atr_val*1.5, min_sl)
    trigger = price
    sl      = round(trigger-sl_dist if direction=="LONG" else trigger+sl_dist,8)
    risk_pct= round(abs(sl-trigger)/trigger*100,2)

    if risk_pct < min_r: return None

    tps = [round(trigger+sl_dist*r if direction=="LONG" else trigger-sl_dist*r,8)
           for r in [0.8,1.5,2.5,4.0]]
    role = "獵頭者" if direction=="LONG" else "沉思者"

    return {
        "id":name+"-"+mode_name+"-"+str(int(time.time())),
        "symbol":name,"timeframe":mode_name,"mode":mode_name,
        "entry_tf":entry_bar,"direction":direction,"role":role,
        "signal_type":"日內","session":session,
        "trigger":round(trigger,8),"current":round(trigger,8),"sl":sl,
        "risk_pct":risk_pct,"tp1":tps[0],"tp2":tps[1],"tp3":tps[2],"ftp":tps[3],
        "vwap":round(vwap,8),"or_high":round(or_high,8),"or_low":round(or_low,8),
        "liq_high":round(liq_high,8),"liq_low":round(liq_low,8),
        "momentum":momentum,"vol_spike":vol_spike,"htf_bias":htf_bias,
        "rsi":rsi_val,"funding":funding,"lsr":lsr,
        "score":score,"long_score":ls,"short_score":ss,"reasons":reasons,
        "pnl":0.0,"reached_tp":0,"active":True,"chg24h":0.0,
        "triggered_at":tw_now(),"timestamp":int(time.time()),
        "ftp_reached_at":None,"result":None,
    }

# ═══════════════════════════════════════════════════════════
# 盈虧更新（共用）
# ═══════════════════════════════════════════════════════════
SYM_MAP = {n:s for n,s in SYMBOLS}

def update_pnl(sig):
    p = get_price(SYM_MAP.get(sig["symbol"], sig["symbol"]+"-USDT-SWAP"))
    if not p: return sig
    sig["current"] = p
    t = sig["trigger"]
    pnl = (p-t)/t*100 if sig["direction"]=="LONG" else (t-p)/t*100
    sig["pnl"] = round(pnl,2)
    prev = sig.get("reached_tp",0)
    for i,tp in enumerate([sig["tp1"],sig["tp2"],sig["tp3"],sig["ftp"]]):
        if sig["direction"]=="LONG" and p>=tp: sig["reached_tp"]=i+1
        elif sig["direction"]=="SHORT" and p<=tp: sig["reached_tp"]=i+1
    if sig.get("reached_tp",0)==4 and prev<4:
        sig["ftp_reached_at"] = tw_now()
        sig["result"] = "WIN"
        label = "[日內]" if sig.get("signal_type")=="日內" else "[波段]"
        print("  🏆 FTP！" + label + sig["symbol"])
    if sig["direction"]=="LONG" and p<=sig["sl"]:
        sig["active"]=False
        if not sig.get("result"): sig["result"]="LOSS"
    elif sig["direction"]=="SHORT" and p>=sig["sl"]:
        sig["active"]=False
        if not sig.get("result"): sig["result"]="LOSS"
    return sig

# ═══════════════════════════════════════════════════════════
# GitHub 持久化
# ═══════════════════════════════════════════════════════════
def gh_load(filename):
    if not GITHUB_TOKEN or not GITHUB_REPO: return []
    try:
        import base64
        url = "https://api.github.com/repos/"+GITHUB_REPO+"/contents/data/"+filename
        req = urllib.request.Request(url, headers={
            "Authorization":"token "+GITHUB_TOKEN,"User-Agent":"sentiment-lens"})
        with urllib.request.urlopen(req, timeout=10) as r:
            meta = json.loads(r.read())
        sigs = json.loads(base64.b64decode(meta["content"]).decode("utf-8")).get("signals",[])
        print("  GitHub載入["+filename+"] "+str(len(sigs))+"筆")
        return sigs
    except Exception as e:
        print("  GitHub載入失敗["+filename+"]: "+str(e)[:50])
        return []

def gh_save(signals, filename, extra={}):
    if not GITHUB_TOKEN or not GITHUB_REPO: return
    try:
        import base64
        wins   = [s for s in signals if s.get("result")=="WIN"]
        losses = [s for s in signals if s.get("result")=="LOSS"]
        closed = len(wins)+len(losses)
        wr     = round(len(wins)/closed*100,1) if closed>0 else 0.0
        data   = {
            "signals":signals,
            "updated_at":tw_now_full()+" (台北時間)",
            "total":len(signals),
            "active":sum(1 for s in signals if s.get("active",True) and not s.get("result")),
            "ftp_count":sum(1 for s in signals if s.get("reached_tp",0)==4),
            "win_count":len(wins),"loss_count":len(losses),"win_rate":wr,
            **extra,
        }
        b64 = base64.b64encode(json.dumps(data,ensure_ascii=False,indent=2).encode()).decode()
        url = "https://api.github.com/repos/"+GITHUB_REPO+"/contents/data/"+filename
        sha = None
        try:
            req = urllib.request.Request(url,headers={"Authorization":"token "+GITHUB_TOKEN,"User-Agent":"sentiment-lens"})
            with urllib.request.urlopen(req,timeout=10) as r: sha=json.loads(r.read()).get("sha")
        except: pass
        payload = {"message":"update "+filename+" "+tw_now(),"content":b64}
        if sha: payload["sha"]=sha
        req2 = urllib.request.Request(url,data=json.dumps(payload).encode(),
            headers={"Authorization":"token "+GITHUB_TOKEN,"Content-Type":"application/json","User-Agent":"sentiment-lens"},
            method="PUT")
        with urllib.request.urlopen(req2,timeout=20): pass
        print("  GitHub儲存["+filename+"] 勝率:"+str(wr)+"%")
    except Exception as e:
        print("  GitHub儲存失敗: "+str(e)[:60])

# ═══════════════════════════════════════════════════════════
# 防休眠
# ═══════════════════════════════════════════════════════════
def keep_alive():
    if not RENDER_URL: return
    while True:
        time.sleep(600)
        try:
            urllib.request.urlopen(RENDER_URL+"/health",timeout=10)
            print("  keep-alive OK")
        except: pass

# ═══════════════════════════════════════════════════════════
# 波段掃描引擎
# ═══════════════════════════════════════════════════════════
def swing_loop():
    global swing_store, swing_update
    print("波段掃描引擎啟動...")
    with swing_lock: swing_store = gh_load("signals.json")
    save_cnt = 0
    while True:
        try:
            print("\n[波段] "+tw_now_full())
            with swing_lock: existing = list(swing_store)
            cutoff  = int(time.time())-SWING_TTL
            updated = []
            for s in existing:
                if s.get("timestamp",0)<cutoff: continue
                if s.get("active",True) and s.get("result") is None:
                    s=update_pnl(s); time.sleep(0.1)
                updated.append(s)
            new_sigs=[]; dedup=int(time.time())-SWING_DEDUP
            for name,sym in SYMBOLS:
                for tf_label,tf_bar in SWING_TIMEFRAMES:
                    if any(s["symbol"]==name and s["timeframe"]==tf_label
                           and s.get("timestamp",0)>dedup for s in updated): continue
                    sig = analyze_swing(name,sym,tf_label,tf_bar,updated)
                    if sig: new_sigs.append(sig)
                    time.sleep(0.3)
            all_sigs = sorted(new_sigs+updated, key=lambda x:x.get("timestamp",0), reverse=True)[:SWING_MAX]
            now_str  = tw_now_full()+" (台北時間)"
            with swing_lock: swing_store=all_sigs; swing_update=now_str
            save_cnt+=1
            if save_cnt>=5 or len(new_sigs)>0:
                gh_save(all_sigs,"signals.json"); save_cnt=0
            wins=sum(1 for s in all_sigs if s.get("result")=="WIN")
            losses=sum(1 for s in all_sigs if s.get("result")=="LOSS")
            closed=wins+losses
            wr=round(wins/closed*100,1) if closed>0 else 0
            print("[波段] 新增:"+str(len(new_sigs))+" 合計:"+str(len(all_sigs))+" 勝率:"+str(wr)+"%")
        except Exception as e:
            print("[波段] 錯誤:"+str(e))
        time.sleep(SWING_SCAN)

# ═══════════════════════════════════════════════════════════
# 日內掃描引擎
# ═══════════════════════════════════════════════════════════
def intraday_loop():
    global intraday_store, intraday_update
    print("日內掃描引擎啟動...")
    with intraday_lock: intraday_store = gh_load("intraday_signals.json")
    save_cnt = 0
    while True:
        try:
            print("\n[日內] "+tw_now_full())
            with intraday_lock: existing = list(intraday_store)
            cutoff  = int(time.time())-INTRADAY_TTL
            updated = []
            for s in existing:
                if s.get("timestamp",0)<cutoff: continue
                if s.get("active",True) and s.get("result") is None:
                    s=update_pnl(s); time.sleep(0.08)
                updated.append(s)
            new_sigs=[]
            for name,sym in SYMBOLS:
                for mode_name,entry_bar,ref_bar,dedup_min,min_r,sl_pct in INTRADAY_MODES:
                    dedup=int(time.time())-dedup_min*60
                    if any(s["symbol"]==name and s.get("mode")==mode_name
                           and s.get("timestamp",0)>dedup for s in updated): continue
                    sig = analyze_intraday(name,sym,mode_name,entry_bar,ref_bar,min_r,sl_pct)
                    if sig: new_sigs.append(sig)
                    time.sleep(0.2)
            all_sigs = sorted(new_sigs+updated, key=lambda x:x.get("timestamp",0), reverse=True)[:INTRADAY_MAX]
            now_str  = tw_now_full()+" (台北時間)"
            with intraday_lock: intraday_store=all_sigs; intraday_update=now_str
            save_cnt+=1
            if save_cnt>=10 or len(new_sigs)>0:
                gh_save(all_sigs,"intraday_signals.json"); save_cnt=0
            wins=sum(1 for s in all_sigs if s.get("result")=="WIN")
            losses=sum(1 for s in all_sigs if s.get("result")=="LOSS")
            closed=wins+losses
            wr=round(wins/closed*100,1) if closed>0 else 0
            print("[日內] 新增:"+str(len(new_sigs))+" 合計:"+str(len(all_sigs))+" 勝率:"+str(wr)+"%")
        except Exception as e:
            print("[日內] 錯誤:"+str(e))
        time.sleep(INTRADAY_SCAN)

# ═══════════════════════════════════════════════════════════
# HTTP 伺服器
# ═══════════════════════════════════════════════════════════
def make_response(signals, updated_at):
    wins  = sum(1 for s in signals if s.get("result")=="WIN")
    losses= sum(1 for s in signals if s.get("result")=="LOSS")
    closed= wins+losses
    return {
        "signals":    signals,
        "updated_at": updated_at,
        "total":      len(signals),
        "active_count": sum(1 for s in signals if s.get("active",True) and not s.get("result")),
        "ftp_count":  sum(1 for s in signals if s.get("reached_tp",0)==4),
        "win_count":  wins,
        "loss_count": losses,
        "win_rate":   round(wins/closed*100,1) if closed>0 else 0,
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ["/signals","/"]:
            with swing_lock:
                data = make_response(swing_store, swing_update)
        elif path == "/intraday":
            with intraday_lock:
                data = make_response(intraday_store, intraday_update)
        elif path == "/health":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin","*")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        else:
            self.send_response(404); self.end_headers(); return

        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","*")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers","*")
        self.end_headers()

class ThreadedServer(socketserver.ThreadingMixIn, HTTPServer): pass

# ═══════════════════════════════════════════════════════════
# 啟動
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=swing_loop,    daemon=True).start()
    threading.Thread(target=intraday_loop, daemon=True).start()
    threading.Thread(target=keep_alive,    daemon=True).start()
    server = ThreadedServer(("0.0.0.0", port), Handler)
    print("伺服器啟動 port:"+str(port)+" | /signals=波段 | /intraday=日內")
    server.serve_forever()
