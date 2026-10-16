
import os
import time
import requests
import ccxt
import pandas as pd
import ta

# Telegram Credentials
TELEGRAM_BOT_TOKEN = "8898475987:AAFm1acbDHx2x_z1dLIeCVbhr-rZ16TtB_Q"
TELEGRAM_CHAT_ID = "8574090814"

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
        df['RSI'] = ta.momentum.rsi(df['close'], window=14)
        df['EMA50'] = ta.trend.ema_indicator(df['close'], window=50)
        return df
    except Exception:
        return None

# --- STRATEGY 1: Trend + Momentum Breakout ---
def check_strategy_1(symbol):
    df_1d = fetch_ohlcv_data(symbol, '1d', limit=50)
    df_1h = fetch_ohlcv_data(symbol, '1h', limit=50)
    df_30m = fetch_ohlcv_data(symbol, '30m', limit=50)

    if df_1d is None or df_1h is None or df_30m is None:
        return False, ""

    uptrend_1d = df_1d['close'].iloc[-1] > df_1d['EMA50'].iloc[-1]
    uptrend_1h = df_1h['close'].iloc[-1] > df_1h['EMA50'].iloc[-1]

    rsi_1h_curr = df_1h['RSI'].iloc[-1]
    rsi_1h_prev = df_1h['RSI'].iloc[-2]
    
    rsi_30m_curr = df_30m['RSI'].iloc[-1]
    rsi_30m_prev = df_30m['RSI'].iloc[-2]

    if uptrend_1d and uptrend_1h:
        if (rsi_1h_prev < 50 <= rsi_1h_curr) or (52 <= rsi_1h_curr <= 58 and rsi_30m_curr > rsi_30m_prev + 1.5):
            msg = (f"🔥 <b>Strategy #1 Alert: {symbol}</b>\n"
                   f"• 1D & 1H Trend: <b>Bullish</b>\n"
                   f"• 1H RSI: {rsi_1h_curr:.2f}\n"
                   f"• 30M RSI Shift: +{rsi_30m_curr - rsi_30m_prev:.2f}")
            return True, msg

    return False, ""

# --- STRATEGY 2: Hidden Bullish Divergence ---
def check_strategy_2(symbol):
    df = fetch_ohlcv_data(symbol, '1h', limit=50)
    if df is None or len(df) < 30:
        return False, ""

    price_low_recent = df['low'].iloc[-6:].min()
    price_low_past = df['low'].iloc[-25:-6].min()

    rsi_low_recent = df['RSI'].iloc[-6:].min()
    rsi_low_past = df['RSI'].iloc[-25:-6].min()

    if (price_low_recent > price_low_past) and (rsi_low_recent < rsi_low_past) and (rsi_low_recent < 45):
        msg = (f"📈 <b>Strategy #2 Alert: {symbol}</b>\n"
               f"• Type: <b>Hidden Bullish Divergence</b>\n"
               f"• Price Higher Low with RSI Reset\n"
               f"• Current RSI: {df['RSI'].iloc[-1]:.2f}")
        return True, msg

    return False, ""

# --- STRATEGY 3: ICT Order Block & Fair Value Gap (1H) ---
def check_strategy_3(symbol):
    df = fetch_ohlcv_data(symbol, '1h', limit=20)
    if df is None or len(df) < 5:
        return False, ""

    c0 = df.iloc[-1]
    c1 = df.iloc[-2]
    c2 = df.iloc[-3]

    is_c0_green = c0['close'] > c0['open']
    is_c1_red = c1['close'] < c1['open']
    
    impulse_percent = ((c2['high'] - c2['low']) / c2['low']) * 100

    if is_c0_green and is_c1_red and impulse_percent >= 0.75:
        if c0['low'] > c2['high']:
            msg = (f"🧩 <b>Strategy #3 Alert: {symbol}</b>\n"
                   f"• Setup: <b>1H ICT Order Block / FVG</b>\n"
                   f"• Impulse Move: {impulse_percent:.2f}%")
            return True, msg

    return False, ""

# --- STRATEGY 4: RSI Oversold at Support ---
def check_strategy_4(symbol):
    df = fetch_ohlcv_data(symbol, '1h', limit=100)
    if df is None or len(df) < 60:
        return False, ""

    current_price = df['close'].iloc[-1]
    current_rsi = df['RSI'].iloc[-1]
    support_level = df['low'].iloc[-60:-3].min()

    is_rsi_oversold = 20 <= current_rsi <= 35
    is_near_support = abs(current_price - support_level) / support_level <= 0.015

    if is_rsi_oversold and is_near_support:
        msg = (f"🎯 <b>Strategy #4 Alert: {symbol}</b>\n"
               f"• Setup: <b>Oversold at Support Zone</b>\n"
               f"• 1H RSI: <b>{current_rsi:.2f}</b>\n"
               f"• Support Level: <code>{support_level}</code>")
        return True, msg

    return False, ""

# --- STRATEGY 5: Multi-Timeframe Order Block (1H + 15m) (NEW) ---
def check_strategy_5(symbol):
    df_1h = fetch_ohlcv_data(symbol, '1h', limit=15)
    df_15m = fetch_ohlcv_data(symbol, '15m', limit=20)

    if df_1h is None or df_15m is None or len(df_1h) < 4 or len(df_15m) < 4:
        return False, ""

    # 1H Order Block structure check
    h_c0 = df_1h.iloc[-1]
    h_c1 = df_1h.iloc[-2]
    h_c2 = df_1h.iloc[-3]
    h_impulse = ((h_c2['high'] - h_c2['low']) / h_c2['low']) * 100
    is_1h_ob = (h_c0['close'] > h_c0['open']) and (h_c1['close'] < h_c1['open']) and (h_impulse >= 0.5) and (h_c0['low'] > h_c2['high'])

    # 15m Order Block confirmation check
    m_c0 = df_15m.iloc[-1]
    m_c1 = df_15m.iloc[-2]
    m_c2 = df_15m.iloc[-3]
    m_impulse = ((m_c2['high'] - m_c2['low']) / m_c2['low']) * 100
    is_15m_ob = (m_c0['close'] > m_c0['open']) and (m_c1['close'] < m_c1['open']) and (m_impulse >= 0.4) and (m_c0['low'] > m_c2['high'])

    if is_1h_ob and is_15m_ob:
        msg = (f"⚡ <b>Strategy #5 Alert: {symbol}</b>\n"
               f"• Setup: <b>Multi-Timeframe Order Block</b>\n"
               f"• Confirmed on both <b>1H & 15m</b> timeframes\n"
               f"• High Probability Reversal Zone")
        return True, msg

    return False, ""

# --- MAIN SCANNER LOOP ---
def run_scanner():
    print("Starting Optimized Binance USDT Market Scanner...")
    send_telegram_alert("🚀 <b>Crypto Scanner Updated! Strategy #5 (1H + 15m Order Block) Added!</b>")

    while True:
        try:
            exchange.load_markets()
            symbols = [s for s in exchange.symbols if s.endswith('/USDT') and 'BEAR' not in s and 'BULL' not in s]
            print(f"Scanning {len(symbols)} USDT pairs...")

            for symbol in symbols:
                s1, m1 = check_strategy_1(symbol)
                if s1: send_telegram_alert(m1)

                s2, m2 = check_strategy_2(symbol)
                if s2: send_telegram_alert(m2)

                s3, m3 = check_strategy_3(symbol)
                if s3: send_telegram_alert(m3)

                s4, m4 = check_strategy_4(symbol)
                if s4: send_telegram_alert(m4)

                s5, m5 = check_strategy_5(symbol)
                if s5: send_telegram_alert(m5)

                time.sleep(0.08)

            print("Scan cycle completed. Waiting 3 minutes...")
            time.sleep(180)

        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    run_scanner()
