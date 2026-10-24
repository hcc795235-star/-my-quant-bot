import requests

TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"  # ⚠️ 记得换成你的真 Token
CHAT_ID = "6293141270"
SYMBOL = "SNDKUSDT"

def analyze_market():
    try:
        # 获取最近 50 根 5分钟 K线
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={SYMBOL}&interval=5m&limit=50"
        response = requests.get(url).json()
        
        # 检查 API 是否报错
        if isinstance(response, dict) and "code" in response:
            print(f"API报错: {response}")
            return

        candles = []
        for c in response:
            candles.append({
                "open": float(c[1]), "high": float(c[2]), 
                "low": float(c[3]), "close": float(c[4]), 
                "vol": float(c[7]) # USDT成交额
            })

        curr = candles[-1]
        prev = candles[-2]
        
        # 严格放量过滤：当前量 > 过去20根平均量的2倍，且成交额 > 5万美金
        avg_vol = sum([c["vol"] for c in candles[-20:-1]]) / 19
        is_volume_spike = curr["vol"] > avg_vol * 2 and curr["vol"] > 50000 

        body = abs(curr["close"] - curr["open"])
        total_length = curr["high"] - curr["low"]
        upper_shadow = curr["high"] - max(curr["close"], curr["open"])
        lower_shadow = min(curr["close"], curr["open"]) - curr["low"]
        
        signal = None
        direction = None

        # ================= 形态识别逻辑 =================
        if curr["close"] > curr["open"] and body > total_length * 0.8 and is_volume_spike:
            signal, direction = "🟢 大阳线 (放量)", "LONG"
        elif curr["close"] < curr["open"] and body > total_length * 0.8 and is_volume_spike:
            signal, direction = "🔴 大阴线 (放量)", "SHORT"
        elif lower_shadow > body * 2 and upper_shadow < body * 0.5 and curr["close"] > curr["open"] and is_volume_spike:
            signal, direction = "🔨 锤子线 (放量)", "LONG"
        elif prev["close"] < prev["open"] and curr["close"] > curr["open"] and curr["close"] > prev["open"] and curr["open"] < prev["close"] and is_volume_spike:
            signal, direction = "🟢 阳包阴 (放量反攻)", "LONG"
        elif prev["close"] > prev["open"] and curr["close"] < curr["open"] and curr["close"] < prev["open"] and curr["open"] > prev["close"] and is_volume_spike:
            signal, direction = "🔴 阴包阳 (放量砸盘)", "SHORT"

        # ================= 计算止盈止损 =================
        if signal:
            entry_price = curr["close"]
            
            if direction == "LONG":
                stop_loss = curr["low"] * 0.999 
                risk = entry_price - stop_loss
                tp1 = entry_price + (risk * 1.5)
                tp2 = entry_price + (risk * 2.5)
                tp3 = entry_price + (risk * 4.0)
            else:
                stop_loss = curr["high"] * 1.001
                risk = stop_loss - entry_price
                tp1 = entry_price - (risk * 1.5)
                tp2 = entry_price - (risk * 2.5)
                tp3 = entry_price - (risk * 4.0)

            fmt = lambda x: f"{x:.3f}"
            
            message = (
                f"🚨 {SYMBOL} 交易信号！\n"
                f"📊 形态: {signal}\n"
                f"📈 放量: {curr['vol']/avg_vol:.1f} 倍 (达 5万U)\n"
                f"🧭 方向: {'做多' if direction == 'LONG' else '做空'}\n"
                f"-------------------\n"
                f"🎯 建议入场: {fmt(entry_price)}\n"
                f"🛑 严格止损: {fmt(stop_loss)}\n"
                f"-------------------\n"
                f"🥇 止盈1 (减仓50%): {fmt(tp1)}\n"
                f"🥈 止盈2 (减仓30%): {fmt(tp2)}\n"
                f"🥉 止盈3 (博弈长线): {fmt(tp3)}\n"
                f"💡 纪律：到达止盈1后，务必将剩余仓位止损推至入场价！"
            )
            
            tg_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            requests.post(tg_url, json={"chat_id": CHAT_ID, "text": message})
            print(f"🔥 发现信号：{signal}，已发送TG！")
        else:
            print(f"👀 未触发：现价 {curr['close']}，当前成交额 {curr['vol']:,.0f}")

    except Exception as e:
        print(f"❌ 出错: {e}")

# GitHub 专用：只执行一次就退出
analyze_market()
