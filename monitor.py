import requests

# 填入你的信息
TOKEN = "8611401535:AAFQiAe7UiOYNwQeiEuCnM-iDQo925Aa0Kk"
CHAT_ID = "6293141270"
SYMBOL = "ETHUSDT"

def check_volume():
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={SYMBOL}&interval=1m&limit=10"
        response = requests.get(url).json()
        
        volumes = [float(candle[5]) for candle in response[:-1]]
        avg_volume = sum(volumes) / len(volumes)
        latest_volume = float(response[-1][5])
        current_price = float(response[-1][4])
        
        # 判断异动（放大3倍且大于10000）
        if latest_volume > avg_volume * 3 and latest_volume > 10000:
            message = f"🚨 发现异动！{SYMBOL}\n💰 当前价格: {current_price}\n📊 最新成交量: {latest_volume:.2f}\n📉 平均成交量: {avg_volume:.2f}"
            tg_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            requests.post(tg_url, json={"chat_id": CHAT_ID, "text": message})
            print("警报已发送！")
    except Exception as e:
        print(f"出错: {e}")

check_volume()
