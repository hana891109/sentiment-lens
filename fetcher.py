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
