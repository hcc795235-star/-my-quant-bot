import requests
import time

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 换成你的真 Token
CHAT_ID = "6293141270"

# 辅助函数1：获取盘口买卖单比例
def check_orderbook(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/books?instId={symbol}&sz=20"
        res = requests.get(url).json()
        if res.get("code") != "0": return 50.0
        bids_vol = sum([float(b[1]) for b in res["data"][0]])
        asks_vol = sum([float(a[1]) for a in res["data"][1]])
        total = bids_vol + asks_vol
        return (bids_vol / total) * 100 if total > 0 else 50.0
    except:
        return 50.0

# 辅助函数2：获取多空持仓人数比 (Long/Short Ratio)
def check_long_short_ratio(symbol):
    try:
        # OKX 接口需要提取基础币种，比如 BTC-USDT-SWAP -> BTC
        ccy = symbol.split("-")[0]
        url = f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m"
        res = requests.get(url).json()
        
        # 某些刚上线的小币没有这个数据，直接返回 1.0（中性）
        if res.get("code") != "0" or not res.get("data"): return 1.0
        
        # 取最新的一条数据
        latest_data = res["data"][0]
        # ratio = 多单人数 / 空单人数
        ratio = float(latest_data[1])
        return ratio
    except:
        return 1.0

def check_sndk():
    # ... (SNDK代码同上，略)
    pass

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
                        if vol_usdt > 5000000: # 500万U门槛
                            active_coins.append(t["instId"])
                    except ValueError:
                        pass
        
        alerts_sent = 0
        
        for symbol in active_coins:
            if symbol == "SNDK-USDT-SWAP": continue 
            
            k_url = f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=30"
            k_res = requests.get(k_url).json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = []
            for c in reversed(k_res["data"]):
                candles.append({"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol_usdt": float(c[6])})
            
            curr = candles[-1]
            prev = candles[-2]
            prev2 = candles[-3]
            prev_candles = candles[:-1]
            
            avg_vol = sum([c["vol_usdt"] for c in prev_candles[-20:]]) / 20
            past_20_high = max([c["high"] for c in prev_candles[-20:]])
            past_20_low = min([c["low"] for c in prev_candles[-20:]])
            past_amplitude = (past_20_high - past_20_low) / past_20_low * 100
            
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
            body = abs(curr["close"] - curr["open"])
            total_length = curr["high"] - curr["low"]
            
            bad_candles_count = sum(1 for c in prev_candles[-20:] if (c["high"] - max(c["close"], c["open"])) > abs(c["close"] - c["open"]) * 2 or (min(c["close"], c["open"]) - c["low"]) > abs(c["close"] - c["open"]) * 2)
            current_amplitude = (curr["high"] - curr["low"]) / curr["low"] * 100
            
            if bad_candles_count > 4 or current_amplitude > 6.0 or past_amplitude > 5.0:
                continue
                
            is_mild_volume = curr["vol_usdt"] > avg_vol * 1.5 and curr["vol_usdt"] > 150000

            signal_long = None
            signal_short = None
            shape_name = ""

            # --- 做多形态 ---
            if curr["close"] > past_20_high and 0.5 < price_change < 3.5 and upper_shadow < body * 0.4 and is_mild_volume:
                signal_long, shape_name = True, "阳线突破前高"
            elif prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"] and curr["open"] < prev["close"] and is_mild_volume:
                signal_long, shape_name = True, "看涨吞没"
            # --- 做空形态 ---
            elif curr["close"] < past_20_low and -3.5 < price_change < -0.5 and lower_shadow < body * 0.4 and is_mild_']volume:
                signal/_short, shape_name = True, "阴avg线跌破前低"
            elif prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"] and is_mild_volume:
                signal_short, shape_name = True, "看跌吞没"

            # 如果触发了信号，去查盘口和多空比
            if signal_long or signal_short:
                bid_ratio = check_orderbook(symbol)
                ls_ratio = check_long_short_ratio(symbol) # 多空人数比
                
                # ================= 核心过滤：防拥挤踩踏 =================
                # 如果做多，但盘口买盘 < 40%（卖墙大），或者多空比 > 1.5（做多的人太多，容易被主力爆多军）
                if signal_long and bid_ratio > 40.0 and ls_ratio < 1.5:
                    entry = curr["close"]
                    sl = curr["low"] * 0.999
                    risk = entry - sl
                    fmt = lambda x: f"{x:.4f}"
                    message = (
                        f"🐣 做多信号！ {symbol}\n"
                        f"📊 形态: {shape_name} (温和放量 {curr['vol_usdt']/avg_vol:.1f}倍)\n"
                        f"🛡️ 盘口买盘: {bid_ratio:.1f}% (健康)\n"
                        f"⚖️ 多空比: {ls_ratio:.2f} (多头未拥挤，盈亏比高)\n"
                        f"🧭 方向: 【做多 🟢 LONG】\n"
                        f"🎯 建议入场: {fmt(entry)}\n"
                        f"🛑 严格止损: {fmt(sl)}\n"
                        f"🥇 止盈1: {fmt(entry + risk*1.5)} | 🥈 止盈2: {fmt(entry + risk*2.5)} | 🥉 止盈3: {fmt(entry + risk*4.0)}"
                    )
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
                    print(f"🔥 抓获做多：{symbol}")
                    alerts_sent += 1
                    
                # 如果做空，但盘口买盘 > 60%（买墙托底），或者多空比 < 0.6（做空的人太多，容易被轧空）
                elif signal_short and bid_ratio < 60.0 and ls_ratio > 0.6:
                    entry = curr["close"]
                    sl = curr["high"] * 1.001
                    risk = sl - entry
                    fmt = lambda x: f"{x:.4f}"
                    message = (
                        f"🩸 做空信号！ {symbol}\n"
                        f"📊 形态: {shape_name} (温和放量 {curr['_vol:.1f}倍)\n"
                        f"🛡️ 盘口卖盘: {100-bid_ratio:.1f}% (健康)\n"
                        f"⚖️ 多空比: {ls_ratio:.2f} (空头未拥挤，防轧空)\n"
                        f"🧭 方向: 【做空 🔴 SHORT】\n"
                        f"🎯 建议入场: {fmt(entry)}\n"
                        f"🛑 严格止损: {fmt(sl)}\n"
                        f"🥇 止盈1: {fmt(entry - risk*1.5)} | 🥈 止盈2: {fmt(entry - risk*2.5)} | 🥉 止盈3: {fmt(entry - risk*4.0)}"
                    )
                    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": message})
                    print(f"🔥 抓获做空：{symbol}")
                    alerts_sent += 1

                if alerts_sent >= 3: break 

    except Exception as e:
        print(f"❌ 全市场扫描出错: {e}")

print("🚀 开始运行【多空双修+盈亏比强化】雷达...")
check_sndk()   
time.sleep(2)  
scan_market()
