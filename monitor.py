import requests
import time

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"

def check_sndk():
    symbol = "SNDK-USDT-SWAP"
    try:
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30"
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
        
        is_volume_spike = curr["vol_usdt"] > avg_vol * 1.5 and curr["vol_usdt"] > 50000 

        body = abs(curr["close"] - curr["open"])
        total_length = curr["high"] - curr["low"]
        upper_shadow = curr["high"] - max(curr["close"], curr["open"])
        lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
        
        signal, direction = None, None
        price_change = (curr["close"] - curr["open"]) / curr["open"] * 100

        # 涨幅限制在 0.5% ~ 3.5% 之间，防追高
        if curr["close"] > curr["open"] and body > total_length * 0.7 and is_volume_spike and 0.5 < price_change < 3.5:
            signal, direction = "🟢 SNDK 温和放量突破", "LONG"
        elif curr["close"] < curr["open"] and body > total_length * 0.7 and is_volume_spike and -3.5 < price_change < -0.5:
            signal, direction = "🔴 SNDK 温和放量下破", "SHORT"

        if signal:
            entry = curr["close"]
            sl = curr["low"] * 0.999 if direction == "LONG" else curr["high"] * 1.001
            risk = abs(entry - sl)
            tp1, tp2, tp3 = (entry + risk*1.5, entry + risk*2.5, entry + risk*4.0) if direction == "LONG" else (entry - risk*1.5, entry - risk*2.5, entry - risk*4.0)
            
            fmt = lambda x: f"{x:.3f}"
            message = (
                f"🚨 {symbol} 潜伏信号！\n"
                f"📊 形态: {signal} (温和放量 {curr['vol_usdt']/avg_vol:.1f}倍)\n"
                f"🧭 方向: {'做多' if direction == 'LONG' else '做空'}\n"
                f"🎯 建议入场: {fmt(entry)}\n"
                f"🛑 严格止损: {fmt(sl)}\n"
                f"🥇 止盈1: {fmt(tp1)} | 🥈 止盈2: {fmt(tp2)} | 🥉 止盈3: {fmt(tp3)}"
            )
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
            print(f"🔥 SNDK 信号触发：{signal}")
    except Exception as e:
        print(f"❌ SNDK 监控出错: {e}")


def scan_market():
    try:
        tickers_url = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
        res = requests.get(tickers_url).json()
        if res.get("code") != "0": return
            
        tickers = res["data"]
        active_coins = []
        
        for t in tickers:
            if t["instId"].endswith("USDT-SWAP"):
                last_price = t.get("last", "")
                vol_24h = t.get("volCcy24h", "")
                
                if last_price and vol_24h:
                    try:
                        vol_usdt = float(vol_24h) * float(last_price)
                        # 池子：24h成交额大于 200万 U
                        if vol_usdt > 2000000: 
                            active_coins.append(t["instId"])
                    except ValueError:
                        pass
        
        alerts_sent = 0
        
        for symbol in active_coins:
            if symbol == "SNDK-USDT-SWAP": continue 
            
            # 获取 30 根 K 线，用来判断前期是否横盘
            k_url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30"
            k_res = requests.get(k_url).json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = []
            for c in reversed(k_res["data"]):
                candles.append({"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol_usdt": float(c[6])})
            
            curr = candles[-1]
            prev_candles = candles[:-1]
            
            # 1. 过去 20 根 K 线的平均成交量
            avg_vol = sum([c["vol_usdt"] for c in prev_candles[-20:]]) / 20
            
            # 2. 判断是否“无量横盘”：过去 20 根的振幅小于 2%
            past_20_high = max([c["high"] for c in prev_candles[-20:]])
            past_20_low = min([c["low"] for c in prev_candles[-20:]])
            past_amplitude = (past_20_high - past_20_low) / past_20_low * 100
            
            # 3. 当前这根 K 线的指标
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            # 当前价格离这根 K 线最低点的距离（防针尖）
            pump_from_low = (curr["close"] - curr["low"]) / curr["low"] * 100
            upper_shadow = curr["high"] - curr["close"]
            body = abs(curr["close"] - curr["open"])
            
            # ================= 核心潜伏逻辑 =================
            # A. 前期必须是死水：振幅 < 4%
            is_sideways = past_amplitude < 4.0
            
            # B. 刚刚开始温和放量：最新量 > 过去均量的 1.5 倍
            is_mild_volume = curr["vol_usdt"] > avg_vol * 1.5 and curr["vol_usdt"] > 100000
            
            # C. 偷偷拉升：涨幅在 0.5% 到 3.5% 之间（绝对不能是爆拉，爆拉就是后期了）
            is_early_pump = 0.5 < price_change < 3.5
            
            # D. 突破：价格刚好突破了前 20 根的最高点
            is_breakout = curr["close"] > past_20_high
            
            # E. 形态健康：上影线不能长，且不是针尖拉上来的
            is_healthy = upper_shadow < body * 0.4 and pump_from_low < 2.5
            
            if is_sideways and is_mild_volume and is_early_pump and is_breakout and is_healthy:
                entry = curr["close"]
                sl = curr["low"] * 0.999
                risk = entry - sl
                fmt = lambda x: f"{x:.4f}"
                
                message = (
                    f"🐣 发现潜伏起爆币！ {symbol}\n"
                    f"🌱 前期横盘振幅: {past_amplitude:.2f}% (无量死水)\n"
                    f"🚀 当前温和拉升: +{price_change:.2f}%\n"
                    f"💵 温和放量: {curr['vol_usdt']/avg_vol:.1f} 倍 (刚睡醒)\n"
                    f"🎯 建议入场: {fmt(entry)}\n"
                    f"🛑 严格止损: {fmt(sl)}\n"
                    f"🥇 止盈1: {fmt(entry + risk*1.5)} | 🥈 止盈2: {fmt(entry + risk*2.5)}"
                )
                requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
                print(f"🔥 抓获潜伏币：{symbol}")
                alerts_sent += 1
                if alerts_sent >= 3: break 

    except Exception as e:
        print(f"❌ 全市场扫描出错: {e}")

print("🚀 开始运行【潜伏起爆】雷达...")
check_sndk()   
time.sleep(2)  
scan_market()
