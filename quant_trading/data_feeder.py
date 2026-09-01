import yfinance as yf
import time
import json
import sys
from datetime import datetime
import pytz

# Sector definitions with top constituents
SECTORS = {
    "^NSEBANK": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS"],
    "^CNXIT": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"],
    "^CNXAUTO": ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS"],
    "^CNXPHARMA": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"]
}

def get_vix():
    vix = yf.Ticker("^INDIAVIX")
    data = vix.history(period="1d")
    if data.empty:
        # Fallback to US VIX if India VIX fails to fetch due to Yahoo issues
        vix = yf.Ticker("^VIX")
        data = vix.history(period="1d")
    return data['Close'].iloc[-1] if not data.empty else 0

def get_best_sector():
    best_sector = None
    best_pct_change = -float('inf')
    
    for sector_ticker in SECTORS.keys():
        ticker = yf.Ticker(sector_ticker)
        data = ticker.history(period="2d")
        if len(data) >= 2:
            prev_close = data['Close'].iloc[0]
            curr_close = data['Close'].iloc[1]
            pct_change = ((curr_close - prev_close) / prev_close) * 100
        else:
            pct_change = 0
            
        if pct_change > best_pct_change:
            best_pct_change = pct_change
            best_sector = sector_ticker
            
    return best_sector

def stream_data(tickers):
    # We will simulate a live stream by fetching 1-minute data 
    # and sending the most recent un-sent bar
    last_times = {t: None for t in tickers}
    
    while True:
        for ticker in tickers:
            try:
                data = yf.download(ticker, period="1d", interval="1m", progress=False)
                if not data.empty:
                    latest_bar = data.iloc[-1]
                    # Pandas yfinance returns multi-index columns sometimes, handle both
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
                            "timestamp": int(latest_time)
                        }
                        # Print as JSON for C++ to read via stdin
                        print(json.dumps(msg))
                        sys.stdout.flush()
            except Exception as e:
                # Silently ignore fetch errors and try next time
                pass
                
        time.sleep(5) # Small delay to avoid aggressive rate limiting by Yahoo

if __name__ == "__main__":
    # 1. Check VIX
    current_vix = get_vix()
    msg = {"type": "info", "message": f"Current VIX: {current_vix}"}
    print(json.dumps(msg))
    sys.stdout.flush()
    
    if current_vix >= 20:
        msg = {"type": "info", "message": "VIX is >= 20. Shutting down for the day."}
        print(json.dumps(msg))
        sys.stdout.flush()
        sys.exit(0)
        
    msg = {"type": "info", "message": "VIX is < 20. Proceeding with sector scan."}
    print(json.dumps(msg))
    sys.stdout.flush()

    # 2. Get best sector
    import pandas as pd # Needed for isinstance checks
    best_sector = get_best_sector()
    if not best_sector:
        msg = {"type": "info", "message": "Could not determine best sector. Exiting."}
        print(json.dumps(msg))
        sys.exit(1)
        
    stocks_to_trade = SECTORS[best_sector]
    
    msg = {
        "type": "info", 
        "message": f"Best Sector: {best_sector}. Monitoring stocks: {', '.join(stocks_to_trade)}"
    }
    print(json.dumps(msg))
    sys.stdout.flush()
    
    # 3. Stream data
    stream_data(stocks_to_trade)
