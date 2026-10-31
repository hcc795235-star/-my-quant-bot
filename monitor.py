import requests
import json
import os
from datetime import datetime, timezone, timedelta

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 记得换成你的真 Token
CHAT_ID = "6293141270"
DB_FILE = "trades.json"
REPORT_FILE = "last_report.json"
CYCLE_FILE = "cycle_time.json"

MAX_OPEN_TRADES = 15  
CYCLE_HOURS = 3       # 每 3 小时强制换血

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
    requests.post(url, json={"chat_id": CHAT_ID, "text": message})

def calculate_rsi(candles, period=14):
    if len(candles) < period + 1: return 50.0
    gains, losses = 0, 0
    for i in range(1, period + 1):
        change = candles[-i]["close"] - candles[-i-1]["close"]
        if change > 0: gains += change
        else: losses -= change
    if losses == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + (gains / losses)))

def get_current_price(symbol):
    try:
        res = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={symbol}").json()
        if res.get("code") == "0": return float(res["data"][0]["last"])
    except: pass
    return None

# ================= 核心：AI 诊断复盘逻辑 =================
def ai_diagnose(symbol, direction):
    try:
        k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=5").json()
        if k_res.get("code") != "0": return "数据获取失败。"
        
        candles = [{"close": float(c[4]), "open": float(c[1])} for c in k_res["data"]]
        curr = candles[0]
        
        btc_res = requests.get("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=5m&limit=3").json()
        btc_change = 0
        if btc_res.get("code") == "0":
            btc_candles = btc_res["data"]
            btc_change = (float(btc_candles[0][4]) - float(btc_candles[-1][1])) / float(btc_candles[-1][1]) * 100

        if direction == "LONG" and btc_change < -0.5:
            return f"🌐 大盘拖累：做多时 BTC 正在下跌 ({btc_change:.2f}%)，泥沙俱下。"
        elif direction == "SHORT" and btc_change > 0.5:
            return f"🌐 大盘逼空：做空时 BTC 正在拉升 ({btc_change:.2f}%)，引发轧空。"
        else:
            return "💣 技术性假突破：主力画线洗盘，形态失效。"
    except: return "AI分析模块异常。"

def review_trades(trades):
    active_trades, new_trades = [], []
    
    for t in trades:
        if t["status"] != "OPEN":
            new_trades.append(t); continue
            
        curr_price = get_current_price(t["symbol"])
        if not curr_price: active_trades.append(t); continue

        closed = False
        # 保本推止损逻辑
        if t["direction"] == "LONG":
            if curr_price - t["entry"] >= (t["entry"] - t["sl"]) and t["sl"] < t["entry"]:
                t["sl"] = t["entry"]
            if curr_price <= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price >= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price >= t["tp1"]: t["status"] = "WIN_TP1"; closed = True
        elif t["direction"] == "SHORT":
            if t["entry"] - curr_price >= (t["sl"] - t["entry"]) and t["sl"] > t["entry"]:
                t["sl"] = t["entry"]
            if curr_price >= t["sl"]: t["status"] = "LOSS"; closed = True
            elif curr_price <= t["tp2"]: t["status"] = "WIN_TP2"; closed = True
            elif curr_price <= t["tp1"]: t["status"] = "WIN_TP1"; closed = True

        if closed: 
            t["close_time"] = datetime.now(timezone.utc).isoformat()
            # 如果是亏损，立刻触发 AI 诊断
            if t["status"] == "LOSS":
                reason = ai_diagnose(t["symbol"], t["direction"])
                send_tg(f"🛑 {t['symbol']} 触发止损！\n\n🧠 【AI 诊断】\n{reason}")
            new_trades.append(t)
        else: active_trades.append(t)
    return active_trades, new_trades

# ================= 扫描市场 =================
def scan_market(trades):
    if len(trades) >= MAX_OPEN_TRADES: return
    try:
        res = requests.get("https://www.okx.com/api/v5/market/tickers?instType=SWAP").json()
        active_coins = []
        for t in res.get("data", []):
            if t.get("instId", "").endswith("USDT-SWAP"):
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
            curr, prev = candles[-1], candles[-2]
            avg_vol = sum([c["vol"] for c in candles[:-1][-20:]]) / 20
            rsi = calculate_rsi(candles, 14) 
            
            body = abs(curr["close"] - curr["open"])
            total_length = curr["high"] - curr["low"] if (curr["high"] - curr["low"]) > 0 else 0.0001
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100

            # 做多逻辑
            is_long_signal = (prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"]) or (lower_shadow > body * 2 and curr["vol"] > avg_vol * 1.2)
            if is_long_signal and rsi < 70:
                entry = curr["close"]
                sl = min([c["low"] for c in candles[-10:]]) * 0.998
                min_sl_dist = entry * (0.006 if entry > 1000 else 0.015)
                if (entry - sl) < min_sl_dist: sl = entry - min_sl_dist
                
                risk = entry - sl
                if risk / entry <= 0.04:
                    tp1, tp2 = entry + risk * (1.5 if entry > 1000 else 2.0), entry + risk * (2.0 if entry > 1000 else 3.0)
                    trades.append({"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                    send_tg(f"🐂 底部反转做多! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)}\n(RSI: {rsi:.1f})")
                    alerts_sent += 1
                    continue

            # 做空逻辑
            is_short_signal = (upper_shadow > body * 2 and upper_shadow > total_length * 0.5) or (prev["close"] > prev["open"] and curr["close"] < curr["open"])
            if is_short_signal and rsi > 30:
                entry = curr["close"]
                sl = max([c["high"] for c in candles[-10:]]) * 1.002
                min_sl_dist = entry * (0.006 if entry > 1000 else 0.015)
                if (sl - entry) < min_sl_dist: sl = entry + min_sl_dist
                
                risk = sl - entry
                if risk / entry <= 0.04:
                    tp1, tp2 = entry - risk * (1.5 if entry > 1000 else 2.0), entry - risk * (2.0 if entry > 1000 else 3.0)
                    trades.append({"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                    send_tg(f"🔪 高位做空! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)}\n(RSI: {rsi:.1f})")
                    alerts_sent += 1
    except Exception as e:
        print(f"扫描出错: {e}")

# ================= 主程序 =================
if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    all_trades = load_json(DB_FILE, [])
    report_data = load_json(REPORT_FILE, {"last_4h_time": 0, "last_12h_time": 0})
    cycle_data = load_json(CYCLE_FILE, {"last_reset": 0})
    
    # 1. 检查 3 小时强制轮转
    if now.timestamp() - cycle_data["last_reset"] >= CYCLE_HOURS * 3600:
        active_old = [t for t in all_trades if t["status"] == "OPEN"]
        if active_old:
            send_tg(f"⏰ 【3小时强制换血】清理当前持仓 {len(active_old)} 单，重新扫描！")
            for t in active_old: t["status"] = "CYCLE_TIMEOUT"
        cycle_data["last_reset"] = now.timestamp()
        
    # 2. 正常运行：查平仓、开新单
    active_trades, new_trades = review_trades(all_trades)
    scan_market(active_trades)
    final_trades = new_trades + active_trades
    
    # 3. 检查 4 小时周期战报（距离上次满 4 小时即发）
    if now.timestamp() - report_data["last_4h_time"] >= 4 * 3600:
        closed = [t for t in final_trades if t["status"] != "OPEN"]
        wins = len([t for t in closed if "WIN" in t["status"]])
        losses = len([t for t in closed if t["status"] == "LOSS"])
        rate = (wins / len(closed) * 100) if closed else 0
        send_tg(f"📊 【4小时周期战报】\n当前总持仓: {len(active_trades)} / 15\n累计平仓: {len(closed)} 单\n胜率: {rate:.1f}% (✅胜{wins} | 🛑负{losses})")
        report_data["last_4h_time"] = now.timestamp()

    # 4. 检查 12 小时 AI 总结（距离上次满 12 小时即发）
    if now.timestamp() - report_data["last_12h_time"] >= 12 * 3600:
        # 这里只是做一个整体宏观总结
        send_tg(f"🧠 【12小时全局复盘】\n市场依然充满欺骗性。请严格按照止损位执行，不要扛单。系统已为您过滤了大量假突破。")
        report_data["last_12h_time"] = now.timestamp()

    # 保存所有数据
    save_json(DB_FILE, final_trades)
    save_json(REPORT_FILE, report_data)
    save_json(CYCLE_FILE, cycle_data)
