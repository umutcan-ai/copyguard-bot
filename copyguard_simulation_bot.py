#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CopyGuard Simulation Bot GitHub v1
GERÇEK EMİR AÇMAZ. 500 USDT sanal copy trade hesabı gibi çalışır.
GitHub'da Binance Futures 451 verdiği için bu paper sürüm OKX USDT-SWAP public data kullanır.
Sadece LONG. Yeni fırsat taraması 5 dk, açık sanal pozisyon yönetimi her workflow çalışmasında yapılır.
"""

import os, json, math, time, uuid, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta

VERSION = "CopyGuard Simulation Bot GitHub v1"
OKX_BASE = os.getenv("OKX_BASE_URL", "https://www.okx.com").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("PAPER_TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("PAPER_TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = os.getenv("PAPER_STATE_FILE", "paper_state.json")

START_BALANCE = float(os.getenv("PAPER_START_EQUITY_USDT", "500"))
# Pozisyon boyutu sabit değil: güncel sanal equity'ye göre ölçeklenir.
PER_COIN_PLAN_RATIO = float(os.getenv("PER_COIN_PLAN_RATIO", "0.50"))
EXCEPTION_PLAN_RATIO = float(os.getenv("EXCEPTION_PLAN_RATIO", "0.25"))
PLAN_NOTIONAL = START_BALANCE * PER_COIN_PLAN_RATIO
MIN_24H_QUOTE_VOLUME = float(os.getenv("MIN_24H_QUOTE_VOLUME", "15000000"))
MAX_24H_CHANGE_PCT = float(os.getenv("MAX_24H_CHANGE_PCT", "18"))

MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
EXCEPTION_MAX_POSITIONS = int(os.getenv("EXCEPTION_MAX_POSITIONS", "6"))
MAX_ORDER_COINS = int(os.getenv("MAX_ORDER_COINS", "10"))
COMFORT_EXPOSURE_X = float(os.getenv("COMFORT_EXPOSURE_X", "2.0"))
CANCEL_EXTERNAL_ORDERS_AT_X = float(os.getenv("CANCEL_EXTERNAL_ORDERS_AT_X", "2.5"))
NORMAL_MAX_EXPOSURE_X = float(os.getenv("NORMAL_MAX_EXPOSURE_X", "3.0"))
RESCUE_MAX_EXPOSURE_X = float(os.getenv("RESCUE_MAX_EXPOSURE_X", "3.5"))
EMERGENCY_DCA_MAX_X = float(os.getenv("EMERGENCY_DCA_MAX_X", "4.0"))
EXCEPTION_LONG_SCORE = float(os.getenv("EXCEPTION_LONG_SCORE", "9.2"))
REPLACE_SCORE_DELTA = float(os.getenv("REPLACE_SCORE_DELTA", "0.8"))
REPRICE_STRONG_SCORE = float(os.getenv("REPRICE_STRONG_SCORE", "8.5"))
PENDING_REVIEW_HOURS = float(os.getenv("PENDING_REVIEW_HOURS", "12"))
REPRICE_COOLDOWN_MINUTES = float(os.getenv("REPRICE_COOLDOWN_MINUTES", "30"))
MAX_UP_REPRICE_PER_DAY = int(os.getenv("MAX_UP_REPRICE_PER_DAY", "2"))

SCAN_INTERVAL_MINUTES = float(os.getenv("SCAN_INTERVAL_MINUTES", "5"))
MAX_NEW_POSITIONS_PER_SCAN = int(os.getenv("MAX_NEW_POSITIONS_PER_SCAN", "3"))
MIN_LONG_SCORE = float(os.getenv("MIN_LONG_SCORE", "7.8"))
COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "6"))
TAKER_FEE_RATE = float(os.getenv("TAKER_FEE_RATE", "0.0005"))
SLIPPAGE_RATE = float(os.getenv("PAPER_SLIPPAGE_RATE", "0.0002"))
DAILY_NET_LOSS_LIMIT = float(os.getenv("DAILY_NET_LOSS_LIMIT_USDT", "-15"))
HARD_DAILY_NET_LOSS_LIMIT = float(os.getenv("HARD_DAILY_NET_LOSS_LIMIT_USDT", "-25"))
DAILY_REPORT_HOUR_TR = int(os.getenv("DAILY_REPORT_HOUR_TR", "23"))
DAILY_REPORT_MINUTE_TR = int(os.getenv("DAILY_REPORT_MINUTE_TR", "55"))
REQ_SLEEP = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.03"))

UA = "Mozilla/5.0 CopyGuard-Paper-Manager-GitHub-v1"
BASES = ["BTC","ETH","BNB","SOL","XRP","ADA","LINK","AVAX","DOT","LTC","BCH","TRX","XLM","ETC","ATOM",
"NEAR","APT","ARB","OP","SUI","INJ","UNI","AAVE","FIL","HBAR","ICP","RENDER","TAO","SEI","TIA",
"ALGO","EGLD","STX","LDO","PENDLE","ENA","ONDO","JUP","PYTH","IMX","DYDX","CRV","COMP","SNX",
"GMX","WLD","ORDI","ARKM"]
BLACKLIST = {"SHIB","PEPE","FLOKI","BONK","WIF","MEME","BOME","TURBO","DOGS","TRUMP","SATS","RATS"}
BAR = {"5m":"5m","15m":"15m","1h":"1H","4h":"4H","1d":"1D"}

def utcnow(): return datetime.now(timezone.utc)
def ts(): return utcnow().timestamp()
def trdt(): return utcnow() + timedelta(hours=3)
def tr_date(): return trdt().strftime("%Y-%m-%d")
def tr_time(): return trdt().strftime("%Y-%m-%d %H:%M:%S TR")
def sf(x,d=0.0):
    try:
        if x is None or x=="": return d
        return float(x)
    except Exception: return d
def fp(x):
    x=sf(x)
    if x>=100: return f"{x:.2f}"
    if x>=10: return f"{x:.3f}"
    if x>=1: return f"{x:.4f}"
    if x>=0.1: return f"{x:.5f}"
    if x>=0.01: return f"{x:.6f}"
    return f"{x:.8f}".rstrip("0").rstrip(".")
def fu(x): return f"{sf(x):.2f}".rstrip("0").rstrip(".")
def pct(x): return f"{sf(x):+.2f}%"
def nid(p): return p+"_"+uuid.uuid4().hex[:10]

def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent":UA, "Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))
def okx(path, params=None):
    url = OKX_BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
    data = http_json(url)
    if str(data.get("code")) != "0":
        raise RuntimeError(f"OKX hata code={data.get('code')} msg={data.get('msg')}")
    return data.get("data", [])

def tg_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secret eksik"); return False
    chunks=[]; s=str(text)
    while len(s)>3600:
        cut=s.rfind("\n",0,3600)
        if cut<1000: cut=3600
        chunks.append(s[:cut]); s=s[cut:].lstrip()
    chunks.append(s)
    okall=True
    for ch in chunks:
        url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        body=urllib.parse.urlencode({"chat_id":TELEGRAM_CHAT_ID,"text":ch,"parse_mode":"HTML","disable_web_page_preview":"true"}).encode()
        req=urllib.request.Request(url,data=body,headers={"User-Agent":UA})
        try:
            with urllib.request.urlopen(req,timeout=25) as r:
                okall = okall and (200 <= r.status < 300)
                print("Telegram", r.status)
        except Exception as e:
            print("Telegram hata:",repr(e)); okall=False
        time.sleep(0.25)
    return okall

def ema(v,n):
    if not v: return []
    k=2/(n+1); out=[v[0]]
    for x in v[1:]: out.append(x*k+out[-1]*(1-k))
    return out
def rsi(v,n=14):
    if len(v)<n+2: return 50.0
    g=[]; l=[]
    for i in range(1,len(v)):
        d=v[i]-v[i-1]; g.append(max(d,0)); l.append(max(-d,0))
    ag=sum(g[:n])/n; al=sum(l[:n])/n
    for i in range(n,len(g)):
        ag=(ag*(n-1)+g[i])/n; al=(al*(n-1)+l[i])/n
    if al==0: return 100.0
    rs=ag/al; return 100-100/(1+rs)
def macd_delta(v):
    if len(v)<40: return 0,0
    e12,e26=ema(v,12),ema(v,26)
    m=[a-b for a,b in zip(e12[-len(e26):],e26)]
    sig=ema(m,9); h=[a-b for a,b in zip(m[-len(sig):],sig)]
    return h[-1], h[-1]-h[-2] if len(h)>1 else 0
def atr(c,n=14):
    if len(c)<n+1: return 0
    trs=[]
    for i in range(1,len(c)):
        h,l,pc=c[i]["high"],c[i]["low"],c[i-1]["close"]
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-n:])/min(n,len(trs))
def wick_bad(c):
    if not c: return False
    x=c[-1]; rng=max(x["high"]-x["low"],1e-12)
    body=abs(x["close"]-x["open"]); upper=x["high"]-max(x["close"],x["open"]); lower=min(x["close"],x["open"])-x["low"]
    return body/rng<0.16 or upper/rng>0.64 or lower/rng>0.64
def summ(c):
    cl=[x["close"] for x in c]; e7,e25,e99=ema(cl,7)[-1],ema(cl,25)[-1],ema(cl,99)[-1]
    mh,md=macd_delta(cl)
    return {"price":cl[-1],"ema7":e7,"ema25":e25,"ema99":e99,"rsi":rsi(cl),"macd_hist":mh,"macd_delta":md,"atr":atr(c)}
def label(s):
    if s["price"]>s["ema25"] and s["ema7"]>s["ema25"] and s["macd_delta"]>0: return "pozitif"
    if s["price"]<s["ema25"] and s["ema7"]<s["ema25"] and s["macd_delta"]<0: return "negatif"
    return "toparlanıyor" if s["macd_delta"]>0 else ("zayıflıyor" if s["macd_delta"]<0 else "nötr")

def candles(inst, tf, limit=180):
    data=okx("/api/v5/market/candles", {"instId":inst,"bar":BAR[tf],"limit":str(limit)})
    rows=[]
    for k in data:
        rows.append({"ts":int(k[0]),"open":sf(k[1]),"high":sf(k[2]),"low":sf(k[3]),"close":sf(k[4]),"volume":sf(k[5]),"turnover":sf(k[7]) if len(k)>7 else sf(k[6]),"confirm":str(k[8]) if len(k)>8 else "1"})
    rows.sort(key=lambda x:x["ts"])
    if rows and rows[-1].get("confirm")=="0": rows=rows[:-1]
    elif len(rows)>2: rows=rows[:-1]
    return rows
def latest5(inst):
    try:
        c=candles(inst,"5m",5); return c[-1] if c else None
    except Exception: return None

def ticker_map():
    out={}
    for t in okx("/api/v5/market/tickers", {"instType":"SWAP"}):
        inst=t.get("instId")
        if not inst or not inst.endswith("-USDT-SWAP"): continue
        last=sf(t.get("last")); open24h=sf(t.get("open24h")); chg=((last-open24h)/open24h*100) if open24h else 0
        base_vol=sf(t.get("volCcy24h")); contract_vol=sf(t.get("vol24h"))
        turn=base_vol*last if base_vol and last else 0
        if turn<=0 and contract_vol and last: turn=contract_vol*last
        out[inst]={"inst":inst,"last":last,"turnover":turn,"change":chg}
    return out
def active_instruments():
    active=set()
    try:
        for x in okx("/api/v5/public/instruments", {"instType":"SWAP"}):
            if x.get("state")=="live" and x.get("settleCcy")=="USDT": active.add(x.get("instId"))
    except Exception as e: print("instrument hata",repr(e))
    return active
def funding(inst):
    try:
        d=okx("/api/v5/public/funding-rate", {"instId":inst})
        return sf(d[0].get("fundingRate")) if d else 0
    except Exception: return 0
def open_interest(inst):
    try:
        d=okx("/api/v5/public/open-interest", {"instType":"SWAP","instId":inst})
        return (sf(d[0].get("oi")) or sf(d[0].get("oiCcy"))) if d else 0
    except Exception: return 0

def universe(active,tm):
    syms=[]; skipped={"low_volume":[],"big_move":[],"missing":[]}
    for b in BASES:
        if b in BLACKLIST: continue
        inst=f"{b}-USDT-SWAP"
        if active and inst not in active: skipped["missing"].append(b); continue
        t=tm.get(inst)
        if not t: skipped["missing"].append(b); continue
        if t["turnover"]<MIN_24H_QUOTE_VOLUME: skipped["low_volume"].append(b); continue
        if abs(t["change"])>MAX_24H_CHANGE_PCT: skipped["big_move"].append(b); continue
        syms.append(inst)
    return syms,skipped
def btc_filter():
    try:
        c1=candles("BTC-USDT-SWAP","1h"); time.sleep(REQ_SLEEP); c4=candles("BTC-USDT-SWAP","4h")
        s1,s4=summ(c1),summ(c4)
        strong=s1["price"]>s1["ema25"] and s4["price"]>s4["ema25"] and s4["price"]>s4["ema99"] and s1["macd_delta"]>0 and s1["rsi"]>50
        weak=s1["price"]<s1["ema25"] and s4["price"]<s4["ema25"] and s4["price"]<s4["ema99"] and s1["macd_delta"]<0 and s1["rsi"]<45
        return {"strong":strong,"weak":weak,"rsi1h":s1["rsi"]}
    except Exception as e:
        print("BTC filtre hata",repr(e)); return {"strong":False,"weak":False,"rsi1h":50}

def new_daily(date,start_eq):
    return {"date":date,"start_equity":start_eq,"realized_pnl":0.0,"fees":0.0,"opened":0,"closed":0,"tp_closed":0,"stop_closed":0,"partial_reduces":0,"dca_fills":0,"wins":0,"losses":0,"max_equity":start_eq,"min_equity":start_eq,"events":[],"closed_trades":[],"rescue_summary":[],"report_sent":False}
def fresh_state():
    return {"version":VERSION,"created_at":tr_time(),"start_balance":START_BALANCE,"balance":START_BALANCE,"positions":{},"orders":[],"recent_signals":{},"last_scan_ts":0,"telegram_last_update_id":0,"pending_proposals":{},"daily":new_daily(tr_date(),START_BALANCE),"history":[]}
def load_state():
    if not os.path.exists(STATE_FILE): return fresh_state()
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f: st=json.load(f)
        if "positions" not in st or "orders" not in st: return fresh_state()
        return st
    except Exception: return fresh_state()
def save_state(st):
    st["history"]=st.get("history",[])[-300:]; st["daily"]["events"]=st["daily"].get("events",[])[-250:]; st["daily"]["closed_trades"]=st["daily"].get("closed_trades",[])[-80:]
    with open(STATE_FILE,"w",encoding="utf-8") as f: json.dump(st,f,ensure_ascii=False,indent=2)
def add_event(st,text,notify=False):
    item=f"{tr_time()} | {text}"; print(item)
    st["daily"].setdefault("events",[]).append(item); st.setdefault("history",[]).append(item)
    if notify: tg_send(text)
def pos_symbols(st): return set(st.get("positions",{}).keys())
def order_symbols(st): return set(o["inst"] for o in st.get("orders",[]) if o.get("side")=="BUY")
def pending_entry_symbols(st): return set(o["inst"] for o in st.get("orders",[]) if o.get("side")=="BUY" and o.get("role") in ("ENTRY","ENTRY_REPRICE"))
def current_prices(st,tm=None):
    if tm is None:
        try: tm=ticker_map()
        except Exception: tm={}
    prices={}
    symbols=set(st.get("positions",{}).keys()) | set(o.get("inst") for o in st.get("orders",[]))
    for inst in symbols:
        if inst in tm: prices[inst]=sf(tm[inst]["last"])
        elif inst in st.get("positions",{}): prices[inst]=sf(st["positions"][inst].get("last_price",st["positions"][inst].get("avg_entry")))
    return prices
def plan_notional(st, prices=None, exception=False):
    base = max(equity(st, prices or {}), 1.0)
    return base * (EXCEPTION_PLAN_RATIO if exception else PER_COIN_PLAN_RATIO)

def total_notional(st,prices=None):
    total=0
    for inst,p in st.get("positions",{}).items():
        pr=(prices or {}).get(inst, sf(p.get("last_price",p.get("avg_entry",0))))
        total += abs(sf(p.get("qty"))*sf(pr))
    return total
def potential_notional(st,prices=None):
    return total_notional(st,prices) + sum(sf(o.get("usdt")) for o in st.get("orders",[]) if o.get("side")=="BUY")
def exposure_x(st,prices=None): return total_notional(st,prices)/max(equity(st,prices),1.0)
def potential_x(st,prices=None): return potential_notional(st,prices)/max(equity(st,prices),1.0)
def unrealized(st,prices=None):
    u=0
    for inst,p in st.get("positions",{}).items():
        pr=(prices or {}).get(inst, sf(p.get("last_price",p.get("avg_entry",0))))
        u += sf(p.get("qty"))*(sf(pr)-sf(p.get("avg_entry")))
    return u
def equity(st,prices=None): return sf(st.get("balance",START_BALANCE)) + unrealized(st,prices)
def update_daily_eq(st,prices=None):
    e=equity(st,prices); d=st["daily"]; d["max_equity"]=max(sf(d.get("max_equity",e)),e); d["min_equity"]=min(sf(d.get("min_equity",e)),e)
def ensure_daily(st,prices=None):
    today=tr_date()
    if st.get("daily",{}).get("date") != today:
        try: tg_send(report(st,prices,title="📊 Gün değişimi raporu"))
        except Exception as e: print("gün değişim rapor hata",repr(e))
        st["daily"]=new_daily(today,equity(st,prices))
def cancel_orders(st,pred,reason):
    keep=[]; canc=[]
    for o in st.get("orders",[]):
        (canc if pred(o) else keep).append(o)
    st["orders"]=keep
    if canc:
        names=sorted(set(o["inst"].replace("-USDT-SWAP","") for o in canc))
        add_event(st,f"🧹 {reason}: {', '.join(names)} | {len(canc)} emir iptal edildi",True)
    return canc
def enforce_risk(st,prices=None):
    ps=pos_symbols(st); exp=exposure_x(st,prices)
    if len(ps)>=MAX_OPEN_POSITIONS:
        cancel_orders(st, lambda o: o.get("side")=="BUY" and o.get("inst") not in ps, f"Maksimum {MAX_OPEN_POSITIONS} açık pozisyon doldu")
    if exp>=CANCEL_EXTERNAL_ORDERS_AT_X:
        cancel_orders(st, lambda o: o.get("side")=="BUY" and o.get("inst") not in ps, f"Açık notional x{exp:.2f}; pozisyonsuz emirler temizlendi")
    osy=list(order_symbols(st))
    if len(osy)>MAX_ORDER_COINS:
        posless=[s for s in osy if s not in ps]; to_cancel=set(posless[:max(0,len(osy)-MAX_ORDER_COINS)])
        cancel_orders(st, lambda o: o.get("side")=="BUY" and o.get("inst") in to_cancel, f"Açık emir coin sayısı {MAX_ORDER_COINS} üstüne çıktı")

def signal_ok(st,inst,score):
    r=st.get("recent_signals",{}).get(inst)
    if not r: return True
    age=(ts()-sf(r.get("ts")))/3600
    return age>=COOLDOWN_HOURS or score>=sf(r.get("score"))+1
def remember(st,inst,score):
    st.setdefault("recent_signals",{})[inst]={"ts":ts(),"score":score}
    for k in list(st["recent_signals"].keys()):
        if (ts()-sf(st["recent_signals"][k].get("ts")))/3600 > 48: del st["recent_signals"][k]

def analyze_candidate(inst,tick,btc):
    c15=candles(inst,"15m"); time.sleep(REQ_SLEEP); c1=candles(inst,"1h"); time.sleep(REQ_SLEEP); c4=candles(inst,"4h"); time.sleep(REQ_SLEEP); cd=candles(inst,"1d"); time.sleep(REQ_SLEEP)
    if min(len(c15),len(c1),len(c4),len(cd))<105: return None
    s15,s1,s4,sd=summ(c15),summ(c1),summ(c4),summ(cd)
    price=s15["price"]; atrp=max(min((s15["atr"]/price) if price else .004,.03),.0025)
    support=min(x["low"] for x in c1[-36:-1]); resistance=max(x["high"] for x in c1[-36:-1])
    fnd=funding(inst); time.sleep(REQ_SLEEP); oi=open_interest(inst); time.sleep(REQ_SLEEP)
    vol_now=c15[-1]["volume"]; vol_avg=sum(x["volume"] for x in c15[-25:-1])/24 if len(c15)>25 else vol_now
    score=0; reasons=[]
    if sd["price"]>sd["ema99"]: score+=.7; reasons.append("1D EMA99 üstü")
    else: score-=.5; reasons.append("1D EMA99 altı")
    if sd["price"]>sd["ema25"] and sd["ema7"]>sd["ema25"]: score+=.7; reasons.append("1D EMA7/25 pozitif")
    if sd["price"]<sd["ema99"] and sd["ema7"]<sd["ema25"]<sd["ema99"] and sd["rsi"]<38: score-=1.5; reasons.append("1D ağır düşüş filtresi")
    if sd["macd_delta"]>0: score+=.4
    if s4["price"]>s4["ema99"]: score+=1; reasons.append("4H EMA99 üstü")
    if s4["ema7"]>s4["ema25"]: score+=1.1; reasons.append("4H EMA7/25 pozitif")
    if 40<=s4["rsi"]<=64: score+=.5; reasons.append(f"4H RSI {s4['rsi']:.0f}")
    if s4["macd_delta"]>0: score+=.8; reasons.append("4H MACD toparlanıyor")
    if s4["price"]<s4["ema25"] and s4["macd_delta"]<0: score-=.8; reasons.append("4H zayıf")
    if s1["price"]>s1["ema25"] and s1["ema7"]>=s1["ema25"]: score+=1.4; reasons.append("1H EMA25 geri kazanılmış")
    if 42<=s1["rsi"]<=64: score+=.6; reasons.append(f"1H RSI {s1['rsi']:.0f}")
    if s1["macd_delta"]>0: score+=.8; reasons.append("1H MACD güçleniyor")
    if s1["price"]<s1["ema25"] and s1["macd_delta"]<0: score-=.9; reasons.append("1H negatif")
    if s15["price"]>s15["ema25"] and s15["ema7"]>s15["ema25"]: score+=1; reasons.append("15m momentum long")
    if s15["rsi"]>=45 and s15["macd_delta"]>0: score+=.7; reasons.append("15m RSI/MACD tepki")
    if wick_bad(c15): score-=.5; reasons.append("fitil riski")
    ds=(price-support)/price; dr=(resistance-price)/price
    if 0<=ds<=max(.018,atrp*2.4): score+=1; reasons.append("destek yakın")
    elif price>resistance*.995: score-=1; reasons.append("dirence çok yakın")
    if resistance>price*(1+max(.008,atrp*1.2)): score+=.7; reasons.append("TP alanı var")
    else: score-=.5; reasons.append("TP alanı dar")
    if vol_now>vol_avg*1.15 and c15[-1]["close"]>=c15[-1]["open"]: score+=.6; reasons.append("tepki hacmi")
    if fnd>.0008: score-=.5; reasons.append("funding kalabalık")
    elif fnd<-.0004: score+=.2
    if oi>0: score+=.2
    if btc.get("strong"): score+=.9; reasons.append("BTC long destekli")
    if btc.get("weak"): score-=1.2; reasons.append("BTC zayıf")
    if score<MIN_LONG_SCORE: return None
    return {"inst":inst,"symbol":inst.replace("-USDT-SWAP",""),"score":round(score,2),"price":price,"support":support,"resistance":resistance,"atr_pct":atrp,"funding":fnd,"oi":oi,"quote_vol":tick["turnover"],"change_pct":tick["change"],"tf_15m":label(s15),"tf_1h":label(s1),"tf_4h":label(s4),"tf_1d":label(sd),"rsi_15m":s15["rsi"],"rsi_1h":s1["rsi"],"rsi_4h":s4["rsi"],"rsi_1d":sd["rsi"],"reasons":reasons[:9]}

def can_open(st,inst,prices=None,score=0):
    if inst in st["positions"]: return False,False,"pozisyon var"
    if inst in pending_entry_symbols(st): return False,False,"bekleyen entry planı var"
    pos_count=len(st["positions"]); exp=exposure_x(st,prices); pot=potential_x(st,prices); eq=max(equity(st,prices),1.0)
    day_net=equity(st,prices)-sf(st["daily"].get("start_equity",eq))
    soft=-eq*0.03; hard=-eq*0.05
    if day_net<=hard: return False,False,f"günlük hard zarar {fu(day_net)}"
    if day_net<=soft and score<EXCEPTION_LONG_SCORE: return False,False,f"günlük soft zarar {fu(day_net)}"
    if len(pending_entry_symbols(st))>=MAX_ORDER_COINS: return False,False,"max bekleyen entry coin dolu"
    if exp>=NORMAL_MAX_EXPOSURE_X: return False,False,f"aktif exposure x{exp:.2f}; yeni coin yok"
    if pos_count<MAX_OPEN_POSITIONS:
        if exp>=CANCEL_EXTERNAL_ORDERS_AT_X and score<8.6: return False,False,f"x{exp:.2f} dikkat; skor yetersiz"
        if pot + plan_notional(st,prices)/eq > EMERGENCY_DCA_MAX_X: return False,False,f"potansiyel x{pot:.2f}"
        return True,False,"normal long plan"
    if pos_count==MAX_OPEN_POSITIONS and score>=EXCEPTION_LONG_SCORE and exp<NORMAL_MAX_EXPOSURE_X:
        if pot + plan_notional(st,prices,exception=True)/eq <= EMERGENCY_DCA_MAX_X:
            return True,True,"6. istisna fırsat planı"
    return False,False,"pozisyon sınırı / istisna şartı yok"
def plan_levels(sig, st=None, prices=None, exception=False, reprice_mode=False):
    p=sig["price"]; atrp=sig["atr_pct"]
    # Kontrollü artan DCA: %15 / %17.5 / %20 / %22.5 / %25
    w=[.15,.175,.20,.225,.25]
    if reprice_mode:
        gaps=[.0015,max(.004,.45*atrp),max(.008,.9*atrp),max(.014,1.5*atrp),max(.022,2.2*atrp)]
    else:
        gaps=[.003,max(.006,.7*atrp),max(.011,1.2*atrp),max(.018,2*atrp),max(.028,3*atrp)]
    levels=[p*(1-g) for g in gaps]
    for i in range(1,len(levels)):
        if levels[i]>=levels[i-1]: levels[i]=levels[i-1]*(1-max(.003,atrp*.4))
    total = plan_notional(st, prices or current_prices(st) if st else None, exception) if st else PLAN_NOTIONAL
    return levels, [total*x for x in w]
def tp_price(pos, resistance=None, mode="normal"):
    avg=sf(pos["avg_entry"]); atrp=sf(pos.get("atr_pct",.006),.006); dca=int(pos.get("dca_count",0))
    if mode=="rescue": tp=max(.0045,min(.010,atrp*.95))
    elif dca>=2: tp=max(.007,min(.018,atrp*1.2))
    else: tp=max(.008,min(.022,atrp*1.35))
    natural=avg*(1+tp)
    if resistance and resistance>avg and resistance<natural*1.02: return max(avg*1.0035,resistance*.996)
    return natural
def set_tp(st,inst,price,reason):
    pos=st["positions"].get(inst)
    if not pos: return
    st["orders"]=[o for o in st["orders"] if not (o.get("inst")==inst and o.get("role")=="TP")]
    st["orders"].append({"id":nid("tp"),"inst":inst,"side":"SELL","role":"TP","price":price,"qty":sf(pos["qty"]),"created_ts":ts(),"reduce_only":True,"reason":reason})
    pos["tp_price"]=price
    add_event(st,f"🎯 {inst.replace('-USDT-SWAP','')} TP güncellendi: {fp(price)} | {reason}",True)
def open_position(st,sig,exception=False):
    entries,amounts=plan_levels(sig,st,current_prices(st),exception=exception); inst=sig["inst"]; plan_id=nid("plan")
    for lvl,(price,amount) in enumerate(zip(entries,amounts),start=1):
        st["orders"].append({"id":nid("buy"),"plan_id":plan_id,"inst":inst,"side":"BUY","role":"ENTRY","level":lvl,"price":price,"usdt":amount,"score":sig["score"],"created_ts":ts(),"last_review_ts":ts(),"last_reprice_ts":0,"up_reprice_count_today":0,"reason":"limit entry plan","signal_snapshot":sig})
    plan_text = "\n".join([f"{i}) {fp(px)} — {fu(am)} USDT" for i,(px,am) in enumerate(zip(entries,amounts),1)])
    add_event(st, "🟢 SANAL LONG limit planı oluşturuldu: {} | skor {}/10\n{}".format(sig["symbol"], sig["score"], plan_text), True)
    remember(st,inst,sig["score"])

def start_position_from_entry(st,o,fill):
    inst=o["inst"]; sig=o.get("signal_snapshot",{}); usdt=sf(o["usdt"]); qty=usdt/fill; fee=usdt*TAKER_FEE_RATE
    st["balance"]=sf(st["balance"])-fee; st["daily"]["fees"]+=fee
    st["positions"][inst]={"inst":inst,"symbol":inst.replace("-USDT-SWAP",""),"side":"LONG","qty":qty,"avg_entry":fill,"filled_notional":usdt,"initial_ts":ts(),"last_price":fill,"dca_count":0,"rescue_count":0,"partial_reduced":False,"protective_stop":None,"atr_pct":sf(sig.get("atr_pct"),.006),"score":sf(o.get("score")),"reasons":sig.get("reasons",[]),"realized_on_position":-fee,"rescue_records":[]}
    st["daily"]["opened"]+=1
    add_event(st,f"✅ {inst.replace('-USDT-SWAP','')} 1. kademe sanal alış doldu | {fp(fill)} / {fu(usdt)} USDT | fee {fu(fee)}",True)
    # Aynı plandaki kalan entry emirleri artık DCA sayılır.
    for oo in st["orders"]:
        if oo.get("inst")==inst and oo.get("plan_id")==o.get("plan_id") and oo.get("id")!=o.get("id") and oo.get("role") in ("ENTRY","ENTRY_REPRICE"):
            oo["role"]="DCA"; oo["reason"]="pozisyon açıldıktan sonra DCA"
    set_tp(st,inst,tp_price(st["positions"][inst],sig.get("resistance")),"ilk alış sonrası TP")

def add_dca(st,inst,o,fill):
    pos=st["positions"].get(inst)
    if not pos: return
    usdt=sf(o["usdt"]); qadd=usdt/fill; oq=sf(pos["qty"]); avg=sf(pos["avg_entry"]); nq=oq+qadd; navg=(oq*avg+qadd*fill)/max(nq,1e-12); fee=usdt*TAKER_FEE_RATE
    st["balance"]=sf(st["balance"])-fee; st["daily"]["fees"]+=fee; st["daily"]["dca_fills"]+=1
    pos["qty"]=nq; pos["avg_entry"]=navg; pos["filled_notional"]=sf(pos.get("filled_notional"))+usdt; pos["realized_on_position"]=sf(pos.get("realized_on_position"))-fee
    if o.get("role") in ("RESCUE_DCA","RESCUE"):
        pos["rescue_count"]=int(pos.get("rescue_count",0))+1
        if "rescue_records" not in pos: pos["rescue_records"]=[]
        rec=o.get("rescue_record")
        if rec: pos["rescue_records"].append(rec)
        label="🛟 RESCUE"
    else:
        pos["dca_count"]=int(pos.get("dca_count",0))+1
        label="🟡 DCA"
    add_event(st,f"{label} doldu: {inst.replace('-USDT-SWAP','')} seviye {o.get('level')} | {fp(fill)} / {fu(usdt)} USDT | yeni ort. {fp(navg)}",True)
    set_tp(st,inst,tp_price(pos,mode="rescue" if int(pos.get("dca_count",0))>=2 else "normal"),"DCA sonrası ortak TP")
def close_qty(st,inst,qty_close,price,reason,ctype="MANUAL"):
    pos=st["positions"].get(inst)
    if not pos: return 0
    qty=sf(pos["qty"]); qty_close=min(qty_close,qty)
    if qty_close<=0: return 0
    avg=sf(pos["avg_entry"]); exitp=price*(1-SLIPPAGE_RATE); gross=qty_close*(exitp-avg); fee=qty_close*exitp*TAKER_FEE_RATE; net=gross-fee
    st["balance"]=sf(st["balance"])+net; st["daily"]["realized_pnl"]+=net; st["daily"]["fees"]+=fee; pos["realized_on_position"]=sf(pos.get("realized_on_position"))+net
    rem=qty-qty_close; symbol=inst.replace("-USDT-SWAP",""); pnlpct=(exitp-avg)/avg*100 if avg else 0
    if rem<=qty*.001:
        total=sf(pos.get("realized_on_position")); st["daily"]["closed"]+=1
        if ctype=="TP": st["daily"]["tp_closed"]+=1
        if ctype in ("STOP","RISK_CLOSE"): st["daily"]["stop_closed"]+=1
        if total>=0: st["daily"]["wins"]+=1
        else: st["daily"]["losses"]+=1
        st["daily"]["closed_trades"].append({"symbol":symbol,"type":ctype,"entry":avg,"exit":exitp,"net_pnl":total,"pnl_pct":pnlpct,"dca_count":int(pos.get("dca_count",0)),"rescue_count":int(pos.get("rescue_count",0)),"reason":reason,"time":tr_time()})
        for rec in pos.get("rescue_records",[]):
            shadow=sf(rec.get("shadow_stop_pnl")); diff=total-shadow
            msg=f"{symbol} rescue {'başarılı' if diff>0 else 'başarısız'} | stop alternatifi {fu(shadow)} USDT | gerçek sonuç {fu(total)} USDT | fark {fu(diff)} USDT"
            st["daily"].setdefault("rescue_summary",[]).append(msg)
            add_event(st,"📌 "+msg,False)
        st["orders"]=[o for o in st["orders"] if o.get("inst")!=inst]; del st["positions"][inst]
        add_event(st,f"✅ {symbol} pozisyon kapandı | {ctype} | çıkış {fp(exitp)} | net PnL {fu(total)} USDT ({pct(pnlpct)}) | {reason}",True)
    else:
        pos["qty"]=rem; st["daily"]["partial_reduces"]+=1
        for o in st["orders"]:
            if o.get("inst")==inst and o.get("role")=="TP": o["qty"]=rem
        add_event(st,f"🟠 {symbol} pozisyon azaltıldı | net {fu(net)} USDT | kalan qty {rem:.6f} | {reason}",True)
    return net
def fill_orders(st):
    if not st["orders"]: return
    by={}
    for o in st["orders"]: by.setdefault(o["inst"],[]).append(o)
    rem=[]
    for inst,orders in by.items():
        rng=latest5(inst); time.sleep(REQ_SLEEP)
        if not rng: rem.extend(orders); continue
        low,high,close=rng["low"],rng["high"],rng["close"]
        if inst in st["positions"]: st["positions"][inst]["last_price"]=close
        for o in orders:
            price=sf(o["price"])
            if o.get("side")=="BUY":
                if low<=price:
                    exp_after=(total_notional(st,{inst:close})+sf(o.get("usdt")))/max(equity(st,{inst:close}),1.0)
                    if inst not in st["positions"] and o.get("role") in ("ENTRY","ENTRY_REPRICE"):
                        start_position_from_entry(st,o,price*(1+SLIPPAGE_RATE))
                    elif inst in st["positions"] and exp_after<=EMERGENCY_DCA_MAX_X:
                        add_dca(st,inst,o,price*(1+SLIPPAGE_RATE))
                    else:
                        add_event(st,f"⛔ {inst.replace('-USDT-SWAP','')} alış dolum reddi | exp_after x{exp_after:.2f}",True)
                else: rem.append(o)
            elif o.get("side")=="SELL" and o.get("role")=="TP":
                if high>=price and inst in st["positions"]: close_qty(st,inst,sf(st["positions"][inst]["qty"]),price,"TP seviyesi görüldü","TP")
                else: rem.append(o)
            else: rem.append(o)
    st["orders"]=rem

def market_summary(inst):
    c15=candles(inst,"15m"); time.sleep(REQ_SLEEP); c1=candles(inst,"1h"); time.sleep(REQ_SLEEP); c4=candles(inst,"4h"); time.sleep(REQ_SLEEP)
    s15,s1,s4=summ(c15),summ(c1),summ(c4)
    support=min(x["low"] for x in c1[-36:-1]); resistance=max(x["high"] for x in c1[-36:-1])
    vol_now=c15[-1]["volume"]; vol_avg=sum(x["volume"] for x in c15[-25:-1])/24 if len(c15)>25 else vol_now
    return {"price":s15["price"],"support":support,"resistance":resistance,"s15":s15,"s1":s1,"s4":s4,"tf_15m":label(s15),"tf_1h":label(s1),"tf_4h":label(s4),"sell_volume":vol_now>vol_avg*1.2 and c15[-1]["close"]<c15[-1]["open"],"wick_bad":wick_bad(c15),"atr_pct":max(min((s15["atr"]/s15["price"]) if s15["price"] else .004,.03),.0025)}
def assess(pos,ms,btc,st):
    price=sf(ms["price"]); avg=sf(pos["avg_entry"]); pnlpct=(price-avg)/avg*100 if avg else 0; dca=int(pos.get("dca_count",0)); risk=0; reasons=[]
    if price<ms["support"]: risk+=2; reasons.append("1H destek altı")
    if ms["s15"]["price"]<ms["s15"]["ema25"] and ms["s15"]["macd_delta"]<0: risk+=1; reasons.append("15m zayıf")
    if ms["s1"]["price"]<ms["s1"]["ema25"]: risk+=2; reasons.append("1H EMA25 altı")
    if ms["s1"]["ema7"]<ms["s1"]["ema25"] and ms["s1"]["macd_delta"]<0: risk+=1.3; reasons.append("1H trend aşağı")
    if ms["s4"]["price"]<ms["s4"]["ema25"]: risk+=1.8; reasons.append("4H EMA25 altı")
    if ms["sell_volume"]: risk+=1.2; reasons.append("hacimli satış")
    if ms["wick_bad"]: risk+=.5; reasons.append("fitil")
    if btc.get("weak"): risk+=1.8; reasons.append("BTC zayıf")
    if pnlpct<=-1.5: risk+=.8; reasons.append("zarar büyüyor")
    if pnlpct<=-3: risk+=1.2; reasons.append("zarar kritik")
    if dca>=2 and pnlpct<-.8: risk+=1; reasons.append("2+ DCA sonrası toparlamadı")
    if exposure_x(st)>=NORMAL_MAX_EXPOSURE_X: risk+=1.2; reasons.append("notional x3 sınırı")
    if pnlpct>.5: risk-=1
    if pnlpct>1.2: risk-=1
    return max(risk,0),pnlpct,reasons
def manage_positions(st,tm=None):
    if not st["positions"]: return
    btc=btc_filter(); prices=current_prices(st,tm); update_daily_eq(st,prices)
    for inst in list(st["positions"].keys()):
        pos=st["positions"].get(inst)
        if not pos: continue
        try:
            ms=market_summary(inst); pos["last_price"]=ms["price"]; pos["atr_pct"]=ms["atr_pct"]
            risk,pnlpct,reasons=assess(pos,ms,btc,st); sym=inst.replace("-USDT-SWAP","")
            if pnlpct>=1.2:
                protect=sf(pos["avg_entry"])*1.0015
                if protect>sf(pos.get("protective_stop") or 0):
                    pos["protective_stop"]=protect; add_event(st,f"🔒 {sym} kâr koruma stopu hazırlandı: {fp(protect)} | PnL {pct(pnlpct)}",True)
            desired=tp_price(pos,ms["resistance"],"rescue" if int(pos.get("dca_count",0))>=2 or risk>=5 else "normal")
            old=sf(pos.get("tp_price") or 0)
            if old<=0 or abs(desired-old)/max(old,1e-9)>.004:
                if pnlpct>.2 or risk>=5 or int(pos.get("dca_count",0))>=1: set_tp(st,inst,desired,f"dinamik TP | risk {risk:.1f}")
            prot=sf(pos.get("protective_stop") or 0)
            if prot>0 and ms["price"]<prot and pnlpct>0:
                close_qty(st,inst,sf(pos["qty"]),ms["price"],f"kâr koruma stopu tetiklendi ({fp(prot)})","PROTECT"); continue
            if risk>=10:
                cancel_orders(st,lambda o,x=inst:o.get("inst")==x and o.get("side")=="BUY",f"{sym} çok yüksek risk; DCA iptal")
                close_qty(st,inst,sf(pos["qty"]),ms["price"],f"çok yüksek risk: {', '.join(reasons[:4])}","RISK_CLOSE"); continue
            if risk>=8:
                cancel_orders(st,lambda o,x=inst:o.get("inst")==x and o.get("side")=="BUY",f"{sym} yüksek risk; DCA iptal")
                if not pos.get("partial_reduced"):
                    close_qty(st,inst,sf(pos["qty"])*.5,ms["price"],f"yüksek riskte %50 azalt: {', '.join(reasons[:4])}","RISK_REDUCE")
                    if inst in st["positions"]:
                        st["positions"][inst]["partial_reduced"]=True; set_tp(st,inst,tp_price(st["positions"][inst],ms["resistance"],"rescue"),"risk sonrası rescue TP")
                else:
                    close_qty(st,inst,sf(pos["qty"]),ms["price"],f"risk devam ediyor: {', '.join(reasons[:4])}","RISK_CLOSE")
                continue
            if risk>=6:
                cancel_orders(st,lambda o,x=inst:o.get("inst")==x and o.get("side")=="BUY",f"{sym} risk arttı; DCA kapatıldı")
                stop=min(ms["support"]*.992, ms["price"]*.985)
                if sf(pos.get("protective_stop") or 0)==0 or stop>sf(pos.get("protective_stop")):
                    pos["protective_stop"]=stop; add_event(st,f"⚠️ {sym} risk {risk:.1f}; stop hazır: {fp(stop)} | {', '.join(reasons[:4])}",True)
                continue
            # kontrollü rescue DCA: zararda ama grafik tamamen bozulmamışsa
            if risk<5 and pnlpct<-.7:
                has_dca=any(o for o in st["orders"] if o.get("inst")==inst and o.get("side")=="BUY")
                if not has_dca and exposure_x(st,prices)<RESCUE_MAX_EXPOSURE_X and int(pos.get("dca_count",0))+int(pos.get("rescue_count",0))<4:
                    amount=min(plan_notional(st,prices)*.18,equity(st,prices)*.10); price=ms["price"]*(1-max(.004,ms["atr_pct"]*.7))
                    qty=sf(pos.get("qty")); avg=sf(pos.get("avg_entry")); mark=sf(ms["price"]); shadow=qty*((mark*(1-SLIPPAGE_RATE))-avg)-(qty*mark*TAKER_FEE_RATE)
                    rec={"time":tr_time(),"symbol":sym,"shadow_stop_pnl":shadow,"pnl_before":qty*(mark-avg),"reason":"kontrollü rescue DCA"}
                    st["orders"].append({"id":nid("buy"),"inst":inst,"side":"BUY","role":"RESCUE_DCA","level":int(pos.get("dca_count",0))+int(pos.get("rescue_count",0))+2,"price":price,"usdt":amount,"created_ts":ts(),"reason":"kontrollü rescue DCA","rescue_record":rec})
                    add_event(st,f"🛟 {sym} rescue DCA emri: {fp(price)} / {fu(amount)} USDT | risk {risk:.1f} | o anda stop olsaydı {fu(shadow)} USDT",True)
        except Exception as e:
            add_event(st,f"⚠️ {inst} pozisyon yönetim hatası: {repr(e)}",True)


def reprice_entry_plan(st,inst,sig,direction,reason):
    orders=sorted([o for o in st.get("orders",[]) if o.get("inst")==inst and o.get("role") in ("ENTRY","ENTRY_REPRICE")], key=lambda x:x.get("level",0))
    if not orders: return
    amounts=[sf(o.get("usdt")) for o in orders]
    old_first=sf(orders[0].get("price")); up_count=max(int(o.get("up_reprice_count_today",0)) for o in orders)
    if direction=="up": up_count+=1
    entries,_=plan_levels(sig,st,current_prices(st),reprice_mode=(direction=="up"))
    st["orders"]=[o for o in st["orders"] if not (o.get("inst")==inst and o.get("role") in ("ENTRY","ENTRY_REPRICE"))]
    plan_id=nid("rplan")
    for lvl,(price,amount) in enumerate(zip(entries,amounts),start=1):
        st["orders"].append({"id":nid("buy"),"plan_id":plan_id,"inst":inst,"side":"BUY","role":"ENTRY_REPRICE","level":lvl,"price":price,"usdt":amount,"score":sig["score"],"created_ts":orders[0].get("created_ts",ts()),"last_review_ts":ts(),"last_reprice_ts":ts(),"up_reprice_count_today":up_count,"reason":reason,"signal_snapshot":sig})
    add_event(st,f"🔁 {inst.replace('-USDT-SWAP','')} bekleyen limit planı güncellendi ({'yukarı kontrollü' if direction=='up' else 'güncel/aşağı'}): {reason}\n"+"\n".join([f"{i}) {fp(p)} — {fu(a)} USDT" for i,(p,a) in enumerate(zip(entries,amounts),1)]),True)

def review_pending_orders(st,tm,active,btc):
    for inst in list(pending_entry_symbols(st)):
        if inst in st.get("positions",{}): continue
        try:
            tick=tm.get(inst)
            sig=analyze_candidate(inst,tick,btc) if tick else None
            orders=[o for o in st["orders"] if o.get("inst")==inst and o.get("role") in ("ENTRY","ENTRY_REPRICE")]
            if not orders: continue
            oldest=min(sf(o.get("created_ts")) for o in orders); age=(ts()-oldest)/3600
            oldscore=max(sf(o.get("score")) for o in orders)
            if not sig:
                cancel_orders(st,lambda o,x=inst:o.get("inst")==x and o.get("role") in ("ENTRY","ENTRY_REPRICE"),f"bekleyen plan iptal: güncel sinyal kayboldu / skor eşik altı ({oldscore:.1f})"); continue
            if age>=PENDING_REVIEW_HOURS:
                add_event(st,f"🔎 {inst.replace('-USDT-SWAP','')} bekleyen emir {age:.1f} saattir dolmadı; otomatik silinmedi, güncel skor {sig['score']}/10",False)
            if sig["score"] < MIN_LONG_SCORE-.4:
                cancel_orders(st,lambda o,x=inst:o.get("inst")==x and o.get("role") in ("ENTRY","ENTRY_REPRICE"),f"güncel skor düştü {oldscore:.1f} → {sig['score']:.1f}"); continue
            last=max(sf(o.get("last_reprice_ts")) for o in orders); since=(ts()-last)/60 if last else 999
            up_count=max(int(o.get("up_reprice_count_today",0)) for o in orders)
            old_first=sf(sorted(orders,key=lambda x:x.get("level",0))[0]["price"])
            new_up=plan_levels(sig,st,current_prices(st),reprice_mode=True)[0][0]
            if sig["score"]>=REPRICE_STRONG_SCORE and not btc.get("weak") and since>=REPRICE_COOLDOWN_MINUTES and up_count<MAX_UP_REPRICE_PER_DAY and old_first*1.004<new_up<old_first*1.025:
                reprice_entry_plan(st,inst,sig,"up","long yapısı devam ediyor; kontrollü yukarı reprice")
            else:
                for o in orders:
                    o["score"]=sig["score"]; o["last_review_ts"]=ts(); o["signal_snapshot"]=sig
        except Exception as e:
            add_event(st,f"⚠️ {inst} pending review hata: {repr(e)}",False)

def scan_open(st,tm,active):
    prices=current_prices(st,tm); enforce_risk(st,prices)
    day_net=equity(st,prices)-sf(st["daily"].get("start_equity",START_BALANCE))
    if day_net<=HARD_DAILY_NET_LOSS_LIMIT:
        add_event(st,f"🛑 Günlük hard zarar limiti: {fu(day_net)} USDT. Yeni pozisyon arama durdu.",True); return
    syms,skipped=universe(active,tm); btc=btc_filter(); review_pending_orders(st,tm,active,btc); cands=[]
    for inst in syms:
        try:
            if inst in st["positions"] or inst in order_symbols(st): continue
            sig=analyze_candidate(inst,tm.get(inst,{}),btc)
            if sig and signal_ok(st,inst,sig["score"]):
                cands.append(sig); print(inst,"aday",sig["score"])
        except Exception as e: print(inst,"analiz hata",repr(e))
        time.sleep(REQ_SLEEP)
    cands.sort(key=lambda x:x["score"], reverse=True); opened=0
    for sig in cands:
        if opened>=MAX_NEW_POSITIONS_PER_SCAN: break
        ok,exception,why=can_open(st,sig["inst"],current_prices(st,tm),sig["score"])
        if ok:
            open_position(st,sig,exception=exception); opened+=1; enforce_risk(st,current_prices(st,tm))
        else:
            # Eğer bekleyen 10 entry doluysa yeni aday en zayıf plandan belirgin iyiyse değiştir.
            if len(pending_entry_symbols(st))>=MAX_ORDER_COINS and sig["inst"] not in pending_entry_symbols(st):
                scores={}
                for o in st["orders"]:
                    if o.get("role") in ("ENTRY","ENTRY_REPRICE"):
                        scores[o["inst"]]=min(scores.get(o["inst"],99),sf(o.get("score")))
                if scores:
                    weak=min(scores,key=scores.get)
                    if sig["score"]>=scores[weak]+REPLACE_SCORE_DELTA:
                        cancel_orders(st,lambda o,x=weak:o.get("inst")==x and o.get("role") in ("ENTRY","ENTRY_REPRICE"),f"daha güçlü aday {sig['symbol']} {sig['score']}/10 > {weak.replace('-USDT-SWAP','')} {scores[weak]:.1f}/10")
                        open_position(st,sig); opened+=1; enforce_risk(st,current_prices(st,tm)); continue
            print(sig["inst"],"açılmadı",why)
    if opened: add_event(st,f"📡 Market taraması: {opened} yeni sanal LONG açıldı | aday {len(cands)}",True)
    else: print(tr_time(),"Tarama: yeni pozisyon yok | aday",len(cands))
    st["last_scan_ts"]=ts()

def report(st,prices=None,title="📊 Gün sonu CopyGuard Paper Raporu"):
    prices=prices or {}; e=equity(st,prices); u=unrealized(st,prices); bal=sf(st.get("balance",START_BALANCE)); d=st["daily"]; start=sf(d.get("start_equity",START_BALANCE))
    day_net=e-start; total_net=e-sf(st.get("start_balance",START_BALANCE)); closed=int(d.get("closed",0)); wins=int(d.get("wins",0)); losses=int(d.get("losses",0)); wr=(wins/closed*100) if closed else 0
    maxdd=sf(d.get("max_equity",e))-sf(d.get("min_equity",e))
    lines=[title,f"<b>{VERSION}</b>",f"Tarih: {d.get('date')} | Saat: {tr_time()}","",
           f"Başlangıç sanal bakiye: {fu(st.get('start_balance',START_BALANCE))} USDT",
           f"Gün başlangıç equity: {fu(start)} USDT",f"Güncel balance: {fu(bal)} USDT",f"Açık PnL: {fu(u)} USDT",f"Güncel equity: <b>{fu(e)} USDT</b>",
           f"Günlük net: <b>{fu(day_net)} USDT</b>",f"Toplam net: <b>{fu(total_net)} USDT</b>",f"Günlük fee: {fu(d.get('fees',0))} USDT",f"Gün içi max-min equity farkı: {fu(maxdd)} USDT","",
           f"Dinamik coin başı plan: {fu(plan_notional(st,prices))} USDT",f"Kademe: {' / '.join(fu(plan_notional(st,prices)*w) for w in [.15,.175,.20,.225,.25])}",f"Açık pozisyon: {len(st.get('positions',{}))}/{MAX_OPEN_POSITIONS} normal (+istisna)",f"Pozisyonsuz entry emir coin: {len(pending_entry_symbols(st))}/{MAX_ORDER_COINS}",f"Açık emir coin sayısı: {len(order_symbols(st))}/{MAX_ORDER_COINS}",f"Açık notional: x{exposure_x(st,prices):.2f}",f"Potansiyel notional: x{potential_x(st,prices):.2f}","",
           f"Bugün açılan pozisyon: {d.get('opened',0)}",f"Bugün kapanan pozisyon: {closed}",f"TP ile kapanan: {d.get('tp_closed',0)}",f"Risk/stop kapanan: {d.get('stop_closed',0)}",f"DCA dolumu: {d.get('dca_fills',0)}",f"Kısmi azaltma: {d.get('partial_reduces',0)}",f"Win rate: {wr:.1f}% ({wins}W / {losses}L)"]
    if st.get("positions"):
        lines += ["","<b>Açık pozisyonlar</b>"]
        for inst,p in st["positions"].items():
            pr=prices.get(inst,sf(p.get("last_price",p.get("avg_entry")))); avg=sf(p.get("avg_entry")); qty=sf(p.get("qty")); pnl=qty*(pr-avg); pnlpct=(pr-avg)/avg*100 if avg else 0
            dcas=[o for o in st["orders"] if o.get("inst")==inst and o.get("side")=="BUY"]; tp=next((o for o in st["orders"] if o.get("inst")==inst and o.get("role")=="TP"),None)
            lines.append(f"- {inst.replace('-USDT-SWAP','')}: ort {fp(avg)} | fiyat {fp(pr)} | PnL {fu(pnl)} ({pct(pnlpct)}) | notional {fu(qty*pr)} | DCA {p.get('dca_count',0)} | TP {fp(tp['price']) if tp else 'yok'} | bekleyen DCA {len(dcas)}")
    if d.get("closed_trades"):
        lines += ["","<b>Bugün kapanan işlemler</b>"]
        for tr in d["closed_trades"][-20:]:
            lines.append(f"- {tr['symbol']} {tr['type']}: {fp(tr['entry'])}→{fp(tr['exit'])} | net {fu(tr['net_pnl'])} USDT ({pct(tr['pnl_pct'])}) | DCA {tr.get('dca_count',0)} | {tr.get('reason','')}")
    if pending_entry_symbols(st):
        lines += ["","<b>Pozisyonsuz bekleyen limit planları</b>"]
        for inst in sorted(pending_entry_symbols(st)):
            os=[o for o in st["orders"] if o.get("inst")==inst and o.get("role") in ("ENTRY","ENTRY_REPRICE")]
            os=sorted(os,key=lambda x:x.get("level",0)); score=max([sf(o.get("score")) for o in os] or [0])
            lines.append(f"- {inst.replace('-USDT-SWAP','')} skor {score:.1f}: "+" | ".join([f"{o.get('level')}) {fp(o.get('price'))}/{fu(o.get('usdt'))}" for o in os]))
    if d.get("rescue_summary"):
        lines += ["","<b>Rescue / shadow stop analizi</b>"]
        for x in d.get("rescue_summary",[])[-20:]: lines.append("- "+x)
    if d.get("events"):
        lines += ["","<b>Gün içi olay özeti</b>"]
        for ev in d["events"][-35:]: lines.append("- "+ev)
    lines += ["","Not: Sanal/paper trade testidir. Gerçek emir açılmaz."]
    return "\n".join(lines)
def maybe_report(st,prices=None):
    dt=trdt(); d=st["daily"]
    if d.get("report_sent"): return
    if dt.hour>DAILY_REPORT_HOUR_TR or (dt.hour==DAILY_REPORT_HOUR_TR and dt.minute>=DAILY_REPORT_MINUTE_TR):
        tg_send(report(st,prices)); d["report_sent"]=True


def tg_updates(st):
    if not TELEGRAM_BOT_TOKEN: return []
    offset=int(st.get("telegram_last_update_id",0))+1
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?"+urllib.parse.urlencode({"offset":offset,"timeout":"1"})
    try:
        data=http_json(url,timeout=10)
        return data.get("result",[]) if data.get("ok") else []
    except Exception as e:
        print("getUpdates hata",repr(e)); return []

def process_commands(st):
    for u in tg_updates(st):
        st["telegram_last_update_id"]=max(int(st.get("telegram_last_update_id",0)), int(u.get("update_id",0)))
        msg=u.get("message") or {}; text=(msg.get("text") or "").strip(); parts=text.split()
        if not parts: continue
        cmd=parts[0].lower()
        if cmd in ("/status","/durum"):
            tg_send(f"📌 {VERSION}\nEquity: {fu(equity(st,current_prices(st)))} USDT\nPozisyon: {len(pos_symbols(st))}\nBekleyen entry coin: {len(pending_entry_symbols(st))}\nExposure: x{exposure_x(st,current_prices(st)):.2f}")
        elif cmd in ("/approve","/onay","/reject","/red") and len(parts)>=2:
            pid=parts[1]; prop=st.get("pending_proposals",{}).get(pid)
            if not prop: tg_send(f"Öneri bulunamadı: {pid}"); continue
            if cmd in ("/reject","/red"):
                prop["status"]="rejected"; tg_send(f"❌ {pid} reddedildi. Strateji değişmedi.")
            else:
                # Şimdilik güvenlik için otomatik parametre değiştirme sınırlı; öneri onayı kayda alınır.
                prop["status"]="approved"; tg_send(f"✅ {pid} onaylandı. Değişiklik bir sonraki sürüm/ayar güncellemesinde uygulanmak üzere kaydedildi.")

def maybe_pending_reminder(st):
    for pid,p in st.get("pending_proposals",{}).items():
        if p.get("status")!="pending": continue
        last=sf(p.get("last_reminder_ts",p.get("created_ts",0))); age=(ts()-sf(p.get("created_ts",0)))/86400
        if age>3:
            p["status"]="expired"; tg_send(f"⌛ {pid} 3 gün yanıtsız kaldı, pasife alındı. Mevcut strateji değişmedi.")
        elif ts()-last>86400:
            p["last_reminder_ts"]=ts(); tg_send(f"⏳ Bekleyen strateji önerisi: {pid}\nOnay: /approve {pid}\nRed: /reject {pid}\nCevap gelene kadar strateji değişmez.")

def run():
    print(tr_time(),VERSION,"başladı")
    st=load_state()
    try:
        process_commands(st); maybe_pending_reminder(st)
        tm=ticker_map(); time.sleep(REQ_SLEEP); active=active_instruments(); time.sleep(REQ_SLEEP)
        prices=current_prices(st,tm); ensure_daily(st,prices)
        fill_orders(st); time.sleep(REQ_SLEEP)
        tm=ticker_map(); prices=current_prices(st,tm); manage_positions(st,tm); time.sleep(REQ_SLEEP)
        tm=ticker_map(); prices=current_prices(st,tm); enforce_risk(st,prices); update_daily_eq(st,prices)
        due=(ts()-sf(st.get("last_scan_ts",0))) >= SCAN_INTERVAL_MINUTES*60
        manual=os.getenv("GITHUB_EVENT_NAME","")=="workflow_dispatch"
        if due or manual: scan_open(st,tm,active)
        else: print("Market scan zamanı değil. Son scan yaş:", (ts()-sf(st.get("last_scan_ts",0)))/60)
        tm=ticker_map(); prices=current_prices(st,tm); update_daily_eq(st,prices); maybe_report(st,prices); save_state(st)
        print(tr_time(),"bitti","equity",fu(equity(st,prices)),"pos",len(st["positions"]),"orders",len(st["orders"]),"exp",f"x{exposure_x(st,prices):.2f}")
        if manual:
            tg_send(f"✅ <b>{VERSION}</b>\nManuel test çalıştı.\nEquity: {fu(equity(st,prices))} USDT\nBalance: {fu(st.get('balance',START_BALANCE))} USDT\nAçık pozisyon: {len(st.get('positions',{}))}/{MAX_OPEN_POSITIONS}\nAçık emir coin: {len(order_symbols(st))}/{MAX_ORDER_COINS}\nExposure: x{exposure_x(st,prices):.2f}\nPotansiyel: x{potential_x(st,prices):.2f}\nYeni fırsat taraması: {'yapıldı' if due or manual else 'beklemede'}")
    except Exception as e:
        err=f"⚠️ {VERSION} hata:\n{repr(e)}"; print(err)
        try: tg_send(err)
        except Exception: pass
        save_state(st); raise

if __name__ == "__main__":
    run()
