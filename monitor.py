import requests
import time
import json
import os
from datetime import datetime, timezone

TOKEN = "你的新Token"  # ⚠️ 换成你的真 Token
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
    try:
        k_url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=10"
        res = requests.get(k_url).json()
        if res.get("code") != "0": return "无法获取K线数据进行分析。"

        candles = [{"open": float(c[1]), "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "vol": float(c[6])} for c in reversed(res["data"])]
        
        curr = candles[-1]
        body = abs(curr["close"] - curr["open"])
        upper_shadow = curr["high"] - max(curr["close"], curr["open"])
        lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
        avg_vol = sum([c["vol"] for c in candles[-8:-1]]) / 7
        
        btc_res = requests.get("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=5m&limit=3").json()
        btc_change = 0
        if btc_res.get("code") == "0":
            btc_candles = btc_res["data"]
            btc_change = (float(btc_candles[0][4]) - float(btc_candles[-1][1])) / float(btc_candles[-1][1]) * 100

        reasons = []
        if direction == "LONG":
            if lower_shadow > body * 2: reasons.append("⚡ 遭遇插针扫损：出现极长下影线，主力恶意洗盘爆多单。")
            if curr["close"] < curr["open"] and curr["vol"] < avg_vol * 0.8: reasons.append("📉 动能衰竭：突破后无量跟风，多头力竭被反杀。")
            if btc_change < -0.5: reasons.append(f"🌐 大盘拖累：BTC 同一时间下跌 {btc_change:.2f}%，带崩全场。")
        else:
            if upper_shadow > body * 2: reasons.append("⚡ 遭遇轧空插针：出现极长上影线，主力爆空单。")
            if curr["close"] > curr["open"] and curr["vol"] > avg_vol * 2: reasons.append("🚀 暴力反拉：空头遭遇大资金强行逼空，放量拉升。")
            if btc_change > 0.5: reasons.append(f"🌐 大盘带动：BTC 同一时间拉升 {btc_change:.2f}%，顺势轧空。")

        if not reasons: reasons.append("💣 正常技术性破位：市场随机波动导致形态失效。")
        return f"🧠 【AI 深度复盘】\n" + "\n".join(reasons)
    except: return "AI分析模块异常。"

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
                ai_analysis = ai_diagnose_loss(t["symbol"], "LONG", t["entry"], curr_price)
                send_tg(f"🛑 {t['symbol']} 多单触及止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}\n\n{ai_analysis}")
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
                ai_analysis = ai_diagnose_loss(t["symbol"], "SHORT", t["entry"], curr_price)
                send_tg(f"🛑 {t['symbol']} 空单触及止损！\n入场: {t['entry']:.4f} | 出场: {curr_price:.4f}\n\n{ai_analysis}")
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
        # 【修复核心】：用 try-except 过滤掉脏数据（空字符串）
        for t in res["data"]:
            if t["instId"].endswith("USDT-SWAP"):
                last_price = t.get("last", "")
                vol_24h = t.get("volCcy24h", "")
                # 必须确保不是空字符才能计算
                if last_price and vol_24h:
                    try:
                        vol_usdt = float(vol_24h) * float(last_price)
                        if vol_usdt > 5000000:
                            active_coins.append(t["instId"])
                    except ValueError:
                        pass # 如果转换失败，直接跳过这个币，不报错
        
        alerts_sent = 0
        for symbol in active_coins:
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades): continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            
            curr, prev_candles = candles[-1], candles[:-1]
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            past_20_high = max([c["high"] for c in prev_candles[-20:]])
            past_20_low = min([c["low"] for c in prev_candles[-20:]])
            
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            
            if curr["close"] > past_20_high and 0.5 < price_change < 3.0 and curr["vol"] > avg_vol * 1.5 and curr["vol"] > 150000:
                if check_orderbook(symbol) > 40 and check_ls_ratio(symbol) < 1.5:
                    entry = curr["close"]
                    sl = curr["low"] * 0.999
                    risk = entry - sl
                    
                    trade = {"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": entry + risk*1.5, "tp2": entry + risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                    trades.append(trade)
                    send_tg(f"🐣 开多信号! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}")
                    alerts_sent += 1
                    
            elif curr["close"] < past_20_low and -3.0 < price_change < -0.5 and curr["vol"] > avg_vol * 1.5 and curr["vol"] > 150000:
                if check_orderbook(symbol) < 60 and check_ls_ratio(symbol) > 0.6:
                    entry = curr["close"]
                    sl = curr["high"] * 1.001
                    risk = sl - entry
                    
                    trade = {"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": entry - risk*1.5, "tp2": entry - risk*2.5, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"}
                    trades.append(trade)
                    send_tg(f"🩸 开空信号! {symbol}\n入场: {entry:.4f} | 止损: {sl:.4f}\n止盈1: {trade['tp1']:.4f} | 止盈2: {trade['tp2']:.4f}")
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
