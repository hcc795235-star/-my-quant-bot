import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')

def load_trades():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f: return json.load(f)
    return []

def save_trades(trades):
    with open(DB_FILE, "w") as f: json.dump(trades, f, indent=4)

def send_tg(message):
    time_str = f"\n\n⏰ 触发时间: {get_bj_time()}"
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message + time_str})

def check_orderbook(symbol):
    try:
        res = requests.get(f"https://www.okx.com/api/v5/market/books?instId={symbol}&sz=20").json()
        bids_vol = sum([float(b[1]) for b in res["data"][0]])
        asks_vol = sum([float(a[1]) for a in res["data"][1]])
        return (bids_vol / (bids_vol + asks_vol)) * 100 if (bids_vol + asks_vol) > 0 else 50.0
    except: return 50.0

def check_ls_ratio(symbol):
    try:
        ccy = symbol.split("-")[0]
        res = requests.get(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m").json()
        if res.get("code") == "0" and res.get("data"): return float(res["data"][0][1])
        return 1.0
    except: return 1.0

def get_current_price(symbol):
    try:
        res = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={symbol}").json()
        if res.get("code") == "0": return float(res["data"][0]["last"])
    except: pass
    return None

def review_trades(trades):
    active_trades, new_trades = [], []
    for t in trades:
        if t["status"] != "OPEN":
            new_trades.append(t)
            continue
        curr_price = get_current_price(t["symbol"])
        if not curr_price:
            active_trades.append(t); continue

        closed = False
        if t["direction"] == "LONG":
            if curr_price <= t["sl"]:
                t["status"] = "LOSS"; send_tg(f"🛑 {t['symbol']} 多单止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}"); closed = True
            elif curr_price >= t["tp2"]:
                t["status"] = "WIN_TP2"; send_tg(f"🏆 {t['symbol']} 多单止盈2达成！\n入场: {t['entry']:.4f} | 出场: {t['tp2']:.4f}"); closed = True
            elif curr_price >= t["tp1"]:
                t["status"] = "WIN_TP1"; send_tg(f"✅ {t['symbol']} 多单止盈1达成！\n入场: {t['entry']:.4f} | 出场: {t['tp1']:.4f}"); closed = True
        elif t["direction"] == "SHORT":
            if curr_price >= t["sl"]:
                t["status"] = "LOSS"; send_tg(f"🛑 {t['symbol']} 空单止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}"); closed = True
            elif curr_price <= t["tp2"]:
                t["status"] = "WIN_TP2"; send_tg(f"🏆 {t['symbol']} 空单止盈2达成！\n入场: {t['entry']:.4f} | 出场: {t['tp2']:.4f}"); closed = True
            elif curr_price <= t["tp1"]:
                t["status"] = "WIN_TP1"; send_tg(f"✅ {t['symbol']} 空单止盈1达成！\n入场: {t['entry']:.4f} | 出场: {t['tp1']:.4f}"); closed = True

        if closed: new_trades.append(t)
        else: active_trades.append(t)
    return active_trades, new_trades

def scan_market(trades):
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
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades): continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            curr, prev, prev2 = candles[-1], candles[-2], candles[-3]
            prev_candles = candles[:-1]
            
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            
            # 计算均线 (EMA)
            ema7 = sum([c["close"] for c in candles[-7:]]) / 7
            ema25 = sum([c["close"] for c in candles[-25:]]) / 25
            
            body = abs(curr["close"] - curr["open"])
            total_length = curr["high"] - curr["low"] if (curr["high"] - curr["low"]) > 0 else 0.0001
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            
            signal_type = ""
            direction = ""

            # ================= 战术 A：抓“缩量慢涨” =================
            # 逻辑：连续3根阳线，都在均线之上，涨幅温和，不需要爆量
            is_slow_rise = (curr["close"] > curr["open"] and prev["close"] > prev["open"] and prev2["close"] > prev2["open"] and 
                            curr["close"] > ema7 and ema7 > ema25 and 
                            0.2 < price_change < 2.5 and curr["vol"] > avg_vol * 0.5)
            
            # ================= 战术 B：抓“高位见顶” =================
            # 逻辑：前一根大涨，当前这根留长上影线（流星线），且多头极度拥挤（多空比>2.0）
            ls_ratio = check_ls_ratio(symbol)
            is_top_rejection = (upper_shadow > body * 2 and upper_shadow > total_length * 0.5 and curr["high"] > ema7 and ls_ratio > 2.0)
            
            # ================= 战术 C：高位阴包阳 =================
            is_bearish_engulf = (prev["close"] > prev["open"] and curr["close"] < curr["open"] and 
                                 curr["close"] < prev["open"] and curr["open"] > prev["close"] and curr["high"] > ema7)

            # --- 触发做多 ---
            if is_slow_rise:
                if check_orderbook(symbol) > 45 and ls_ratio < 1.8:
                    entry = curr["close"]
                    sl = curr["low"] * 0.999
                    risk = entry - sl
                    trade = {"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": entry + risk*1.5, "tp2": entry + risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                    trades.append(trade)
                    send_tg(f"🐌 缩量慢涨做多! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}\n形态: 连续小阳逼空")
                    alerts_sent += 1

            # --- 触发做空 (长上影或阴包阳) ---
            elif is_top_rejection or is_bearish_engulf:
                if check_orderbook(symbol) < 55:
                    entry = curr["close"]
                    sl = curr["high"] * 1.001
                    risk = sl - entry
                    shape = "高位流星线" if is_top_rejection else "高位阴包阳"
                    trade = {"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": entry - risk*1.5, "tp2": entry - risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                    trades.append(trade)
                    send_tg(f"🔪 {shape}做空! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}\n多空比: {ls_ratio:.2f}")
                    alerts_sent += 1

            if alerts_sent >= 2: break
    except Exception as e:
        print(f"❌ 扫描出错: {e}")

if __name__ == "__main__":
    print("🚀 启动全能猎手系统...")
    all_trades = load_trades()
    active_trades, new_trades = review_trades(all_trades)
    scan_market(active_trades)
    save_trades(new_trades + active_trades)
