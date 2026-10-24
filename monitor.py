import requests
import time
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"

def load_trades():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
    return []

def save_trades(trades):
    with open(DB_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def send_tg(message):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})

# 辅助：获取盘口
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

# 辅助：获取多空比
def check_ls_ratio(symbol):
    try:
        ccy = symbol.split("-")[0]
        url = f"https://www.okx.com/api/v5/statistics/contracts/long-short-account-ratio?ccy={ccy}&period=5m"
        res = requests.get(url).json()
        if res.get("code") != "0" or not res.get("data"): return 1.0
        return float(res["data"][0][1])
    except: return 1.0

# 辅助：获取最新价格
def get_current_price(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
        res = requests.get(url).json()
        if res.get("code") == "0":
            return float(res["data"][0]["last"])
    except: pass
    return None

def review_trades(trades):
    """复盘检查"""
    now = datetime.now(timezone.utc)
    active_trades = []
    
    for t in trades:
        if t["status"] != "OPEN":
            continue
            
        # 超过 2 小时强制平仓记录（模拟）
        entry_time = datetime.fromisoformat(t["time"])
        if (now - entry_time).total_seconds() > 7200:
            t["status"] = "TIMEOUT"
            send_tg(f"⏳ {t['symbol']} 持仓超2小时，自动按现价平仓记录。")
            continue

        curr_price = get_current_price(t["symbol"])
        if not curr_price:
            active_trades.append(t)
            continue

        # 检查是否触发止盈止损
        if t["direction"] == "LONG":
            if curr_price <= t["sl"]:
                t["status"] = "LOSS"
                send_tg(f"🛑 {t['symbol']} 多单触及止损: {t['sl']}")
            elif curr_price >= t["tp2"]:
                t["status"] = "WIN_TP2"
                send_tg(f"🏆 {t['symbol']} 多单止盈2达成: {t['tp2']}")
            elif curr_price >= t["tp1"]:
                t["status"] = "WIN_TP1"
                send_tg(f"✅ {t['symbol']} 多单止盈1达成: {t['tp1']}")
            else:
                active_trades.append(t)
                
        elif t["direction"] == "SHORT":
            if curr_price >= t["sl"]:
                t["status"] = "LOSS"
                send_tg(f"🛑 {t['symbol']} 空单触及止损: {t['sl']}")
            elif curr_price <= t["tp2"]:
                t["status"] = "WIN_TP2"
                send_tg(f"🏆 {t['symbol']} 空单止盈2达成: {t['tp2']}")
            elif curr_price <= t["tp1"]:
                t["status"] = "WIN_TP1"
                send_tg(f"✅ {t['symbol']} 空单止盈1达成: {t['tp1']}")
            else:
                active_trades.append(t)
                
    return active_trades

def calculate_stats(trades):
    """计算胜率"""
    closed = [t for t in trades if t["status"] != "OPEN"]
    if not closed: return "暂无已完结交易记录"
    wins = len([t for t in closed if "WIN" in t["status"]])
    losses = len([t for t in closed if t["status"] == "LOSS"])
    total = len(closed)
    win_rate = (wins / total) * 100 if total > 0 else 0
    return f"📊 总开单: {total} | 胜: {wins} | 负: {losses} | 胜率: {win_rate:.1f}%"

def scan_market(trades):
    """扫描新信号（简化了之前的形态判断，重点演示流程）"""
    try:
        res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP").json()
        active_coins = [t["instId"] for t in res["data"] if t["instId"].endswith("USDT-SWAP") and float(t.get("volCcy24h", 0)) * float(t.get("last", 0)) > 5000000]
        
        alerts_sent = 0
        for symbol in active_coins:
            if symbol == "SNDK-USDT-SWAP": continue 
            
            # 避免重复开单：如果账本里有这个币的 OPEN 状态，跳过
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades):
                continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            
            curr, prev_candles = candles[-1], candles[:-1]
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            past_20_high = max([c["high"] for c in prev_candles[-20:]])
            past_20_low = min([c["low"] for c in prev_candles[-20:]])
            
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            body = abs(curr["close"] - curr["open"])
            
            # 简化的做多逻辑：放量突破前高，涨幅 0.5% ~ 3%
            if curr["close"] > past_20_high and 0.5 < price_change < 3.0 and curr["vol"] > avg_vol * 1.5 and curr["vol"] > 150000:
                if check_orderbook(symbol) > 40 and check_ls_ratio(symbol) < 1.5:
                    entry = curr["close"]
                    sl = curr["low"] * 0.999
                    risk = entry - sl
                    
                    trade = {
                        "symbol": symbol, "direction": "LONG", 
                        "entry": entry, "sl": sl, 
                        "tp1": entry + risk*1.5, "tp2": entry + risk*2.5, 
                        "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"
                    }
                    trades.append(trade)
                    send_tg(f"🐣 开多信号! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}")
                    alerts_sent += 1
                    
            # 简化的做空逻辑
            elif curr["close"] < past_20_low and -3.0 < price_change < -0.5 and curr["vol"] > avg_vol * 1.5 and curr["vol"] > 150000:
                if check_orderbook(symbol) < 60 and check_ls_ratio(symbol) > 0.6:
                    entry = curr["close"]
                    sl = curr["high"] * 1.001
                    risk = sl - entry
                    
                    trade = {
                        "symbol": symbol, "direction": "SHORT", 
                        "entry": entry, "sl": sl, 
                        "tp1": entry - risk*1.5, "tp2": entry - risk*2.5, 
                        "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"
                    }
                    trades.append(trade)
                    send_tg(f"🩸 开空信号! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}")
                    alerts_sent += 1

            if alerts_sent >= 2: break
    except Exception as e:
        print(f"❌ 扫描出错: {e}")

if __name__ == "__main__":
    print(f"🚀 启动量化系统...")
    all_trades = load_trades()
    
    # 1. 先复盘旧单子
    active_trades = review_trades(all_trades)
    
    # 2. 扫描新单子
    scan_market(active_trades)
    
    # 3. 保存账本
    save_trades(active_trades)
    
    # 4. 每天早上8点推送一次胜率报告（这里用简单的时间判断代替）
    if datetime.now(timezone.utc).hour == 0: # 0点是 UTC 时间，相当于北京早上8点
        stats = calculate_stats(active_trades)
        send_tg(f"🌅 每日复盘报告\n{stats}")
