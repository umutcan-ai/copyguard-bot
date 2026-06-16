#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CopyGuard GitHub Actions Bybit v2

Neden Bybit?
- GitHub Actions üzerinde Binance Futures API HTTP 451 verdiği için bu sürüm
  public Bybit USDT perpetual market verisini kullanır.
- İşlem/emir açmaz. Sadece Telegram sinyali üretir.
- Binance API key gerekmez.
- Bybit API key gerekmez.

Çalışma:
- GitHub Actions 5 dakikada bir çalıştırır.
- 15m / 1H / 4H / 1D veriye bakar.
- 1D = büyük yön / risk filtresi.
- 4H = ana trend.
- 1H = işlem yönü.
- 15m = giriş tetikleyici.
"""

import os
import json
import time
import math
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta

VERSION = "CopyGuard GitHub Actions Bybit v2"

BYBIT_BASE = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ACCOUNT_CAPITAL_USDT = float(os.getenv("ACCOUNT_CAPITAL_USDT", "500"))
POSITION_USDT_PER_SIGNAL = float(os.getenv("POSITION_USDT_PER_SIGNAL", "40"))

MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "50000000"))
MAX_24H_CHANGE_PCT = float(os.getenv("MAX_24H_CHANGE_PCT", "18"))
MAX_SIGNALS_PER_RUN = int(os.getenv("MAX_SIGNALS_PER_RUN", "5"))

MIN_LONG_SCORE = float(os.getenv("MIN_LONG_SCORE", "8.0"))
MIN_SHORT_SCORE = float(os.getenv("MIN_SHORT_SCORE", "8.7"))

COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "6"))
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.03"))
SEND_NO_SIGNAL = os.getenv("SEND_NO_SIGNAL", "false").lower() in ("1", "true", "yes", "evet")
STATE_FILE = os.getenv("STATE_FILE", "copyguard_state.json")

UA = "Mozilla/5.0 CopyGuard-GitHub-Actions-Bybit-v2"

WHITELIST_BASE = [
    "BTC","ETH","BNB","SOL","XRP","ADA","LINK","AVAX","DOT","LTC","BCH","TRX","XLM","ETC","ATOM",
    "NEAR","APT","ARB","OP","SUI","INJ","UNI","AAVE","FIL","HBAR","ICP","RENDER","FET","TAO",
    "SEI","TIA","ALGO","VET","EGLD","RUNE","STX","LDO","PENDLE","ENA","ONDO","JUP","PYTH",
    "IMX","DYDX","CRV","COMP","SNX","GMX","WLD","ORDI","ARKM"
]

MEME_BLACKLIST = {
    "SHIBUSDT","1000SHIBUSDT","PEPEUSDT","1000PEPEUSDT","FLOKIUSDT","1000FLOKIUSDT",
    "BONKUSDT","1000BONKUSDT","WIFUSDT","MEMEUSDT","BOMEUSDT","TURBOUSDT",
    "DOGSUSDT","TRUMPUSDT","1000SATSUSDT","1000RATSUSDT"
}

BYBIT_INTERVALS = {
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

def now_utc():
    return datetime.now(timezone.utc)

def tr_time_str():
    return (now_utc() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S TR")

def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def bybit(path, params=None):
    if params:
        url = f"{BYBIT_BASE}{path}?{urllib.parse.urlencode(params)}"
    else:
        url = f"{BYBIT_BASE}{path}"
    data = http_json(url)
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit API hata: retCode={data.get('retCode')} retMsg={data.get('retMsg')}")
    return data.get("result", {})

def tg_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets eksik: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            ok = 200 <= resp.status < 300
            print("Telegram send:", ok)
            return ok
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:800]
        print("Telegram HTTP hata:", e.code, body)
        return False
    except Exception as e:
        print("Telegram hata:", repr(e))
        return False

def safe_float(x, default=0.0):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default

def fmt_price(x):
    if x is None or math.isnan(float(x)):
        return "?"
    x = float(x)
    if x >= 100:
        return f"{x:.2f}"
    if x >= 10:
        return f"{x:.3f}"
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.1:
        return f"{x:.5f}"
    if x >= 0.01:
        return f"{x:.6f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def fmt_usdt(x):
    return f"{float(x):.1f}".rstrip("0").rstrip(".")

def ema(values, period):
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def rsi(values, period=14):
    if len(values) < period + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def macd_hist(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal + 5:
        return 0.0, 0.0
    ef = ema(values, fast)
    es = ema(values, slow)
    macd_line = [a - b for a, b in zip(ef[-len(es):], es)]
    sig = ema(macd_line, signal)
    hist_series = [m - s for m, s in zip(macd_line[-len(sig):], sig)]
    hist = hist_series[-1]
    prev = hist_series[-2] if len(hist_series) > 1 else hist
    return hist, hist - prev

def bybit_candles(symbol, interval_key, limit=180):
    result = bybit("/v5/market/kline", {
        "category": "linear",
        "symbol": symbol,
        "interval": BYBIT_INTERVALS[interval_key],
        "limit": str(limit),
    })
    raw = result.get("list", [])
    rows = []
    for k in raw:
        # Bybit: [startTime, openPrice, highPrice, lowPrice, closePrice, volume, turnover]
        rows.append({
            "open_time": int(k[0]),
            "open": safe_float(k[1]),
            "high": safe_float(k[2]),
            "low": safe_float(k[3]),
            "close": safe_float(k[4]),
            "volume": safe_float(k[5]),
            "turnover": safe_float(k[6]) if len(k) > 6 else 0.0,
        })
    rows.sort(key=lambda x: x["open_time"])
    # En son mum hâlâ açık olabilir. Kapanmış mumlarla çalışmak için son mumu at.
    if len(rows) > 2:
        rows = rows[:-1]
    return rows

def atr(cands, period=14):
    if len(cands) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(cands)):
        h, l, pc = cands[i]["high"], cands[i]["low"], cands[i-1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / min(period, len(trs))

def closes(cands):
    return [c["close"] for c in cands]

def ticker_map():
    result = bybit("/v5/market/tickers", {"category": "linear"})
    out = {}
    for x in result.get("list", []):
        sym = x.get("symbol")
        if not sym:
            continue
        last = safe_float(x.get("lastPrice"))
        prev = safe_float(x.get("prevPrice24h"))
        chg_pct = safe_float(x.get("price24hPcnt")) * 100.0
        if prev and not chg_pct:
            chg_pct = (last - prev) / prev * 100.0
        out[sym] = {
            "symbol": sym,
            "last": last,
            "mark": safe_float(x.get("markPrice"), last),
            "turnover24h": safe_float(x.get("turnover24h")),
            "volume24h": safe_float(x.get("volume24h")),
            "change_pct": chg_pct,
            "funding": safe_float(x.get("fundingRate")),
            "open_interest": safe_float(x.get("openInterest")),
        }
    return out

def instruments_active():
    # Bybit linear sembol sayısı yüksek olabilir. 1000 limit şimdilik yeterli.
    try:
        result = bybit("/v5/market/instruments-info", {"category": "linear", "limit": "1000"})
        active = set()
        for x in result.get("list", []):
            if x.get("status") == "Trading" and x.get("quoteCoin") == "USDT":
                active.add(x.get("symbol"))
        return active
    except Exception as e:
        print("instruments-info hata, ticker listesine düşülecek:", repr(e))
        return set()

def universe(active, tmap):
    if not active:
        active = set(tmap.keys())

    syms = []
    for base in WHITELIST_BASE:
        s = base + "USDT"
        if s in MEME_BLACKLIST:
            continue
        if s not in active:
            continue
        t = tmap.get(s)
        if not t:
            continue
        if t["turnover24h"] < MIN_24H_QUOTE_VOLUME:
            continue
        if abs(t["change_pct"]) > MAX_24H_CHANGE_PCT:
            continue
        syms.append(s)
    return syms

def tf_summary(c):
    cl = closes(c)
    p = cl[-1]
    e7 = ema(cl, 7)[-1]
    e25 = ema(cl, 25)[-1]
    e99 = ema(cl, 99)[-1]
    r = rsi(cl)
    hist, dh = macd_hist(cl)
    return {
        "price": p,
        "ema7": e7,
        "ema25": e25,
        "ema99": e99,
        "rsi": r,
        "macd_hist": hist,
        "macd_delta": dh,
        "atr": atr(c),
    }

def tf_label(s):
    if s["price"] > s["ema25"] and s["ema7"] > s["ema25"] and s["macd_delta"] > 0:
        return "pozitif"
    if s["price"] < s["ema25"] and s["ema7"] < s["ema25"] and s["macd_delta"] < 0:
        return "negatif"
    if s["macd_delta"] > 0:
        return "toparlanıyor"
    if s["macd_delta"] < 0:
        return "zayıflıyor"
    return "nötr"

def candle_wick_bad(c):
    last = c[-1]
    rng = max(last["high"] - last["low"], 1e-12)
    body = abs(last["close"] - last["open"])
    upper = last["high"] - max(last["close"], last["open"])
    lower = min(last["close"], last["open"]) - last["low"]
    return body / rng < 0.18 or upper / rng > 0.62 or lower / rng > 0.62

def btc_filter():
    try:
        c1h = bybit_candles("BTCUSDT", "1h", 160)
        time.sleep(REQUEST_SLEEP_SECONDS)
        c4h = bybit_candles("BTCUSDT", "4h", 160)
        time.sleep(REQUEST_SLEEP_SECONDS)
        c1d = bybit_candles("BTCUSDT", "1d", 170)
        s1 = tf_summary(c1h)
        s4 = tf_summary(c4h)
        sd = tf_summary(c1d)
        strong = (
            s1["price"] > s1["ema25"] and s4["price"] > s4["ema25"] and
            s4["price"] > s4["ema99"] and s1["macd_delta"] > 0 and s1["rsi"] > 50
        )
        weak = (
            s1["price"] < s1["ema25"] and s4["price"] < s4["ema25"] and
            s4["price"] < s4["ema99"] and s1["macd_delta"] < 0 and s1["rsi"] < 45
        )
        return {"strong": strong, "weak": weak, "rsi1h": s1["rsi"]}
    except Exception as e:
        print("BTC filtre hata:", repr(e))
        return {"strong": False, "weak": False, "rsi1h": 50}

def analyze_symbol(symbol, ticker, btc):
    c15 = bybit_candles(symbol, "15m", 160)
    time.sleep(REQUEST_SLEEP_SECONDS)
    c1h = bybit_candles(symbol, "1h", 170)
    time.sleep(REQUEST_SLEEP_SECONDS)
    c4h = bybit_candles(symbol, "4h", 170)
    time.sleep(REQUEST_SLEEP_SECONDS)
    c1d = bybit_candles(symbol, "1d", 180)
    time.sleep(REQUEST_SLEEP_SECONDS)

    if min(len(c15), len(c1h), len(c4h), len(c1d)) < 110:
        return None

    s15 = tf_summary(c15)
    s1 = tf_summary(c1h)
    s4 = tf_summary(c4h)
    sd = tf_summary(c1d)

    price = s15["price"]
    mark = ticker.get("mark") or price
    funding = ticker.get("funding", 0.0)
    mark_diff_pct = abs(mark - price) / price * 100 if price else 0.0
    if mark_diff_pct > 0.45:
        return None

    change_pct = ticker.get("change_pct", 0.0)
    quote_vol = ticker.get("turnover24h", 0.0)
    oi = ticker.get("open_interest", 0.0)

    wick_penalty = candle_wick_bad(c15)

    lows1 = [c["low"] for c in c1h[-36:-1]]
    highs1 = [c["high"] for c in c1h[-36:-1]]
    support = min(lows1) if lows1 else price * 0.985
    resistance = max(highs1) if highs1 else price * 1.015

    a15 = max(s15["atr"] / price if price else 0.004, 0.0025)
    a15 = min(a15, 0.03)

    vol_now = c15[-1]["volume"]
    vol_avg = sum(c["volume"] for c in c15[-25:-1]) / 24 if len(c15) > 25 else vol_now
    vol_boost = vol_now > vol_avg * 1.15

    long_score = 0.0
    short_score = 0.0
    long_reasons = []
    short_reasons = []

    # 1D büyük yön/risk filtresi
    if sd["price"] > sd["ema99"]:
        long_score += 0.6; long_reasons.append("1D EMA99 üstü: büyük yön long için uygun")
    else:
        long_score -= 0.4; long_reasons.append("1D EMA99 altı: long daha seçici")
    if sd["price"] > sd["ema25"] and sd["ema7"] > sd["ema25"]:
        long_score += 0.6; long_reasons.append("1D EMA7/25 pozitif")
    if sd["price"] < sd["ema25"] and sd["ema7"] < sd["ema25"]:
        short_score += 0.8; short_reasons.append("1D EMA7/25 zayıf")
    if sd["price"] < sd["ema99"] and sd["ema7"] < sd["ema25"] < sd["ema99"] and sd["rsi"] < 35:
        long_score -= 1.2; long_reasons.append("1D ağır düşüş filtresi")
    if sd["price"] > sd["ema99"] and sd["ema7"] > sd["ema25"] > sd["ema99"]:
        short_score -= 1.2; short_reasons.append("1D güçlü boğa: short zorlaştırıldı")
    if sd["macd_delta"] > 0:
        long_score += 0.3
    if sd["macd_delta"] < 0:
        short_score += 0.3

    # 4H ana trend
    if s4["price"] > s4["ema99"]:
        long_score += 1.0; long_reasons.append("4H EMA99 üstü")
    else:
        short_score += 0.7; short_reasons.append("4H EMA99 altı")
    if s4["ema7"] > s4["ema25"]:
        long_score += 1.0; long_reasons.append("4H EMA7/25 pozitif")
    elif s4["ema7"] < s4["ema25"]:
        short_score += 1.0; short_reasons.append("4H EMA7/25 negatif")
    if 40 <= s4["rsi"] <= 62:
        long_score += 0.4
    if 42 <= s4["rsi"] <= 58 and s4["macd_delta"] < 0:
        short_score += 0.4
    if s4["macd_delta"] > 0:
        long_score += 0.7; long_reasons.append("4H MACD toparlanıyor")
    if s4["macd_delta"] < 0:
        short_score += 0.7; short_reasons.append("4H MACD zayıflıyor")

    # 1H işlem yönü
    if s1["price"] > s1["ema25"] and s1["ema7"] >= s1["ema25"]:
        long_score += 1.4; long_reasons.append("1H EMA25 geri kazanılmış")
    if s1["price"] < s1["ema25"] and s1["ema7"] <= s1["ema25"]:
        short_score += 1.4; short_reasons.append("1H EMA25 altı")
    if 42 <= s1["rsi"] <= 64:
        long_score += 0.5; long_reasons.append(f"1H RSI sağlıklı ({s1['rsi']:.0f})")
    if s1["rsi"] < 55 and s1["macd_delta"] < 0:
        short_score += 0.5; short_reasons.append(f"1H RSI/MACD aşağı ({s1['rsi']:.0f})")
    if s1["macd_delta"] > 0:
        long_score += 0.7; long_reasons.append("1H MACD güçleniyor")
    if s1["macd_delta"] < 0:
        short_score += 0.7; short_reasons.append("1H MACD aşağı")

    # 15m giriş tetikleyici
    if s15["price"] > s15["ema25"] and s15["ema7"] > s15["ema25"]:
        long_score += 1.0; long_reasons.append("15m giriş momentumu long")
    if s15["price"] < s15["ema25"] and s15["ema7"] < s15["ema25"]:
        short_score += 1.0; short_reasons.append("15m giriş momentumu short")
    if s15["rsi"] >= 45 and s15["macd_delta"] > 0:
        long_score += 0.6; long_reasons.append("15m RSI/MACD tepki")
    if s15["rsi"] <= 55 and s15["macd_delta"] < 0:
        short_score += 0.6; short_reasons.append("15m RSI/MACD red")

    # Destek / direnç / TP alanı
    dist_support = (price - support) / price if price else 1
    dist_res = (resistance - price) / price if price else 1
    near_support = 0 <= dist_support <= max(0.018, a15 * 2.4)
    near_res = 0 <= dist_res <= max(0.018, a15 * 2.4)

    if near_support:
        long_score += 1.0; long_reasons.append("destek bölgesine yakın")
    elif price > resistance * 0.995:
        long_score -= 0.8; long_reasons.append("dirence çok yakın")

    if near_res:
        short_score += 1.0; short_reasons.append("direnç bölgesine yakın")
    elif price < support * 1.005:
        short_score -= 0.8; short_reasons.append("desteğe çok yakın")

    if resistance > price * (1 + max(0.006, a15 * 1.2)):
        long_score += 0.5; long_reasons.append("long için TP alanı var")
    else:
        long_score -= 0.4

    if support < price * (1 - max(0.006, a15 * 1.2)):
        short_score += 0.5; short_reasons.append("short için TP alanı var")
    else:
        short_score -= 0.4

    # Hacim / OI / funding
    if vol_boost and c15[-1]["close"] >= c15[-1]["open"]:
        long_score += 0.5; long_reasons.append("tepki hacmi artmış")
    if vol_boost and c15[-1]["close"] < c15[-1]["open"]:
        short_score += 0.5; short_reasons.append("satış hacmi artmış")

    if oi > 0:
        long_score += 0.2
        short_score += 0.2

    if funding > 0.0008:
        long_score -= 0.5; long_reasons.append("funding long kalabalık")
    if funding < -0.0005:
        short_score -= 0.5; short_reasons.append("funding short kalabalık")
        long_score += 0.2

    # BTC filtresi
    if btc.get("strong"):
        long_score += 0.8; long_reasons.append("BTC filtresi long destekli")
        short_score -= 0.8; short_reasons.append("BTC güçlü: short puanı azaltıldı")
    if btc.get("weak"):
        long_score -= 0.9; long_reasons.append("BTC zayıf: long puanı azaltıldı")
        short_score += 0.7; short_reasons.append("BTC filtresi short destekli")

    if wick_penalty:
        long_score -= 0.4
        short_score -= 0.4

    # Zıt tüm TF filtresi
    if s4["price"] < s4["ema25"] and s1["price"] < s1["ema25"] and s15["price"] < s15["ema25"]:
        long_score -= 0.8
    if s4["price"] > s4["ema25"] and s1["price"] > s1["ema25"] and s15["price"] > s15["ema25"]:
        short_score -= 0.8

    direction = None
    score = 0.0
    reasons = []
    if long_score >= MIN_LONG_SCORE and long_score >= short_score + 0.5:
        direction = "LONG"; score = long_score; reasons = long_reasons[:8]
    elif short_score >= MIN_SHORT_SCORE and short_score >= long_score + 0.8:
        direction = "SHORT"; score = short_score; reasons = short_reasons[:8]
    else:
        return None

    return {
        "symbol": symbol,
        "direction": direction,
        "score": round(score, 2),
        "price": price,
        "mark": mark,
        "funding": funding,
        "oi": oi,
        "quote_vol": quote_vol,
        "change_pct": change_pct,
        "support": support,
        "resistance": resistance,
        "atr_pct": a15,
        "rsi_15m": s15["rsi"],
        "rsi_1h": s1["rsi"],
        "rsi_4h": s4["rsi"],
        "rsi_1d": sd["rsi"],
        "tf_1d": tf_label(sd),
        "tf_4h": tf_label(s4),
        "tf_1h": tf_label(s1),
        "tf_15m": tf_label(s15),
        "reasons": reasons,
    }

def build_plan(sig):
    p = sig["price"]
    atrp = sig["atr_pct"]
    total = POSITION_USDT_PER_SIGNAL
    weights = [0.25, 0.22, 0.20, 0.18, 0.15]

    if sig["direction"] == "LONG":
        steps_pct = [0.000, 0.55*atrp, 1.10*atrp, 1.75*atrp, 2.55*atrp]
        entries = [p * (1 - x) for x in steps_pct]
        tp_pcts = [max(0.006, 0.95*atrp), max(0.007, 1.10*atrp), max(0.008, 1.25*atrp), max(0.009, 1.40*atrp), max(0.010, 1.55*atrp)]
        tps = [e * (1 + tp) for e, tp in zip(entries, tp_pcts)]
        invalid = min(sig["support"] * 0.985, entries[-1] * (1 - max(0.006, atrp)))
        alarms = [entries[1], entries[3], max(tps[0], p * 1.006), invalid]
    else:
        steps_pct = [0.000, 0.55*atrp, 1.10*atrp, 1.75*atrp, 2.55*atrp]
        entries = [p * (1 + x) for x in steps_pct]
        tp_pcts = [max(0.006, 0.95*atrp), max(0.007, 1.10*atrp), max(0.008, 1.25*atrp), max(0.009, 1.40*atrp), max(0.010, 1.55*atrp)]
        tps = [e * (1 - tp) for e, tp in zip(entries, tp_pcts)]
        invalid = max(sig["resistance"] * 1.015, entries[-1] * (1 + max(0.006, atrp)))
        alarms = [entries[1], entries[3], min(tps[0], p * 0.994), invalid]

    amounts = [total * w for w in weights]
    return entries, amounts, tps, invalid, alarms

def signal_message(sig):
    emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    entries, amounts, tps, invalid, alarms = build_plan(sig)
    lines = [
        f"{emoji} <b>{sig['symbol']} {sig['direction']} ADAYI</b>",
        f"Skor: <b>{sig['score']:.1f}/10</b>",
        f"Saat: {tr_time_str()}",
        "",
        "Veri kaynağı: Bybit USDT perpetual public market data",
        "Not: Plan Binance Futures üzerinde manuel/copy trade için yorumlanacak.",
        "",
        "Zaman dilimleri:",
        f"1D: {sig['tf_1d']} | 4H: {sig['tf_4h']} | 1H: {sig['tf_1h']} | 15m: {sig['tf_15m']}",
        "",
        "Canlı veri:",
        f"Son fiyat: {fmt_price(sig['price'])} | Mark: {fmt_price(sig['mark'])}",
        f"24s hacim: {sig['quote_vol']/1_000_000:.1f}M USDT | 24s değişim: {sig['change_pct']:.2f}%",
        f"Funding: {sig['funding']*100:.4f}% | OI: {sig['oi']:.0f}",
        f"RSI 15m/1H/4H/1D: {sig['rsi_15m']:.0f}/{sig['rsi_1h']:.0f}/{sig['rsi_4h']:.0f}/{sig['rsi_1d']:.0f}",
        "",
        "Sebep:",
    ]
    for r in sig["reasons"][:7]:
        lines.append(f"- {r}")

    lines += ["", "5 kademeli plan:"]
    for i, (e, a, tp) in enumerate(zip(entries, amounts, tps), 1):
        lines.append(f"{i}) {fmt_price(e)} — {fmt_usdt(a)} USDT — TP {fmt_price(tp)}")

    lines += [
        "",
        "Alarm:",
        " / ".join(fmt_price(x) for x in alarms),
        "",
    ]
    if sig["direction"] == "LONG":
        lines.append(f"İptal: 1H veya 4H mum {fmt_price(invalid)} altında kapanırsa planı askıya al.")
    else:
        lines.append(f"İptal: 1H veya 4H mum {fmt_price(invalid)} üstünde kapanırsa planı askıya al.")

    lines += [
        "",
        "Not: Otomatik emir yok. Grafiği ChatGPT’ye kontrol ettir. İşleme girersen TP reduce-only olsun.",
        "2+ kademe dolarsa ortalama girişe göre ortak tek TP hesaplat.",
    ]
    return "\n".join(lines)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"signals": {}}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"signals": {}}

def save_state(state):
    now_ts = now_utc().timestamp()
    cleaned = {}
    for k, v in state.get("signals", {}).items():
        ts = float(v.get("ts", 0))
        if now_ts - ts <= 48 * 3600:
            cleaned[k] = v
    state["signals"] = cleaned
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def cooldown_allows(sig, state):
    key = f"{sig['symbol']}:{sig['direction']}"
    last = state.get("signals", {}).get(key)
    now_ts = now_utc().timestamp()
    if not last:
        return True, "yeni"
    age_h = (now_ts - float(last.get("ts", 0))) / 3600
    last_score = float(last.get("score", 0))
    if age_h >= COOLDOWN_HOURS:
        return True, f"cooldown bitti ({age_h:.1f}s)"
    if sig["score"] >= last_score + 1.0:
        return True, f"skor ciddi arttı ({last_score:.1f}→{sig['score']:.1f})"
    return False, f"cooldown aktif ({age_h:.1f}/{COOLDOWN_HOURS:.0f}s)"

def update_state_for_signal(sig, state):
    key = f"{sig['symbol']}:{sig['direction']}"
    state.setdefault("signals", {})[key] = {
        "ts": now_utc().timestamp(),
        "score": sig["score"],
        "price": sig["price"],
    }

def scan():
    started = time.time()
    print(f"{tr_time_str()} | {VERSION} tarama başladı")

    state = load_state()
    tmap = ticker_map()
    time.sleep(REQUEST_SLEEP_SECONDS)
    active = instruments_active()
    time.sleep(REQUEST_SLEEP_SECONDS)
    btc = btc_filter()

    syms = universe(active, tmap)
    print(f"{len(syms)} coin taranacak | BTC weak={btc.get('weak')} strong={btc.get('strong')}")

    candidates = []
    for idx, sym in enumerate(syms, 1):
        try:
            sig = analyze_symbol(sym, tmap.get(sym, {}), btc)
            if sig:
                ok, why = cooldown_allows(sig, state)
                if ok:
                    sig["cooldown_reason"] = why
                    candidates.append(sig)
                    print(f"{idx}/{len(syms)} {sym} {sig['direction']} skor={sig['score']} OK {why}")
                else:
                    print(f"{idx}/{len(syms)} {sym} {sig['direction']} skor={sig['score']} skip {why}")
            elif idx % 10 == 0 or idx == len(syms):
                print(f"... {idx}/{len(syms)}")
        except Exception as e:
            print(f"{sym} analiz hata: {repr(e)}")
        time.sleep(REQUEST_SLEEP_SECONDS)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    final = candidates[:MAX_SIGNALS_PER_RUN]

    manual_run = os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"

    if final:
        header = (
            f"✅ <b>{VERSION}</b>\n"
            f"{tr_time_str()} | {len(syms)} coin tarandı | {len(final)} sinyal\n"
            f"Tarama: 15m / 1H / 4H / 1D | GitHub Actions 5 dk\n"
            f"Veri kaynağı: Bybit USDT perpetual public market data\n"
            f"Max açık notional hedefi: ana para x3 ≈ {fmt_usdt(ACCOUNT_CAPITAL_USDT*3)} USDT "
            f"(gerekirse max x4 ≈ {fmt_usdt(ACCOUNT_CAPITAL_USDT*4)} USDT)\n"
            f"Otomatik emir yok."
        )
        tg_send(header)
        for sig in final:
            tg_send(signal_message(sig))
            update_state_for_signal(sig, state)
            time.sleep(0.5)
    else:
        msg = (
            f"ℹ️ <b>{VERSION}</b>\n"
            f"{tr_time_str()} | {len(syms)} coin tarandı.\n"
            f"Kalite eşiğini geçen yeni sinyal yok.\n"
            f"Bu mesaj sadece manuel testte veya SEND_NO_SIGNAL=true iken gönderilir."
        )
        print(msg)
        if SEND_NO_SIGNAL or manual_run:
            tg_send(msg)

    save_state(state)
    print(f"{tr_time_str()} | Tarama bitti | {time.time()-started:.1f} sn | sinyal {len(final)}")

if __name__ == "__main__":
    try:
        scan()
    except Exception as e:
        err = f"⚠️ {VERSION} hata:\n{repr(e)}"
        print(err)
        tg_send(err)
        if not os.path.exists(STATE_FILE):
            save_state({"signals": {}})
        raise
