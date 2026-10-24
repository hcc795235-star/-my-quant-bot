import requests
import time

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"

# ================= 任务1：监控特定的美股代币 =================
def check_sndk():
    symbol = "SNDK-USDT-SWAP"
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=20"
        response = requests.get(url).json()
        if response.get("code") != "0": return

        raw_candles = response["data"]
        candles = []
        for c in reversed(raw_candles):
            candles.append({
                "open": float(c[1]), "high": float(c[2]), 
                "low": float(c[3]), "close": float(c[4]), 
                "vol_usdt": float(c[6])
            })

        curr = candles[-1]
        prev = candles[-2]
        avg_vol = sum([c["vol_usdt"] for c in candles[-20:-1]]) / 19
        
        # SNDK 盘前量小，用 1.5倍 和 5万U 门槛
        is_volume_spike = curr["vol_usdt"] > avg_vol * 1.5 and curr["vol_usdt"] > 50000 

        body = abs(curr["close"] - curr["open"])
        total_length = curr["high"] - curr["low"]
        upper_shadow = curr["high"] - max(curr["close"], curr["open"])
        lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
        
        signal, direction = None, None

        if curr["close"] > curr["open"] and body > total_length * 0.8 and is_volume_spike:
            signal, direction = "🟢 SNDK 大阳线", "LONG"
        elif curr["close"] < curr["open"] and body > total_length * 0.8 and is_volume_spike:
            signal, direction = "🔴 SNDK 大阴线", "SHORT"
        elif lower_shadow > body * 2 and upper_shadow < body * 0.5 and curr["close"] > curr["open"] and is_volume_spike:
            signal, direction = "🔨 SNDK 锤子线", "LONG"

        if signal:
            entry = curr["close"]
            sl = curr["low"] * 0.999 if direction == "LONG" else curr["high"] * 1.001
            risk = abs(entry - sl)
            tp1, tp2, tp3 = (entry + risk*1.5, entry + risk*2.5, entry + risk*4.0) if direction == "LONG" else (entry - risk*1.5, entry - risk*2.5, entry - risk*4.0)
            
            fmt = lambda x: f"{x:.3f}"
            message = (
                f"🚨 {symbol} 形态信号！\n"
                f"📊 形态: {signal} (放量 {curr['vol_usdt']/avg_vol:.1f}倍)\n"
                f"🧭 方向: {'做多' if direction == 'LONG' else '做空'}\n"
                f"🎯 建议入场: {fmt(entry)}\n"
                f"🛑 严格止损: {fmt(sl)}\n"
                f"🥇 止盈1: {fmt(tp1)} | 🥈 止盈2: {fmt(tp2)} | 🥉 止盈3: {fmt(tp3)}"
            )
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
            print(f"🔥 SNDK 信号触发：{signal}")
    except Exception as e:
        print(f"❌ SNDK 监控出错: {e}")


# ================= 任务2：全市场扫描爆量山寨币 =================
def scan_market():
    try:
        tickers_url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        res = requests.get(tickers_url).json()
        if res.get("code") != "0": return
            
        tickers = res["data"]
        active_coins = []
        for t in tickers:
            if t["instId"].endswith("USDT-SWAP"):
                vol_usdt = float(t["volCcy24h"]) * float(t["last"])
                if vol_usdt > 5000000: # 成交额 > 500万U
                    active_coins.append(t["instId"])
        
        alerts_sent = 0
        
        for symbol in active_coins:
            if symbol == "SNDK-USDT-SWAP": continue # SNDK 交给上面的任务单独处理
            
            k_url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=20"
            k_res = requests.get(k_url).json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = []
            for c in reversed(k_res["data"]):
                candles.append({"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol_usdt": float(c[6])})
            
            curr = candles[-1]
            prev_candles = candles[:-1]
            avg_vol = sum([c["vol_usdt"] for c in prev_candles]) / len(prev_candles)
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            past_max_high = max([c["high"] for c in prev_candles])
            upper_shadow = curr["high"] - curr["close"]
            body = abs(curr["close"] - curr["open"])
            
            # 防骗炮核心逻辑
            is_spike = curr["vol_usdt"] > 1000000 and curr["vol_usdt"] > avg_vol * 5
            is_pump = price_change > 2
            is_breakout = curr["close"] > past_max_high
            is_strong_close = upper_shadow < body * 0.3 
            
            if is_spike and is_pump and is_breakout and is_strong_close:
                entry = curr["close"]
                sl = curr["low"] * 0.999
                risk = entry - sl
                fmt = lambda x: f"{x:.4f}"
                message = (
                    f"🚨 全市场爆量妖币！ {symbol}\n"
                    f"🚀 5m涨幅: +{price_change:.2f}%\n"
                    f"💵 5m成交额: {curr['vol_usdt']:,.0f} U (爆量 {curr['vol_usdt']/avg_vol:.1f}倍)\n"
                    f"✅ 已突破前高，实体强势收线\n"
                    f"🎯 建议入场: {fmt(entry)}\n"
                    f"🛑 严格止损: {fmt(sl)}\n"
                    f"🥇 止盈1: {fmt(entry + risk*1.5)} | 🥈 止盈2: {fmt(entry + risk*2.5)}"
                )
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
                print(f"🔥 抓获妖币：{symbol}")
                alerts_sent += 1
                if alerts_sent >= 3: break # 一次最多发 3 条

    except Exception as e:
        print(f"❌ 全市场扫描出错: {e}")

# ================= 启动执行 =================
print("🚀 开始运行雷达监控...")
check_sndk()   # 先单独查 SNDK
time.sleep(2)  # 停顿2秒防封IP
scan_market()  # 再扫全市场
