#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CopyGuard GitHub Actions OKX v3

GitHub Actions üzerinde:
- Binance Futures API HTTP 451 verdi.
- Bybit API HTTP 403 verdi.
Bu sürüm OKX public market data kullanır.

Özellikler:
- API key istemez.
- Otomatik emir açmaz.
- Telegram'a sinyal gönderir.
- 5 dakikada bir GitHub Actions ile çalışır.
- 15m / 1H / 4H / 1D bakar.
"""

import os, json, time, math, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

VERSION = "CopyGuard GitHub Actions OKX v3.2"
OKX_BASE = os.getenv("OKX_BASE_URL", "https://www.okx.com").rstrip("/")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

ACCOUNT_CAPITAL_USDT = float(os.getenv("ACCOUNT_CAPITAL_USDT", "500"))
POSITION_USDT_PER_SIGNAL = float(os.getenv("POSITION_USDT_PER_SIGNAL", "40"))

MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "15000000"))
MAX_24H_CHANGE_PCT = float(os.getenv("MAX_24H_CHANGE_PCT", "18"))
MAX_SIGNALS_PER_RUN = int(os.getenv("MAX_SIGNALS_PER_RUN", "5"))

MIN_LONG_SCORE = float(os.getenv("MIN_LONG_SCORE", "8.0"))
MIN_SHORT_SCORE = float(os.getenv("MIN_SHORT_SCORE", "8.7"))
COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "6"))
SEND_NO_SIGNAL = os.getenv("SEND_NO_SIGNAL", "false").lower() in ("1", "true", "yes", "evet")
STATE_FILE = os.getenv("STATE_FILE", "copyguard_state.json")
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.03"))

UA = "Mozilla/5.0 CopyGuard-GitHub-Actions-OKX-v3"

BASES = [
    "BTC","ETH","BNB","SOL","XRP","ADA","LINK","AVAX","DOT","LTC","BCH","TRX","XLM","ETC","ATOM",
    "NEAR","APT","ARB","OP","SUI","INJ","UNI","AAVE","FIL","HBAR","ICP","RENDER","FET","TAO",
    "SEI","TIA","ALGO","VET","EGLD","RUNE","STX","LDO","PENDLE","ENA","ONDO","JUP","PYTH",
    "IMX","DYDX","CRV","COMP","SNX","GMX","WLD","ORDI","ARKM"
]
BLACKLIST = {"SHIB","PEPE","FLOKI","BONK","WIF","MEME","BOME","TURBO","DOGS","TRUMP","SATS","RATS"}

def now_utc():
    return datetime.now(timezone.utc)

def tr_time():
    return (now_utc() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S TR")

def sf(x, d=0.0):
    try:
        if x is None or x == "":
            return d
        return float(x)
    except Exception:
        return d

def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def okx(path, params=None):
    url = OKX_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = http_json(url)
    if str(data.get("code")) != "0":
        raise RuntimeError(f"OKX hata code={data.get('code')} msg={data.get('msg')}")
    return data.get("data", [])

def tg(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secret eksik.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            print("Telegram send:", resp.status)
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        print("Telegram HTTP hata:", e.code, e.read().decode("utf-8", errors="replace")[:500])
        return False
    except Exception as e:
        print("Telegram hata:", repr(e))
        return False

def fp(x):
    x = sf(x)
    if x >= 100: return f"{x:.2f}"
    if x >= 10: return f"{x:.3f}"
    if x >= 1: return f"{x:.4f}"
    if x >= 0.1: return f"{x:.5f}"
    if x >= 0.01: return f"{x:.6f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")

def fu(x):
    return f"{sf(x):.1f}".rstrip("0").rstrip(".")

def ema(vals, n):
    if not vals: return []
    k = 2/(n+1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v*k + out[-1]*(1-k))
    return out

def rsi(vals, n=14):
    if len(vals) < n+2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(vals)):
        d = vals[i]-vals[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag = sum(gains[:n])/n
    al = sum(losses[:n])/n
    for i in range(n, len(gains)):
        ag = (ag*(n-1)+gains[i])/n
        al = (al*(n-1)+losses[i])/n
    if al == 0: return 100.0
    rs = ag/al
    return 100 - 100/(1+rs)

def macd_delta(vals):
    if len(vals) < 40:
        return 0.0, 0.0
    e12, e26 = ema(vals,12), ema(vals,26)
    m = [a-b for a,b in zip(e12[-len(e26):], e26)]
    sig = ema(m,9)
    h = [a-b for a,b in zip(m[-len(sig):], sig)]
    return h[-1], h[-1]-h[-2] if len(h) > 1 else 0.0

def atr(c, n=14):
    if len(c) < n+1: return 0.0
    trs = []
    for i in range(1, len(c)):
        h,l,pc = c[i]["high"], c[i]["low"], c[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-n:]) / min(n, len(trs))

BAR = {"15m":"15m", "1h":"1H", "4h":"4H", "1d":"1D"}

def candles(inst, tf, limit=180):
    data = okx("/api/v5/market/candles", {"instId": inst, "bar": BAR[tf], "limit": str(limit)})
    rows = []
    for k in data:
        # OKX candles: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
        rows.append({
            "ts": int(k[0]),
            "open": sf(k[1]), "high": sf(k[2]), "low": sf(k[3]), "close": sf(k[4]),
            "volume": sf(k[5]),
            "turnover": sf(k[7]) if len(k) > 7 else sf(k[6]),
            "confirm": str(k[8]) if len(k) > 8 else "1",
        })
    rows.sort(key=lambda x: x["ts"])
    if rows and rows[-1].get("confirm") == "0":
        rows = rows[:-1]
    elif len(rows) > 2:
        # Kapanmış mum garantisi için son mumu at.
        rows = rows[:-1]
    return rows

def summary(c):
    cl = [x["close"] for x in c]
    e7, e25, e99 = ema(cl,7)[-1], ema(cl,25)[-1], ema(cl,99)[-1]
    hist, dh = macd_delta(cl)
    return {
        "price": cl[-1], "ema7": e7, "ema25": e25, "ema99": e99,
        "rsi": rsi(cl), "macd_hist": hist, "macd_delta": dh, "atr": atr(c)
    }

def label(s):
    if s["price"] > s["ema25"] and s["ema7"] > s["ema25"] and s["macd_delta"] > 0: return "pozitif"
    if s["price"] < s["ema25"] and s["ema7"] < s["ema25"] and s["macd_delta"] < 0: return "negatif"
    if s["macd_delta"] > 0: return "toparlanıyor"
    if s["macd_delta"] < 0: return "zayıflıyor"
    return "nötr"

def ticker_map():
    out = {}
    for t in okx("/api/v5/market/tickers", {"instType": "SWAP"}):
        inst = t.get("instId")
        if not inst or not inst.endswith("-USDT-SWAP"):
            continue
        last = sf(t.get("last"))
        open24h = sf(t.get("open24h"))
        chg = ((last - open24h) / open24h * 100) if open24h else 0.0

        # OKX SWAP tarafında volCcy24h çoğu üründe base coin miktarıdır.
        # Hacim filtresini USDT karşılığına çevirmek için last fiyatla çarpıyoruz.
        # Eski v3.1'de BTC/ETH/SOL/LINK gibi pahalı coinler bu yüzden yanlışlıkla eleniyordu.
        base_vol = sf(t.get("volCcy24h"))
        contract_vol = sf(t.get("vol24h"))
        turnover_usdt = base_vol * last if base_vol and last else 0.0
        if turnover_usdt <= 0 and contract_vol and last:
            turnover_usdt = contract_vol * last

        out[inst] = {
            "inst": inst,
            "last": last,
            "turnover": turnover_usdt,
            "raw_volCcy24h": base_vol,
            "raw_vol24h": contract_vol,
            "change": chg,
        }
    return out

def active_instruments():
    active = set()
    try:
        for x in okx("/api/v5/public/instruments", {"instType": "SWAP"}):
            if x.get("state") == "live" and x.get("settleCcy") == "USDT":
                active.add(x.get("instId"))
    except Exception as e:
        print("instrument listesi alınamadı:", repr(e))
    return active

def funding(inst):
    try:
        data = okx("/api/v5/public/funding-rate", {"instId": inst})
        if data:
            return sf(data[0].get("fundingRate"))
    except Exception:
        return 0.0
    return 0.0

def open_interest(inst):
    try:
        data = okx("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst})
        if data:
            return sf(data[0].get("oi")) or sf(data[0].get("oiCcy"))
    except Exception:
        return 0.0
    return 0.0

def okx_available_from_our_list(active, tm):
    found = []
    missing = []
    for b in BASES:
        if b in BLACKLIST:
            continue
        inst = f"{b}-USDT-SWAP"
        if (not active or inst in active) and inst in tm:
            found.append(b)
        else:
            missing.append(b)
    return found, missing

def universe(active, tm):
    syms = []
    skipped_low_volume = []
    skipped_big_move = []
    for b in BASES:
        if b in BLACKLIST:
            continue
        inst = f"{b}-USDT-SWAP"
        if active and inst not in active:
            continue
        t = tm.get(inst)
        if not t:
            continue
        if t["turnover"] < MIN_24H_QUOTE_VOLUME:
            skipped_low_volume.append(b)
            continue
        if abs(t["change"]) > MAX_24H_CHANGE_PCT:
            skipped_big_move.append(b)
            continue
        syms.append(inst)
    return syms, skipped_low_volume, skipped_big_move

def wick_bad(c):
    x = c[-1]
    rng = max(x["high"]-x["low"], 1e-12)
    body = abs(x["close"]-x["open"])
    upper = x["high"]-max(x["close"], x["open"])
    lower = min(x["close"], x["open"])-x["low"]
    return body/rng < 0.18 or upper/rng > 0.62 or lower/rng > 0.62

def btc_filter():
    try:
        c1 = candles("BTC-USDT-SWAP","1h")
        time.sleep(REQUEST_SLEEP_SECONDS)
        c4 = candles("BTC-USDT-SWAP","4h")
        s1, s4 = summary(c1), summary(c4)
        strong = s1["price"] > s1["ema25"] and s4["price"] > s4["ema25"] and s4["price"] > s4["ema99"] and s1["macd_delta"] > 0 and s1["rsi"] > 50
        weak = s1["price"] < s1["ema25"] and s4["price"] < s4["ema25"] and s4["price"] < s4["ema99"] and s1["macd_delta"] < 0 and s1["rsi"] < 45
        return {"strong": strong, "weak": weak}
    except Exception as e:
        print("BTC filtre hata:", repr(e))
        return {"strong": False, "weak": False}

def analyze(inst, tick, btc):
    c15 = candles(inst,"15m"); time.sleep(REQUEST_SLEEP_SECONDS)
    c1 = candles(inst,"1h"); time.sleep(REQUEST_SLEEP_SECONDS)
    c4 = candles(inst,"4h"); time.sleep(REQUEST_SLEEP_SECONDS)
    cd = candles(inst,"1d"); time.sleep(REQUEST_SLEEP_SECONDS)
    if min(len(c15), len(c1), len(c4), len(cd)) < 105:
        return None

    s15, s1, s4, sd = summary(c15), summary(c1), summary(c4), summary(cd)
    price = s15["price"]
    a15 = max(min((s15["atr"]/price) if price else 0.004, 0.03), 0.0025)

    lows = [x["low"] for x in c1[-36:-1]]
    highs = [x["high"] for x in c1[-36:-1]]
    support, resistance = min(lows), max(highs)

    fnd = funding(inst)
    time.sleep(REQUEST_SLEEP_SECONDS)
    oi = open_interest(inst)
    time.sleep(REQUEST_SLEEP_SECONDS)

    vol_now = c15[-1]["volume"]
    vol_avg = sum(x["volume"] for x in c15[-25:-1]) / 24 if len(c15) > 25 else vol_now
    vol_boost = vol_now > vol_avg * 1.15

    long, short = 0.0, 0.0
    lr, sr = [], []

    # 1D filtre
    if sd["price"] > sd["ema99"]:
        long += 0.6; lr.append("1D EMA99 üstü: büyük yön long için uygun")
    else:
        long -= 0.4; lr.append("1D EMA99 altı: long daha seçici")
    if sd["price"] > sd["ema25"] and sd["ema7"] > sd["ema25"]:
        long += 0.6; lr.append("1D EMA7/25 pozitif")
    if sd["price"] < sd["ema25"] and sd["ema7"] < sd["ema25"]:
        short += 0.8; sr.append("1D EMA7/25 zayıf")
    if sd["price"] < sd["ema99"] and sd["ema7"] < sd["ema25"] < sd["ema99"] and sd["rsi"] < 35:
        long -= 1.2; lr.append("1D ağır düşüş filtresi")
    if sd["price"] > sd["ema99"] and sd["ema7"] > sd["ema25"] > sd["ema99"]:
        short -= 1.2; sr.append("1D güçlü boğa: short zorlaştırıldı")
    if sd["macd_delta"] > 0: long += 0.3
    if sd["macd_delta"] < 0: short += 0.3

    # 4H
    if s4["price"] > s4["ema99"]:
        long += 1.0; lr.append("4H EMA99 üstü")
    else:
        short += 0.7; sr.append("4H EMA99 altı")
    if s4["ema7"] > s4["ema25"]:
        long += 1.0; lr.append("4H EMA7/25 pozitif")
    elif s4["ema7"] < s4["ema25"]:
        short += 1.0; sr.append("4H EMA7/25 negatif")
    if 40 <= s4["rsi"] <= 62: long += 0.4
    if 42 <= s4["rsi"] <= 58 and s4["macd_delta"] < 0: short += 0.4
    if s4["macd_delta"] > 0:
        long += 0.7; lr.append("4H MACD toparlanıyor")
    if s4["macd_delta"] < 0:
        short += 0.7; sr.append("4H MACD zayıflıyor")

    # 1H
    if s1["price"] > s1["ema25"] and s1["ema7"] >= s1["ema25"]:
        long += 1.4; lr.append("1H EMA25 geri kazanılmış")
    if s1["price"] < s1["ema25"] and s1["ema7"] <= s1["ema25"]:
        short += 1.4; sr.append("1H EMA25 altı")
    if 42 <= s1["rsi"] <= 64:
        long += 0.5; lr.append(f"1H RSI sağlıklı ({s1['rsi']:.0f})")
    if s1["rsi"] < 55 and s1["macd_delta"] < 0:
        short += 0.5; sr.append(f"1H RSI/MACD aşağı ({s1['rsi']:.0f})")
    if s1["macd_delta"] > 0:
        long += 0.7; lr.append("1H MACD güçleniyor")
    if s1["macd_delta"] < 0:
        short += 0.7; sr.append("1H MACD aşağı")

    # 15m
    if s15["price"] > s15["ema25"] and s15["ema7"] > s15["ema25"]:
        long += 1.0; lr.append("15m giriş momentumu long")
    if s15["price"] < s15["ema25"] and s15["ema7"] < s15["ema25"]:
        short += 1.0; sr.append("15m giriş momentumu short")
    if s15["rsi"] >= 45 and s15["macd_delta"] > 0:
        long += 0.6; lr.append("15m RSI/MACD tepki")
    if s15["rsi"] <= 55 and s15["macd_delta"] < 0:
        short += 0.6; sr.append("15m RSI/MACD red")

    # Destek/direnç
    ds = (price-support)/price
    dr = (resistance-price)/price
    near_support = 0 <= ds <= max(0.018, a15*2.4)
    near_res = 0 <= dr <= max(0.018, a15*2.4)
    if near_support:
        long += 1.0; lr.append("destek bölgesine yakın")
    elif price > resistance*0.995:
        long -= 0.8; lr.append("dirence çok yakın")
    if near_res:
        short += 1.0; sr.append("direnç bölgesine yakın")
    elif price < support*1.005:
        short -= 0.8; sr.append("desteğe çok yakın")

    if resistance > price*(1+max(0.006, a15*1.2)):
        long += 0.5; lr.append("long için TP alanı var")
    else:
        long -= 0.4
    if support < price*(1-max(0.006, a15*1.2)):
        short += 0.5; sr.append("short için TP alanı var")
    else:
        short -= 0.4

    if vol_boost and c15[-1]["close"] >= c15[-1]["open"]:
        long += 0.5; lr.append("tepki hacmi artmış")
    if vol_boost and c15[-1]["close"] < c15[-1]["open"]:
        short += 0.5; sr.append("satış hacmi artmış")

    if oi > 0:
        long += 0.2; short += 0.2
    if fnd > 0.0008:
        long -= 0.5; lr.append("funding long kalabalık")
    if fnd < -0.0005:
        short -= 0.5; sr.append("funding short kalabalık")
        long += 0.2

    if btc.get("strong"):
        long += 0.8; lr.append("BTC filtresi long destekli")
        short -= 0.8
    if btc.get("weak"):
        long -= 0.9
        short += 0.7; sr.append("BTC filtresi short destekli")

    if wick_bad(c15):
        long -= 0.4; short -= 0.4

    if s4["price"] < s4["ema25"] and s1["price"] < s1["ema25"] and s15["price"] < s15["ema25"]:
        long -= 0.8
    if s4["price"] > s4["ema25"] and s1["price"] > s1["ema25"] and s15["price"] > s15["ema25"]:
        short -= 0.8

    direction, score, reasons = None, 0, []
    if long >= MIN_LONG_SCORE and long >= short + 0.5:
        direction, score, reasons = "LONG", long, lr[:8]
    elif short >= MIN_SHORT_SCORE and short >= long + 0.8:
        direction, score, reasons = "SHORT", short, sr[:8]
    else:
        return None

    return {
        "inst": inst, "symbol": inst.replace("-","").replace("SWAP",""),
        "direction": direction, "score": round(score,2), "price": price,
        "funding": fnd, "oi": oi, "quote_vol": tick["turnover"], "change_pct": tick["change"],
        "support": support, "resistance": resistance, "atr_pct": a15,
        "rsi_15m": s15["rsi"], "rsi_1h": s1["rsi"], "rsi_4h": s4["rsi"], "rsi_1d": sd["rsi"],
        "tf_1d": label(sd), "tf_4h": label(s4), "tf_1h": label(s1), "tf_15m": label(s15),
        "reasons": reasons
    }

def plan(sig):
    p, atrp = sig["price"], sig["atr_pct"]
    weights = [0.25,0.22,0.20,0.18,0.15]
    if sig["direction"] == "LONG":
        entries = [p*(1-x) for x in [0, .55*atrp, 1.10*atrp, 1.75*atrp, 2.55*atrp]]
        tps = [e*(1+tp) for e,tp in zip(entries, [max(.006,.95*atrp),max(.007,1.10*atrp),max(.008,1.25*atrp),max(.009,1.40*atrp),max(.010,1.55*atrp)])]
        invalid = min(sig["support"]*.985, entries[-1]*(1-max(.006,atrp)))
        alarms = [entries[1], entries[3], max(tps[0], p*1.006), invalid]
    else:
        entries = [p*(1+x) for x in [0, .55*atrp, 1.10*atrp, 1.75*atrp, 2.55*atrp]]
        tps = [e*(1-tp) for e,tp in zip(entries, [max(.006,.95*atrp),max(.007,1.10*atrp),max(.008,1.25*atrp),max(.009,1.40*atrp),max(.010,1.55*atrp)])]
        invalid = max(sig["resistance"]*1.015, entries[-1]*(1+max(.006,atrp)))
        alarms = [entries[1], entries[3], min(tps[0], p*.994), invalid]
    amounts = [POSITION_USDT_PER_SIGNAL*w for w in weights]
    return entries, amounts, tps, invalid, alarms

def message(sig):
    emoji = "🟢" if sig["direction"]=="LONG" else "🔴"
    entries, amounts, tps, invalid, alarms = plan(sig)
    lines = [
        f"{emoji} <b>{sig['symbol']} {sig['direction']} ADAYI</b>",
        f"Skor: <b>{sig['score']:.1f}/10</b>",
        f"Saat: {tr_time()}",
        "",
        "Veri kaynağı: OKX USDT perpetual public market data",
        "Not: Plan Binance Futures üzerinde manuel/copy trade için yorumlanacak.",
        "",
        "Zaman dilimleri:",
        f"1D: {sig['tf_1d']} | 4H: {sig['tf_4h']} | 1H: {sig['tf_1h']} | 15m: {sig['tf_15m']}",
        "",
        "Canlı veri:",
        f"Son fiyat: {fp(sig['price'])}",
        f"24s hacim: {sig['quote_vol']/1_000_000:.1f}M | 24s değişim: {sig['change_pct']:.2f}%",
        f"Funding: {sig['funding']*100:.4f}% | OI: {sig['oi']:.0f}",
        f"RSI 15m/1H/4H/1D: {sig['rsi_15m']:.0f}/{sig['rsi_1h']:.0f}/{sig['rsi_4h']:.0f}/{sig['rsi_1d']:.0f}",
        "",
        "Sebep:",
    ]
    for r in sig["reasons"][:7]:
        lines.append(f"- {r}")
    lines += ["", "5 kademeli plan:"]
    for i,(e,a,tpv) in enumerate(zip(entries,amounts,tps),1):
        lines.append(f"{i}) {fp(e)} — {fu(a)} USDT — TP {fp(tpv)}")
    lines += ["", "Alarm:", " / ".join(fp(x) for x in alarms), ""]
    if sig["direction"] == "LONG":
        lines.append(f"İptal: 1H veya 4H mum {fp(invalid)} altında kapanırsa planı askıya al.")
    else:
        lines.append(f"İptal: 1H veya 4H mum {fp(invalid)} üstünde kapanırsa planı askıya al.")
    lines += ["", "Not: Otomatik emir yok. Grafiği ChatGPT’ye kontrol ettir. TP reduce-only olsun.", "2+ kademe dolarsa ortalama girişe göre ortak tek TP hesaplat."]
    return "\n".join(lines)

def load_state():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f: return json.load(f)
    except Exception:
        return {"signals":{}}

def save_state(st):
    now = now_utc().timestamp()
    st["signals"] = {k:v for k,v in st.get("signals",{}).items() if now-float(v.get("ts",0)) <= 48*3600}
    with open(STATE_FILE,"w",encoding="utf-8") as f: json.dump(st,f,ensure_ascii=False,indent=2)

def cooldown(sig, st):
    key = sig["inst"] + ":" + sig["direction"]
    last = st.get("signals",{}).get(key)
    now = now_utc().timestamp()
    if not last: return True, "yeni"
    age = (now-float(last.get("ts",0)))/3600
    if age >= COOLDOWN_HOURS: return True, f"cooldown bitti ({age:.1f}s)"
    if sig["score"] >= float(last.get("score",0)) + 1.0: return True, "skor ciddi arttı"
    return False, f"cooldown aktif ({age:.1f}/{COOLDOWN_HOURS:.0f}s)"

def state_update(sig, st):
    st.setdefault("signals",{})[sig["inst"]+":"+sig["direction"]] = {"ts": now_utc().timestamp(), "score": sig["score"], "price": sig["price"]}

def scan():
    start = time.time()
    print(f"{tr_time()} | {VERSION} tarama başladı")
    st = load_state()
    tm = ticker_map()
    time.sleep(REQUEST_SLEEP_SECONDS)
    active = active_instruments()
    time.sleep(REQUEST_SLEEP_SECONDS)
    btc = btc_filter()
    available_clean, missing_clean = okx_available_from_our_list(active, tm)
    syms, skipped_low_volume, skipped_big_move = universe(active, tm)
    print(f"{len(syms)} coin taranacak | BTC strong={btc.get('strong')} weak={btc.get('weak')}")
    scanned_clean = [x.replace("-USDT-SWAP", "") for x in syms]
    print("OKX'te listeden bulunanlar:", ", ".join(available_clean))
    print("Taranan coinler:", ", ".join(scanned_clean))
    if skipped_low_volume:
        print("Hacimden elenenler:", ", ".join(skipped_low_volume))
    if skipped_big_move:
        print("Aşırı hareketten elenenler:", ", ".join(skipped_big_move))
    if missing_clean:
        print("OKX USDT-SWAP tarafında bulunamayanlar:", ", ".join(missing_clean))

    cands = []
    for i,inst in enumerate(syms,1):
        try:
            sig = analyze(inst, tm[inst], btc)
            if sig:
                ok, why = cooldown(sig, st)
                if ok:
                    cands.append(sig)
                    print(f"{i}/{len(syms)} {inst} {sig['direction']} skor={sig['score']} OK")
                else:
                    print(f"{i}/{len(syms)} {inst} {sig['direction']} skip {why}")
            elif i % 10 == 0 or i == len(syms):
                print(f"... {i}/{len(syms)}")
        except Exception as e:
            print(f"{inst} hata: {repr(e)}")
        time.sleep(REQUEST_SLEEP_SECONDS)

    cands.sort(key=lambda x: x["score"], reverse=True)
    final = cands[:MAX_SIGNALS_PER_RUN]
    manual = os.getenv("GITHUB_EVENT_NAME","") == "workflow_dispatch"

    if final:
        tg(f"✅ <b>{VERSION}</b>\n{tr_time()} | {len(syms)} coin tarandı | {len(final)} sinyal\nTarama: 15m / 1H / 4H / 1D | GitHub 5 dk\nVeri: OKX public market data\nMax notional hedefi: x3 ≈ {fu(ACCOUNT_CAPITAL_USDT*3)} USDT | max x4 ≈ {fu(ACCOUNT_CAPITAL_USDT*4)} USDT\nOtomatik emir yok.")
        for sig in final:
            tg(message(sig))
            state_update(sig, st)
            time.sleep(0.5)
    else:
        coin_line = ", ".join(scanned_clean[:60]) if scanned_clean else "Yok"
        avail_line = ", ".join(available_clean[:80]) if available_clean else "Yok"
        missing_line = ", ".join(missing_clean[:40]) if missing_clean else "Yok"
        lowvol_line = ", ".join(skipped_low_volume[:50]) if skipped_low_volume else "Yok"
        bigmove_line = ", ".join(skipped_big_move[:30]) if skipped_big_move else "Yok"
        msg = (
            f"ℹ️ <b>{VERSION}</b>\n"
            f"{tr_time()} | {len(syms)} coin tarandı.\n"
            f"Tarananlar: {coin_line}\n"
            f"OKX'te listemizden bulunanlar: {avail_line}\n"
            f"OKX'te yok/aktif değil görünenler: {missing_line}\n"
            f"Hacimden elenenler: {lowvol_line}\n"
            f"Aşırı hareketten elenenler: {bigmove_line}\n"
            f"Hacim filtresi: {MIN_24H_QUOTE_VOLUME/1_000_000:.0f}M USDT eşdeğeri eşdeğeri\n"
            f"Kalite eşiğini geçen yeni sinyal yok.\n"
            f"Bu mesaj sadece manuel testte veya SEND_NO_SIGNAL=true iken gönderilir."
        )
        print(msg)
        if SEND_NO_SIGNAL or manual:
            tg(msg)

    save_state(st)
    print(f"{tr_time()} | Tarama bitti | {time.time()-start:.1f} sn | sinyal {len(final)}")

if __name__ == "__main__":
    try:
        scan()
    except Exception as e:
        err = f"⚠️ {VERSION} hata:\n{repr(e)}"
        print(err)
        tg(err)
        save_state(load_state())
        raise
