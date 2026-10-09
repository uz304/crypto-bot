import time
import ccxt
import pandas as pd
import numpy as np
import requests
from datetime import datetime

# ==========================================
# ⚙️ TELEGRAM CONFIGURATION
# ==========================================
TELEGRAM_TOKEN = "8898475987:AAFm1acbDHx2x_z1dLIeCVbhr-rZ16TtB_Q"
TELEGRAM_CHAT_ID = "8574090814"

def send_telegram_alert(message):
    if TELEGRAM_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN_HERE" and TELEGRAM_CHAT_ID != "YOUR_TELEGRAM_CHAT_ID_HERE":
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            print(f"Telegram alert error: {e}")

exchange = ccxt.binance({'enableRateLimit': True})

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def fetch_all_usdt_symbols():
    try:
        markets = exchange.load_markets()
        return [
            symbol for symbol, market in markets.items()
            if symbol.endswith('/USDT') and market.get('active', True) 
            and not symbol.endswith('UP/USDT') and not symbol.endswith('DOWN/USDT')
        ]
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return []

def get_ohlcv(symbol, tf, limit=100):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
        return pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'volume'])
    except Exception:
        return pd.DataFrame()

def scan_market():
    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scanning all Binance USDT pairs...")
    symbols = fetch_all_usdt_symbols()
    if not symbols:
        return

    for symbol in symbols:
        try:
            # Fetch 1H & 1D Data
            df_1h = get_ohlcv(symbol, '1h', limit=50)
            if df_1h.empty or len(df_1h) < 20:
                continue

            df_1h['rsi'] = calculate_rsi(df_1h['close'])
            df_1h['ema50'] = df_1h['close'].ewm(span=50, adjust=False).mean()

            # ----------------------------------------------------
            # STRATEGY 1: Trend + RSI 53-55 Cross Below
            # ----------------------------------------------------
            df_1d = get_ohlcv(symbol, '1d', limit=60)
            if not df_1d.empty and len(df_1d) >= 50:
                df_1d['ema50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
                
                # Check Uptrend on 1D and 1H
                cond_1d_uptrend = df_1d['close'].iloc[-1] > df_1d['ema50'].iloc[-1]
                cond_1h_uptrend = df_1h['close'].iloc[-1] > df_1h['ema50'].iloc[-1]
                
                # RSI crossing 53-55 from below
                rsi_curr = df_1h['rsi'].iloc[-1]
                rsi_prev = df_1h['rsi'].iloc[-2]
                cond_rsi_cross = (rsi_prev < 53) and (53 <= rsi_curr <= 55)

                if cond_1d_uptrend and cond_1h_uptrend and cond_rsi_cross:
                    msg = (
                        f"🚨 *STRATEGY 1 MATCHED!*\n\n"
                        f"🪙 *Coin:* {symbol}\n"
                        f"💵 *Price:* ${df_1h['close'].iloc[-1]}\n"
                        f"📊 *Logic:* 1D/1H Uptrend + RSI Cross 53-55 ({round(rsi_curr, 1)})\n"
                        f"⏰ *Timeframe:* 1H"
                    )
                    send_telegram_alert(msg)
                    print(f"--> Strategy 1 Found: {symbol}")

            # ----------------------------------------------------
            # STRATEGY 2: Hidden Bullish Divergence
            # ----------------------------------------------------
            curr_rsi = df_1h['rsi'].iloc[-1]
            curr_price = df_1h['close'].iloc[-1]
            
            past_prices = df_1h['close'].iloc[-15:-2]
            past_rsis = df_1h['rsi'].iloc[-15:-2]
            
            if not past_prices.empty:
                min_past_price = past_prices.min()
                min_past_rsi = past_rsis.min()
                
                cond_rsi_zone = 30 <= curr_rsi <= 40
                cond_price_lower = curr_price < min_past_price
                cond_rsi_higher = curr_rsi > min_past_rsi

                if cond_rsi_zone and cond_price_lower and cond_rsi_higher:
                    msg = (
                        f"🚨 *STRATEGY 2 MATCHED! (Hidden Bullish)*\n\n"
                        f"🪙 *Coin:* {symbol}\n"
                        f"💵 *Price:* ${curr_price}\n"
                        f"📊 *Logic:* RSI 30-40 ({round(curr_rsi, 1)}) + Price Lower Low & RSI Higher Low\n"
                        f"⏰ *Timeframe:* 1H"
                    )
                    send_telegram_alert(msg)
                    print(f"--> Strategy 2 Found: {symbol}")

            # ----------------------------------------------------
            # STRATEGY 3: ICT Order Block / Liquidity Gap Pattern
            # ----------------------------------------------------
            c_curr = df_1h.iloc[-1]  # Last Candle (Green)
            c_prev1 = df_1h.iloc[-2] # Previous Candle (Red)
            
            # Rule A: Last candle Green, before it Red
            is_curr_green = c_curr['close'] > c_curr['open']
            is_prev1_red = c_prev1['close'] < c_prev1['open']

            if is_curr_green and is_prev1_red:
                # Rule B: Find prior Green candle(s) with >1% pump before c_prev1
                for idx in range(3, 10):
                    c_past = df_1h.iloc[-idx]
                    pump_pct = ((c_past['close'] - c_past['open']) / c_past['open']) * 100
                    
                    if c_past['close'] > c_past['open'] and pump_pct > 1.0:
                        # Red candle before that pumped green candle
                        c_past_red = df_1h.iloc[-(idx + 1)]
                        
                        # Rule C: Check body crossing between c_past_red and c_prev1
                        high_level = max(c_past_red['high'], c_prev1['high'])
                        low_level = min(c_past_red['low'], c_prev1['low'])
                        
                        middle_candles = df_1h.iloc[-(idx):-2]
                        no_body_cross = True
                        
                        for _, m_candle in middle_candles.iterrows():
                            body_top = max(m_candle['open'], m_candle['close'])
                            body_bottom = min(m_candle['open'], m_candle['close'])
                            
                            # If middle candles' body breaks outside the zone
                            if body_top > high_level or body_bottom < low_level:
                                no_body_cross = False
                                break
                        
                        if no_body_cross:
                            msg = (
                                f"🚨 *STRATEGY 3 MATCHED! (ICT Pattern)*\n\n"
                                f"🪙 *Coin:* {symbol}\n"
                                f"💵 *Price:* ${c_curr['close']}\n"
                                f"📊 *Logic:* Valid ICT Zone with >1% Green Pump & Clean Body Level\n"
                                f"⏰ *Timeframe:* 1H"
                            )
                            send_telegram_alert(msg)
                            print(f"--> Strategy 3 Found: {symbol}")
                            break

        except Exception as e:
            continue

    print("Scan complete.")

if __name__ == "__main__":
    send_telegram_alert("🤖 *Custom 3-Strategy Crypto Bot Started!* Monitoring 24/7.")
    while True:
        scan_market()
        time.sleep(900)  # Runs every 15 minutes