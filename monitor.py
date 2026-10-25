import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 记得换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"
CYCLE_FILE = "cycle_time.json"
MAX_OPEN_TRADES = 15  # 最多开 15 单
CYCLE_HOURS = 3       # 3 小时强制轮转

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
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    requests.post(url, json=payload)

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1: return 50.0
    gains, losses = 0, 0
    for i in range(1, period + 1):
        change = candles[-i]["close"] - candles[-i-1]["close"]
        if change > 0: gains += change
        else: losses -= change
    if losses == 0: return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))

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
            
        curr_price = get_current_price(t["symbol"])
        if not curr_price: active_trades.append(t); continue

        closed = False
        if t["direction"] == "LONG":
            risk = t["entry"] - t["sl"]
            if curr_price - t["entry"] >= risk and t["sl"] < t["entry"]:
                t["sl"] = t["entry"]
            if curr_price <= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price >= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price >= t["tp1"]: t["status"] = "WIN_TP1"; closed = True
        elif t["direction"] == "SHORT":
            risk = t["sl"] - t["entry"]
            if t["entry"] - curr_price >= risk and t["sl"] > t["entry"]:
                t["sl"] = t["entry"]
            if curr_price >= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price <= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price <= t["tp1"]: t["status"] = "WIN_TP1"; closed = True

        if closed: 
            new_trades.append(t)
        else: active_trades.append(t)
    return active_trades, new_trades

def force_cycle_settlement(active_trades):
    if not active_trades: return []
    msg = f"⏰ 【3小时周期结算强制平仓】\n清理当前持仓 {len(active_trades)} 单。\n释放资金额度，开始新一轮扫描！"
    send_tg(msg)
    return [] 

def scan_market(trades):
    if len(trades) >= MAX_OPEN_TRADES: return
        
    try:
        res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP").json()
        active_coins = [t["instId"] for t in res["data"] if t["instId"].endswith("USDT-SWAP") and float(t.get("volCcy24h", 0)) * float(t.get("last", 0)) > 5000000]
        
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
            rsi = calculate_rsi(candles, 14) 
            
            bad_pin_count = sum(1 for c in prev_candles[-20:] if (c["high"] - max(c["close"], c["open"])) > abs(c["close"] - c["open"]) * 2 or (min(c["close"], c["open"]) - c["low"]) > abs(c["close"] - c["open"]) * 2)
            if bad_pin_count > 4: continue
            
            body = abs(curr["close"] - curr["open"])
            total_length = curr["high"] - curr["low"] if (curr["high"] - curr["low"]) > 0 else 0.0001
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100

            # 做多
            is_slow_rise = (curr["close"] > curr["open"] and prev["close"] > prev["open"] and 0.2 < price_change < 2.5)
            is_hammer = (lower_shadow > body * 2 and lower_shadow > total_length * 0.5 and curr["vol"] > avg_vol * 1.2)
            is_bull_engulf = (prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"] and curr["open"] < prev["close"] and curr["vol"] > avg_vol * 1.2)
            
            if (is_slow_rise or is_hammer or is_bull_engulf) and rsi < 70:
                entry = curr["close"]
                recent_low = min([c["low"] for c in candles[-10:]])
                structural_sl = recent_low * 0.998
                
                min_sl_dist = entry * (0.006 if entry > 1000 else 0.015)
                rr1, rr2 = (1.5, 2.0) if entry > 1000 else (2.0, 3.0)
                
                sl = entry - min_sl_dist if (entry - structural_sl) < min_sl_dist else structural_sl
                risk = entry - sl
                if risk / entry > 0.04: continue 
                    
                tp1, tp2 = entry + risk * rr1, entry + risk * rr2
                
                trades.append({"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                
                msg = f"🐂 底部反转做多! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:{rr1}): {fmt_price(tp1)}\n🥈止盈2(1:{rr2}): {fmt_price(tp2)}\n(RSI: {rsi:.1f})\n⏰ {get_bj_time()}"
                send_tg(msg)
                alerts_sent += 1
                continue

            # 做空
            is_top_rejection = (upper_shadow > body * 2 and upper_shadow > total_length * 0.5)
            is_bearish_engulf = (prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"])
            
            if (is_top_rejection or is_bearish_engulf) and rsi > 30:
                if check_orderbook(symbol) < 55:
                    entry = curr["close"]
                    recent_high = max([c["high"] for c in candles[-10:]])
                    structural_sl = recent_high * 1.002
                    
                    min_sl_dist = entry * (0.006 if entry > 1000 else 0.015)
                    rr1, rr2 = (1.5, 2.0) if entry > 1000 else (2.0, 3.0)
                        
                    sl = entry + min_sl_dist if (structural_sl - entry) < min_sl_dist else structural_sl
                    risk = sl - entry
                    if risk / entry > 0.04: continue
                        
                    tp1, tp2 = entry - risk * rr1, entry - risk * rr2
                    shape = "高位流星线" if is_top_rejection else "高位阴包阳"
                    
                    trades.append({"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                    
                    msg = f"🔪 {shape}做空! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:{rr1}): {fmt_price(tp1)}\n🥈止盈2(1:{rr2}): {fmt_price(tp2)}\n(RSI: {rsi:.1f})\n⏰ {get_bj_time()}"
                    send_tg(msg)
                    alerts_sent += 1

    except Exception as e:
        print(f"❌ 扫描出错: {e}")

if __name__ == "__main__":
    print("🚀 启动 3 小时轮转量化系统...")
    all_trades = load_json(DB_FILE, [])
    cycle_data = load_json(CYCLE_FILE, {"last_reset": 0})
    
    now = datetime.now(timezone.utc)
    
    if now.timestamp() - cycle_data["last_reset"] >= CYCLE_HOURS * 3600:
        active_old = [t for t in all_trades if t["status"] == "OPEN"]
        closed_old = [t for t in all_trades if t["status"] != "OPEN"]
        force_cycle_settlement(active_old)
        
        for t in active_old:
            t["status"] = "CYCLE_TIMEOUT"
            
        all_trades = closed_old + active_old
        cycle_data["last_reset"] = now.timestamp()
        save_json(CYCLE_FILE, cycle_data)
        save_json(DB_FILE, all_trades)
        
    active_trades, new_trades = review_trades(all_trades)
    scan_market(active_trades)
    
    final_trades = new_trades + active_trades
    save_json(DB_FILE, final_trades)
