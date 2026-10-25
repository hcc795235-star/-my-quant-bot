import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "你的新Token"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"

# 获取北京时间
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')

def load_trades():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(DB_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def send_tg(message):
    # 统一在每条消息下面加上北京时间
    time_str = f"\n\n⏰ 信号触发时间: {get_bj_time()}"
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message + time_str})

def check_orderbook(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/books?instId={symbol}&sz=20"
        res = requests.get(url).json()
        if res.get("code") != "0": return 50.0
        bids_vol = sum([float(b[1]) for b in res["data"][0]])
        asks_vol = sum([float(a[1]) for a in res["data"][1]])
        total = bids_vol + asks_vol
        return (bids_vol / total) * 100 if total > 0 else 50.0
    except: return 50.0

def check_ls_ratio(symbol):
    try:
        ccy = symbol.split("-")[0]
        url = f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m"
        res = requests.get(url).json()
        if res.get("code") != "0" or not res.get("data"): return 1.0
        return float(res["data"][0][1])
    except: return 1.0

def get_current_price(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
        res = requests.get(url).json()
        if res.get("code") == "0":
            return float(res["data"][0]["last"])
    except: pass
    return None

def ai_diagnose_loss(symbol, direction, entry_price, exit_price):
    # ...(同上，省略以节省篇幅，原样保留即可)
    return "🧠 【AI 深度复盘】\n正常技术性破位或市场随机波动导致。"

def review_trades(trades):
    active_trades = []
    new_trades = []
    
    for t in trades:
        if t["status"] != "OPEN":
            new_trades.append(t)
            continue
            
        curr_price = get_current_price(t["symbol"])
        if not curr_price:
            active_trades.append(t)
            continue

        closed = False
        if t["direction"] == "LONG":
            if curr_price <= t["sl"]:
                t["status"] = "LOSS"
                send_tg(f"🛑 {t['symbol']} 多单触及止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}\n\n{ai_diagnose_loss(t['symbol'], 'LONG', t['entry'], curr_price)}")
                closed = True
            elif curr_price >= t["tp2"]:
                t["status"] = "WIN_TP2"
                send_tg(f"🏆 {t['symbol']} 多单止盈2达成！\n入场: {t['entry']:.4f} | 出场: {t['tp2']:.4f}")
                closed = True
            elif curr_price >= t["tp1"]:
                t["status"] = "WIN_TP1"
                send_tg(f"✅ {t['symbol']} 多单止盈1达成！\n入场: {t['entry']:.4f} | 出场: {t['tp1']:.4f}")
                closed = True
                
        elif t["direction"] == "SHORT":
            if curr_price >= t["sl"]:
                t["status"] = "LOSS"
                send_tg(f"🛑 {t['symbol']} 空单触及止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}\n\n{ai_diagnose_loss(t['symbol'], 'SHORT', t['entry'], curr_price)}")
                closed = True
            elif curr_price <= t["tp2"]:
                t["status"] = "WIN_TP2"
                send_tg(f"🏆 {t['symbol']} 空单止盈2达成！\n入场: {t['entry']:.4f} | 出场: {t['tp2']:.4f}")
                closed = True
            elif curr_price <= t["tp1"]:
                t["status"] = "WIN_TP1"
                send_tg(f"✅ {t['symbol']} 空单止盈1达成！\n入场: {t['entry']:.4f} | 出场: {t['tp1']:.4f}")
                closed = True

        if closed: new_trades.append(t)
        else: active_trades.append(t)
                
    return active_trades, new_trades

def scan_market(trades):
    try:
        res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP").json()
        if res.get("code") != "0": return
        
        active_coins = []
        for t in res["data"]:
            if t["instId"].endswith("USDT-SWAP"):
                last_price = t.get("last", "")
                vol_24h = t.get("volCcy24h", "")
                if last_price and vol_24h:
                    try:
                        vol_usdt = float(vol_24h) * float(last_price)
                        if vol_usdt > 5000000: # 500万U门槛
                            active_coins.append(t["instId"])
                    except ValueError:
                        pass
        
        alerts_sent = 0
        for symbol in active_coins:
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades): continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            
            curr = candles[-1]
            prev = candles[-2]
            prev_candles = candles[:-1]
            
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            past_20_high = max([c["high"] for c in prev_candles[-20:]])
            past_20_low = min([c["low"] for c in prev_candles[-20:]])
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            
            # ================= 1. 做多逻辑（回踩确认） =================
            prev_body = abs(prev["close"] - prev["open"])
            prev_is_bullish = prev["close"] > prev["open"]
            prev_vol = prev["vol"]
            
            # 上一根大阳线突破前高
            prev_is_breakout = prev_is_bullish and prev_body > (prev["high"] - prev["low"]) * 0.6 and prev_vol > avg_vol * 2 and prev["close"] > past_20_high
            
            # 当前K线缩量回踩，且没有跌破上一根大阳线的一半
            curr_is_weak_pullback = curr["vol"] < prev_vol * 0.8 and curr["close"] > (prev["open"] + prev["close"]) / 2
            
            # 当前价格不能偏离上一根最高点太远（防追高）
            distance_from_high = (prev["high"] - curr["close"]) / prev["high"] * 100
            not_chasing = distance_from_high < 1.0

            if prev_is_breakout and curr_is_weak_pullback and not_chasing:
                if check_orderbook(symbol) > 40 and check_ls_ratio(symbol) < 1.5:
                    entry = curr["close"]
                    sl = prev["low"] * 0.999 # 止损放在大阳线底部
                    risk = entry - sl
                    
                    trade = {"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": entry + risk*1.5, "tp2": entry + risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                    trades.append(trade)
                    send_tg(f"🐣 突破回踩做多! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}\n形态: 放量突破后缩量回踩")
                    alerts_sent += 1
                    
            # ================= 2. 做空逻辑（回踩确认） =================
            elif prev_is_bullish == False and prev_body > (prev["high"] - prev["low"]) * 0.6 and prev_vol > avg_vol * 2 and prev["close"] < past_20_low:
                curr_is_weak_rebound = curr["vol"] < prev_vol * 0.8 and curr["close"] < (prev["open"] + prev["close"]) / 2
                distance_from_low = (curr["close"] - prev["low"]) / prev["low"] * 100
                not_chasing_short = distance_from_low < 1.0

                if curr_is_weak_rebound and not_chasing_short:
                    if check_orderbook(symbol) < 60 and check_ls_ratio(symbol) > 0.6:
                        entry = curr["close"]
                        sl = prev["high"] * 1.001 # 止损放在大阴线顶部
                        risk = sl - entry
                        
                        trade = {"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": entry - risk*1.5, "tp2": entry - risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                        trades.append(trade)
                        send_tg(f"🩸 破位回踩做空! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}\n形态: 放量破位后缩量反弹")
                        alerts_sent += 1

            if alerts_sent >= 2: break
    except Exception as e:
        print(f"❌ 扫描出错: {e}")

if __name__ == "__main__":
    print("🚀 启动量化系统...")
    all_trades = load_trades()
    active_trades, new_trades = review_trades(all_trades)
    scan_market(active_trades)
    final_trades = new_trades + active_trades
    save_trades(final_trades)
