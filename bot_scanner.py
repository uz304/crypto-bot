import os
import time
import requests
import ccxt
import pandas as pd
import pandas_ta as ta

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")

# Initialize Binance via CCXT
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending alert: {e}")

def fetch_ohlcv_data(symbol, timeframe, limit=100):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA50'] = ta.ema(df['close'], length=50)
        return df
    except Exception:
        return None

# --- STRATEGY 1: Uptrend + RSI Cross & Timeframe Comparison ---
def check_strategy_1(symbol):
    df_1d = fetch_ohlcv_data(symbol, '1d', limit=60)
    df_1h = fetch_ohlcv_data(symbol, '1h', limit=60)
    df_30m = fetch_ohlcv_data(symbol, '30m', limit=60)

    if df_1d is None or df_1h is None or df_30m is None:
        return False, ""

    # Check 1D & 1H Uptrend (Close > EMA50)
    uptrend_1d = df_1d['close'].iloc[-1] > df_1d['EMA50'].iloc[-1]
    uptrend_1h = df_1h['close'].iloc[-1] > df_1h['EMA50'].iloc[-1]

    if not (uptrend_1d and uptrend_1h):
        return False, ""

    rsi_1h_curr = df_1h['RSI'].iloc[-1]
    rsi_1h_prev = df_1h['RSI'].iloc[-2]
    rsi_30m_curr = df_30m['RSI'].iloc[-1]

    # RSI 53 to 55 Crossing Upwards on 1H
    rsi_cross_up = (rsi_1h_prev < 53) and (53 <= rsi_1h_curr <= 55)

    # 30M RSI is 1 to 2 points higher than 1H RSI
    rsi_diff = rsi_30m_curr - rsi_1h_curr
    rsi_diff_valid = 1.0 <= rsi_diff <= 2.0

    if rsi_cross_up and rsi_diff_valid:
        msg = (f"🚀 <b>Strategy #1 Alert: {symbol}</b>\n"
               f"• 1D & 1H in Uptrend\n"
               f"• 1H RSI: {rsi_1h_curr:.2f} (Crossed 53-55)\n"
               f"• 30M RSI: {rsi_30m_curr:.2f} (+{rsi_diff:.2f} points vs 1H)")
        return True, msg

    return False, ""

# --- STRATEGY 2: Hidden Bullish Divergence ---
def check_strategy_2(symbol):
    df = fetch_ohlcv_data(symbol, '1h', limit=50)
    if df is None or len(df) < 30:
        return False, ""

    # Check for lower low in price vs higher low in RSI
    price_low_recent = df['low'].iloc[-5:].min()
    price_low_past = df['low'].iloc[-25:-5].min()

    rsi_low_recent = df['RSI'].iloc[-5:].min()
    rsi_low_past = df['RSI'].iloc[-25:-5].min()

    if (price_low_recent < price_low_past) and (rsi_low_recent > rsi_low_past):
        msg = (f"📈 <b>Strategy #2 Alert: {symbol} (Hidden Bullish Divergence)</b>\n"
               f"• Price is making Lower Lows\n"
               f"• RSI is making Higher Lows ({rsi_low_recent:.2f} vs {rsi_low_past:.2f})")
        return True, msg

    return False, ""

# --- STRATEGY 3: ICT Order Block Gap ---
def check_strategy_3(symbol):
    df = fetch_ohlcv_data(symbol, '1h', limit=20)
    if df is None or len(df) < 5:
        return False, ""

    c0 = df.iloc[-1]  # Current candle (Green)
    c1 = df.iloc[-2]  # Previous candle (Red)
    c2 = df.iloc[-3]  # Candle before Red (Green)

    # 1. Current candle is green, previous is red
    is_c0_green = c0['close'] > c0['open']
    is_c1_red = c1['close'] < c1['open']

    if not (is_c0_green and is_c1_red):
        return False, ""

    # 2. Pumping > 1% on preceding green candle(s)
    green_pumping = ((c2['close'] - c2['open']) / c2['open']) * 100 > 1.0
    if not green_pumping:
        return False, ""

    # 3. Gap check (No body crossing between the order block candles)
    gap_exists = c0['low'] > c2['high']

    if gap_exists:
        msg = (f"🧩 <b>Strategy #3 Alert: {symbol} (ICT Order Block)</b>\n"
               f"• Green reversal following Red OB candle\n"
               f"• Preceding Impulse Move > 1%\n"
               f"• Valid Fair Value Gap (No Body Crossing)")
        return True, msg

    return False, ""

# --- MAIN SCANNER LOOP ---
def run_scanner():
    print("Starting Binance USDT Market Scanner...")
    send_telegram_alert("🤖 <b>Custom 3-Strategy Crypto Bot Active! Scanning all Binance USDT pairs...</b>")

    while True:
        try:
            exchange.load_markets()
            # Fetch all active USDT Spot pairs on Binance
            symbols = [s for s in exchange.symbols if s.endswith('/USDT') and 'BEAR' not in s and 'BULL' not in s]
            print(f"Scanning {len(symbols)} USDT pairs...")

            for symbol in symbols:
                # Strategy 1
                s1, m1 = check_strategy_1(symbol)
                if s1:
                    send_telegram_alert(m1)

                # Strategy 2
                s2, m2 = check_strategy_2(symbol)
                if s2:
                    send_telegram_alert(m2)

                # Strategy 3
                s3, m3 = check_strategy_3(symbol)
                if s3:
                    send_telegram_alert(m3)

                time.sleep(0.1)  # Rate limit safety

            print("Scan cycle completed. Waiting 3 minutes for next iteration...")
            time.sleep(180)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_scanner()
