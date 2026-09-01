import os
import sys
import time
import json
import pytz
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import ta

# Sector definitions with top constituents
SECTORS = {
    "^NSEBANK": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS"],
    "^CNXIT": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],
    "^CNXAUTO": ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS"],
    "^CNXPHARMA": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"]
}

# Load config if available
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
VIX_HIGH_RISK = 22.0
try:
    with open(CONFIG_PATH, 'r') as f:
        cfg = json.load(f)
        VIX_HIGH_RISK = cfg.get("vix_high_risk_threshold", 22.0)
except Exception:
    pass

def log_info(msg):
    print(json.dumps({"type": "info", "message": msg}))
    sys.stdout.flush()

def send_regime(status):
    print(json.dumps({"type": "regime", "status": status}))
    sys.stdout.flush()

def determine_market_regime():
    """
    Evaluates India VIX and Nifty 50 trend.
    No fallback to US VIX. Fail closed if data is missing.
    """
    try:
        # India VIX
        vix = yf.Ticker("^INDIAVIX")
        vix_data = vix.history(period="1d")
        if vix_data.empty:
            log_info("CRITICAL: Failed to fetch India VIX.")
            return "MISSING_DATA"
            
        current_vix = float(vix_data['Close'].iloc[-1])
        
        # Nifty 50 Trend
        nifty = yf.Ticker("^NSEI")
        nifty_data = nifty.history(period="1mo")
        if len(nifty_data) < 20:
            log_info("CRITICAL: Failed to fetch Nifty 50 data.")
            return "MISSING_DATA"
            
        nifty_data['EMA20'] = ta.trend.ema_indicator(nifty_data['Close'], window=20)
        nifty_close = float(nifty_data['Close'].iloc[-1])
        nifty_ema = float(nifty_data['EMA20'].iloc[-1])
        is_uptrend = nifty_close > nifty_ema
        
        log_info(f"India VIX: {current_vix:.2f} | Nifty: {nifty_close:.2f} (EMA20: {nifty_ema:.2f})")
        
        if current_vix >= VIX_HIGH_RISK:
            return "HIGH_RISK"
        elif current_vix >= (VIX_HIGH_RISK * 0.8) and not is_uptrend:
            return "ELEVATED_RISK"
        elif is_uptrend:
            return "LOW_RISK"
        else:
            return "NORMAL"
            
    except Exception as e:
        log_info(f"Exception during market regime evaluation: {e}")
        return "MISSING_DATA"

def get_best_sector():
    """
    Multi-factor sector ranking using 5-day and 1-day momentum.
    """
    best_sector = None
    best_score = -float('inf')
    
    for sector_ticker in SECTORS.keys():
        try:
            ticker = yf.Ticker(sector_ticker)
            data = ticker.history(period="10d")
            if len(data) >= 5:
                close_0 = data['Close'].iloc[-1]
                close_1 = data['Close'].iloc[-2]
                close_5 = data['Close'].iloc[-6]
                
                pct_1d = (close_0 - close_1) / close_1
                pct_5d = (close_0 - close_5) / close_5
                
                # Weight: 60% 5-day, 40% 1-day to prevent whipsaws
                score = (0.6 * pct_5d) + (0.4 * pct_1d)
                log_info(f"Sector {sector_ticker} | 1D: {pct_1d*100:.2f}% | 5D: {pct_5d*100:.2f}% | Score: {score*100:.2f}")
            else:
                score = -float('inf')
        except Exception:
            score = -float('inf')
            
        if score > best_score:
            best_score = score
            best_sector = sector_ticker
            
    return best_sector

def stream_data(tickers):
    log_info("Starting prototype delayed data feeder stream (1m polling)...")
    last_times = {t: None for t in tickers}
    
    while True:
        for ticker in tickers:
            try:
                data = yf.download(ticker, period="1d", interval="1m", progress=False)
                if not data.empty and len(data) > 15:
                    # Calculate ATR (Requires at least 15 bars)
                    atr_series = ta.volatility.average_true_range(data['High'], data['Low'], data['Close'], window=14)
                    latest_atr = float(atr_series.iloc[-1])
                    
                    latest_bar = data.iloc[-1]
                    if isinstance(latest_bar, pd.Series) and isinstance(latest_bar.index, pd.MultiIndex):
                        price = float(latest_bar['Close'].iloc[0])
                        volume = int(latest_bar['Volume'].iloc[0])
                    else:
                        price = float(latest_bar['Close'])
                        volume = int(latest_bar['Volume'])
                        
                    latest_time = data.index[-1].timestamp()
                    
                    if last_times[ticker] != latest_time:
                        last_times[ticker] = latest_time
                        msg = {
                            "type": "trade",
                            "ticker": ticker,
                            "price": price,
                            "volume": volume,
                            "atr": latest_atr if not pd.isna(latest_atr) else (price * 0.01),
                            "timestamp": int(latest_time)
                        }
                        print(json.dumps(msg))
                        sys.stdout.flush()
            except Exception as e:
                pass
                
        time.sleep(10) # Reduced aggression

if __name__ == "__main__":
    # 1. Market Regime
    regime = determine_market_regime()
    send_regime(regime)
    
    if regime in ["HIGH_RISK", "MISSING_DATA", "TRADING_DISABLED"]:
        log_info(f"System idling due to {regime} regime. Exiting feeder.")
        sys.exit(0)
        
    # 2. Sector Selection
    best_sector = get_best_sector()
    if not best_sector:
        log_info("Could not determine best sector. Exiting.")
        sys.exit(1)
        
    stocks_to_trade = SECTORS[best_sector]
    log_info(f"Best Sector: {best_sector}. Monitoring: {', '.join(stocks_to_trade)}")
    
    # 3. Stream
    stream_data(stocks_to_trade)
