import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 记得换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"
REPORT_FILE = "last_report.json"
MAX_OPEN_TRADES = 30 # 最大同时持仓数量 30 单

def fmt_price(price):
    if price >= 1: return f"{price:.4f}"
    elif price >= 0.01: return f"{price:.5f}"
    else: return f"{price:.8f}"

def get_bj_time(dt=None):
    if dt is None: dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')

def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r") as f: return json.load(f)
    return default

def save_json(file, data):
    with open(file, "w") as f: json.dump(data, f, indent=4)

def send_tg(message):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})

def check_orderbook(symbol):
    try:
        res = requests.get(f"https://www.okx.com/api/v5/market/books?instId={symbol}&sz=20").json()
        bids = sum([float(b[1]) for b in res["data"][0]])
        asks = sum([float(a[1]) for a in res["data"][1]])
        return (bids / (bids + asks)) * 100 if (bids + asks) > 0 else 50.0
    except: return 50.0

def get_current_price(symbol):
    try:
        res = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={symbol}").json()
        if res.get("code") == "0": return float(res["data"][0]["last"])
    except: pass
    return None

def review_trades(trades):
    active_trades, new_trades = [], []
    now = datetime.now(timezone.utc)
    
    for t in trades:
        if t["status"] != "OPEN":
            new_trades.append(t); continue
            
        # 超时平仓逻辑（持仓超 8 小时强制平仓释放额度）
        open_time = datetime.fromisoformat(t["time"])
        if (now - open_time).total_seconds() > 8 * 3600:
            t["status"] = "TIMEOUT"
            t["close_time"] = now.isoformat()
            new_trades.append(t)
            continue

        curr_price = get_current_price(t["symbol"])
        if not curr_price: active_trades.append(t); continue

        closed = False
        if t["direction"] == "LONG":
            if curr_price <= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price >= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price >= t["tp1"]: t["status"] = "WIN_TP1"; closed = True
        elif t["direction"] == "SHORT":
            if curr_price >= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price <= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price <= t["tp1"]: t["status"] = "WIN_TP1"; closed = True

        if closed: 
            t["close_time"] = now.isoformat()
            new_trades.append(t)
        else: active_trades.append(t)
    return active_trades, new_trades

def scan_market(trades):
    if len(trades) >= MAX_OPEN_TRADES:
        print("⚠️ 持仓数量已达上限，暂停开新单。")
        return
        
    try:
        res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP").json()
        active_coins = []
        for t in res["data"]:
            if t["instId"].endswith("USDT-SWAP"):
                try:
                    if float(t.get("volCcy24h", 0)) * float(t.get("last", 0)) > 5000000: 
                        active_coins.append(t["instId"])
                except: pass
        
        alerts_sent = 0 
        for symbol in active_coins:
            if len(trades) + alerts_sent >= MAX_OPEN_TRADES: break
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades): continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=60").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            curr, prev, prev2 = candles[-1], candles[-2], candles[-3]
            prev_candles = candles[:-1]
            
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            ema50 = sum([c["close"] for c in candles[-50:]]) / 50  
            
            bad_pin_count = sum(1 for c in prev_candles[-20:] if (c["high"] - max(c["close"], c["open"])) > abs(c["close"] - c["open"]) * 2 or (min(c["close"], c["open"]) - c["low"]) > abs(c["close"] - c["open"]) * 2)
            if bad_pin_count > 4: continue
            if (curr["high"] - curr["low"]) / curr["low"] * 100 > 5.0: continue
            
            body = abs(curr["close"] - curr["open"])
            total_length = curr["high"] - curr["low"] if (curr["high"] - curr["low"]) > 0 else 0.0001
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100

            is_uptrend = curr["close"] > ema50
            is_downtrend = curr["close"] < ema50

            # 做多
            is_slow_rise = (curr["close"] > curr["open"] and prev["close"] > prev["open"] and prev2["close"] > prev2["open"] and 0.2 < price_change < 2.5 and curr["vol"] > avg_vol * 0.5)
            if is_slow_rise and is_uptrend:
                entry = curr["close"]
                recent_low = min([c["low"] for c in candles[-10:]])
                structural_sl = recent_low * 0.998
                
                if entry > 1000: # 大币小止损
                    min_sl_dist = entry * 0.006 
                    rr1, rr2 = 1.5, 2.0        
                else:            # 山寨币宽止损
                    min_sl_dist = entry * 0.015 
                    rr1, rr2 = 2.0, 3.0        
                
                sl = entry - min_sl_dist if (entry - structural_sl) < min_sl_dist else structural_sl
                risk = entry - sl
                
                if risk / entry > 0.04: continue 
                    
                tp1 = entry + risk * rr1
                tp2 = entry + risk * rr2
                
                trades.append({"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                send_tg(f"🐌 缩量慢涨做多! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:{rr1}): {fmt_price(tp1)}\n🥈止盈2(1:{rr2}): {fmt_price(tp2)}\n⏰ {get_bj_time()}")
                alerts_sent += 1
                continue

            # 做空
            is_top_rejection = (upper_shadow > body * 2 and upper_shadow > total_length * 0.5)
            is_bearish_engulf = (prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"])
            
            if (is_top_rejection or is_bearish_engulf) and is_downtrend:
                if check_orderbook(symbol) < 55:
                    entry = curr["close"]
                    recent_high = max([c["high"] for c in candles[-10:]])
                    structural_sl = recent_high * 1.002
                    
                    if entry > 1000: 
                        min_sl_dist = entry * 0.006 
                        rr1, rr2 = 1.5, 2.0
                    else:
                        min_sl_dist = entry * 0.015 
                        rr1, rr2 = 2.0, 3.0
                        
                    sl = entry + min_sl_dist if (structural_sl - entry) < min_sl_dist else structural_sl
                    risk = sl - entry
                    
                    if risk / entry > 0.04: continue
                        
                    tp1 = entry - risk * rr1
                    tp2 = entry - risk * rr2
                    
                    shape = "高位流星线" if is_top_rejection else "高位阴包阳"
                    trades.append({"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                    send_tg(f"🔪 {shape}做空! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:{rr1}): {fmt_price(tp1)}\n🥈止盈2(1:{rr2}): {fmt_price(tp2)}\n⏰ {get_bj_time()}")
                    alerts_sent += 1

    except Exception as e:
        print(f"❌ 扫描出错: {e}")

def send_periodic_report(trades):
    now = datetime.now(timezone.utc)
    last_report = load_json(REPORT_FILE, {"last_time": 0})
    
    if now.timestamp() - last_report["last_time"] >= 14400:
        four_hours_ago = now - timedelta(hours=4)
        recent_trades = [t for t in trades if datetime.fromisoformat(t["time"]) >= four_hours_ago]

        closed_recent = [t for t in recent_trades if t["status"] != "OPEN"]
        wins = len([t for t in closed_recent if "WIN" in t["status"]])
        losses = len([t for t in closed_recent if t["status"] == "LOSS"])
        win_rate = (wins / len(closed_recent) * 100) if len(closed_recent) > 0 else 0
        
        active_trades = [t for t in trades if t["status"] == "OPEN"]
        active_msg = f"💼 当前持仓: {len(active_trades)} / {MAX_OPEN_TRADES} 单\n"
        for t in active_trades[:10]: 
            open_min = int((now - datetime.fromisoformat(t["time"])).total_seconds() / 60)
            active_msg += f"- {t['symbol'].split('-')[0]} {t['direction']} | 已扛 {open_min} 分钟\n"
        if len(active_trades) > 10: active_msg += f"...等 {len(active_trades)} 单\n"
        if len(active_trades) == 0: active_msg += "空仓\n"

        closed_msg = f"✅ 最近平仓 ({len(closed_recent)} 单):\n"
        for t in closed_recent[-5:]: 
            closed_msg += f"- {t['symbol'].split('-')[0]} {t['direction']}: {t['status']}\n"
        if not closed_recent: closed_msg += "无\n"

        report = (
            f"📊 【4小时周期战报】\n"
            f"过去4小时开单: {len(recent_trades)} 单\n"
            f"胜率: {win_rate:.1f}% (胜{wins} 负{losses})\n"
            f"-------------------\n"
            f"{active_msg}"
            f"-------------------\n"
            f"{closed_msg}"
            f"⏰ {get_bj_time()}"
        )
        send_tg(report)
        last_report["last_time"] = now.timestamp()
        save_json(REPORT_FILE, last_report)

if __name__ == "__main__":
    print("🚀 启动高盈亏比量化系统...")
    all_trades = load_json(DB_FILE, [])
    
    active_trades, new_trades = review_trades(all_trades)
    scan_market(active_trades)
    
    final_trades = new_trades + active_trades
    save_json(DB_FILE, final_trades)
    
    send_periodic_report(final_trades)
