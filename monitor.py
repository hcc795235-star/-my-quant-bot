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
        
        for symbol in active_coins:
            if any(t["symbol"] == symbol and t["status"] == "OPEN" for t in trades): continue

            k_res = requests.get(f"https://www.okx.com/api/v5/market/candles?instId={symbol}&bar=5m&limit=60").json()
            if k_res.get("code") != "0" or not k_res.get("data"): continue
                
            candles = [{"high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "open": float(c[1]), "vol": float(c[6])} for c in reversed(k_res["data"])]
            curr, prev, prev2 = candles[-1], candles[-2], candles[-3]
            prev_candles = candles[:-1]
            
            avg_vol = sum([c["vol"] for c in prev_candles[-20:]]) / 20
            ema50 = sum([c["close"] for c in candles[-50:]]) / 50  
            
            # 过滤上下插针垃圾币
            bad_pin_count = 0
            for c in prev_candles[-20:]:
                c_body = abs(c["close"] - c["open"])
                c_upper = c["high"] - max(c["close"], c["open"])
                c_lower = min(c["close"], c["open"]) - c["low"]
                if (c_upper > c_body * 2) or (c_lower > c_body * 2): bad_pin_count += 1
            if bad_pin_count > 4: continue
            if (curr["high"] - curr["low"]) / curr["low"] * 100 > 5.0: continue
            
            body = abs(curr["close"] - curr["open"])
            upper_shadow = curr["high"] - max(curr["close"], curr["open"])
            price_change = (curr["close"] - curr["open"]) / curr["open"] * 100

            is_uptrend = curr["close"] > ema50
            is_downtrend = curr["close"] < ema50

            # ================= 做多逻辑 =================
            is_slow_rise = (curr["close"] > curr["open"] and prev["close"] > prev["open"] and prev2["close"] > prev2["open"] and 0.2 < price_change < 2.5 and curr["vol"] > avg_vol * 0.5)
            if is_slow_rise and is_uptrend:
                entry = curr["close"]
                
                # 找过去10根K线的最低价作为结构支撑
                recent_low = min([c["low"] for c in candles[-10:]])
                structural_sl = recent_low * 0.998 # 留0.2%防插针
                
                # 强制要求止损空间至少 1.5%
                min_sl_dist = entry * 0.015
                if (entry - structural_sl) < min_sl_dist:
                    sl = entry - min_sl_dist
                else:
                    sl = structural_sl
                    
                risk = entry - sl
                
                # 如果止损空间大于 4%，说明位置太高，盈亏比不划算，放弃！
                if risk / entry > 0.04:
                    continue
                    
                tp1 = entry + risk * 2.0  # 盈亏比 1:2
                tp2 = entry + risk * 3.0  # 盈亏比 1:3
                
                trades.append({"symbol": symbol, "direction": "LONG", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                send_tg(f"🐌 缩量慢涨做多! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:2): {fmt_price(tp1)}\n🥈止盈2(1:3): {fmt_price(tp2)}\n⏰ {get_bj_time()}")
                continue

            # ================= 做空逻辑 =================
            is_top_rejection = (upper_shadow > body * 2 and upper_shadow > (curr["high"] - curr["low"]) * 0.5)
            is_bearish_engulf = (prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"])
            
            if (is_top_rejection or is_bearish_engulf) and is_downtrend:
                if check_orderbook(symbol) < 55:
                    entry = curr["close"]
                    
                    # 找过去10根K线的最高价作为结构阻力
                    recent_high = max([c["high"] for c in candles[-10:]])
                    structural_sl = recent_high * 1.002 # 留0.2%防插针
                    
                    # 强制要求止损空间至少 1.5%
                    min_sl_dist = entry * 0.015
                    if (structural_sl - entry) < min_sl_dist:
                        sl = entry + min_sl_dist
                    else:
                        sl = structural_sl
                        
                    risk = sl - entry
                    
                    # 如果止损空间大于 4%，放弃！
                    if risk / entry > 0.04:
                        continue
                        
                    tp1 = entry - risk * 2.0  # 盈亏比 1:2
                    tp2 = entry - risk * 3.0  # 盈亏比 1:3
                    
                    shape = "高位流星线" if is_top_rejection else "高位阴包阳"
                    trades.append({"symbol": symbol, "direction": "SHORT", "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "time": datetime.now(timezone.utc).isoformat(), "status": "OPEN"})
                    send_tg(f"🔪 {shape}做空! {symbol}\n入场: {fmt_price(entry)}\n止损: {fmt_price(sl)} (空间 {risk/entry*100:.2f}%)\n🥇止盈1(1:2): {fmt_price(tp1)}\n🥈止盈2(1:3): {fmt_price(tp2)}\n⏰ {get_bj_time()}")

    except Exception as e:
        print(f"❌ 扫描出错: {e}")
