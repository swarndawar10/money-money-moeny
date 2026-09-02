import os
import sys
import time
import json
import math
import pytz
from datetime import datetime
import pandas as pd
import numpy as np
import yfinance as yf
import ta

# ──────────────────────────────────────────────────────────────────────────────
# Sector definitions
# Each sector index maps to its constituent stocks and a human-readable label.
# ──────────────────────────────────────────────────────────────────────────────
SECTORS = {
    "^NSEBANK":  {"label": "BANKING",  "stocks": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "AXISBANK.NS", "KOTAKBANK.NS"]},
    "^CNXIT":    {"label": "IT",       "stocks": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS"]},
    "^CNXAUTO":  {"label": "AUTO",     "stocks": ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS"]},
    "^CNXPHARMA":{"label": "PHARMA",   "stocks": ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"]},
}

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
VIX_HIGH_RISK = 22.0
try:
    with open(CONFIG_PATH, 'r') as f:
        _cfg = json.load(f)
        VIX_HIGH_RISK = _cfg.get("vix_high_risk_threshold", 22.0)
except Exception:
    pass  # Use default

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def log_info(msg: str) -> None:
    print(json.dumps({"type": "info", "message": msg}))
    sys.stdout.flush()

def send_regime(status: str) -> None:
    print(json.dumps({"type": "regime", "status": status}))
    sys.stdout.flush()

def _valid_atr(atr_value) -> bool:
    """Return True only if the ATR is a finite, positive number."""
    if atr_value is None:
        return False
    try:
        v = float(atr_value)
        return math.isfinite(v) and v > 0.0
    except (TypeError, ValueError):
        return False

# ──────────────────────────────────────────────────────────────────────────────
# Market regime — FAIL CLOSED if India VIX or Nifty data unavailable.
# No fallback to US VIX. No invented fallback values.
#
# Regime states:
#   LOW_RISK       → VIX low and Nifty in uptrend
#   NORMAL         → VIX moderate and Nifty in uptrend
#   ELEVATED_RISK  → VIX approaching threshold OR Nifty below EMA20
#   HIGH_RISK      → VIX >= threshold
#   MISSING_DATA   → any required data unavailable
# ──────────────────────────────────────────────────────────────────────────────
def determine_market_regime() -> str:
    # ── India VIX ──────────────────────────────────────────────────────────────
    try:
        vix_data = yf.Ticker("^INDIAVIX").history(period="1d")
    except Exception as e:
        log_info(f"CRITICAL: Exception fetching India VIX: {e}")
        return "MISSING_DATA"

    if vix_data is None or vix_data.empty:
        log_info("CRITICAL: India VIX data empty. NOT substituting US VIX.")
        return "MISSING_DATA"

    current_vix = vix_data['Close'].iloc[-1]
    if not math.isfinite(float(current_vix)):
        log_info("CRITICAL: India VIX returned non-finite value.")
        return "MISSING_DATA"
    current_vix = float(current_vix)

    # ── Nifty 50 trend ─────────────────────────────────────────────────────────
    try:
        nifty_data = yf.Ticker("^NSEI").history(period="1mo")
    except Exception as e:
        log_info(f"CRITICAL: Exception fetching Nifty data: {e}")
        return "MISSING_DATA"

    if nifty_data is None or len(nifty_data) < 20:
        log_info("CRITICAL: Insufficient Nifty data (need 20 bars).")
        return "MISSING_DATA"

    nifty_data['EMA20'] = ta.trend.ema_indicator(nifty_data['Close'], window=20)
    nifty_close = float(nifty_data['Close'].iloc[-1])
    nifty_ema   = float(nifty_data['EMA20'].iloc[-1])
    is_uptrend  = nifty_close > nifty_ema

    log_info(f"India VIX: {current_vix:.2f} | Nifty: {nifty_close:.2f} | EMA20: {nifty_ema:.2f} | Uptrend: {is_uptrend}")

    if current_vix >= VIX_HIGH_RISK:
        return "HIGH_RISK"
    if current_vix >= (VIX_HIGH_RISK * 0.8) and not is_uptrend:
        return "ELEVATED_RISK"
    if is_uptrend:
        return "LOW_RISK"
    return "NORMAL"

# ──────────────────────────────────────────────────────────────────────────────
# Sector ranking — short-term momentum ranking.
# Uses 1-day and 5-day momentum. Documented honestly as a simple ranking,
# not a multi-factor institutional model.
#
# If a sector's data cannot be fetched it is assigned a score of -inf and
# effectively excluded.
# ──────────────────────────────────────────────────────────────────────────────
def get_best_sector():
    """
    Short-term sector momentum ranking.
    Score = 0.6 * 5D_return + 0.4 * 1D_return.
    Returns (sector_key, sector_label) or (None, None) on failure.
    """
    best_sector_key   = None
    best_sector_label = None
    best_score        = -float('inf')

    for sector_key, meta in SECTORS.items():
        try:
            data = yf.Ticker(sector_key).history(period="10d")
            if len(data) >= 6:
                c0 = float(data['Close'].iloc[-1])
                c1 = float(data['Close'].iloc[-2])
                c5 = float(data['Close'].iloc[-6])
                if c1 <= 0 or c5 <= 0:
                    score = -float('inf')
                else:
                    pct_1d = (c0 - c1) / c1
                    pct_5d = (c0 - c5) / c5
                    score  = (0.6 * pct_5d) + (0.4 * pct_1d)
                    log_info(f"Sector {sector_key} ({meta['label']}) | 1D: {pct_1d*100:.2f}% | 5D: {pct_5d*100:.2f}% | Score: {score*100:.3f}")
            else:
                score = -float('inf')
                log_info(f"Sector {sector_key}: insufficient data")
        except Exception as e:
            score = -float('inf')
            log_info(f"Sector {sector_key}: fetch error ({e})")

        if score > best_score:
            best_score        = score
            best_sector_key   = sector_key
            best_sector_label = meta['label']

    if best_score == -float('inf'):
        return None, None

    return best_sector_key, best_sector_label

# ──────────────────────────────────────────────────────────────────────────────
# Data stream
#
# NOTE: This feeder uses yfinance 1-minute polling.
# This is a PROTOTYPE / delayed data feed and is NOT suitable for live
# institutional trading. For production use a proper low-latency websocket
# feed from a licensed market data provider (e.g. Kite Connect, Interactive
# Brokers, Bloomberg).
#
# ATR: if ATR is NaN, zero, or not finite, the tick is emitted WITHOUT an atr
# field so the C++ RiskManager will see atr=0 and reject the trade.
# We do NOT substitute price * 0.01 or any invented fallback.
# ──────────────────────────────────────────────────────────────────────────────
def stream_data(tickers: list, sector_label: str) -> None:
    log_info("Starting prototype 1-minute polling feeder. Data is delayed.")
    last_times = {t: None for t in tickers}

    while True:
        for ticker in tickers:
            try:
                data = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=True)
                if data is None or data.empty or len(data) < 15:
                    continue

                # ATR — no fallback: if invalid, skip this tick's atr field
                try:
                    atr_series = ta.volatility.average_true_range(
                        data['High'].squeeze(),
                        data['Low'].squeeze(),
                        data['Close'].squeeze(),
                        window=14
                    )
                    latest_atr_raw = float(atr_series.iloc[-1])
                except Exception:
                    latest_atr_raw = float('nan')

                # Extract price/volume, handling potential MultiIndex columns
                row = data.iloc[-1]
                try:
                    price  = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
                    volume = int(row['Volume'].iloc[0])  if hasattr(row['Volume'], 'iloc') else int(row['Volume'])
                except (KeyError, TypeError, ValueError):
                    continue

                latest_time = data.index[-1].timestamp()
                if last_times[ticker] == latest_time:
                    continue
                last_times[ticker] = latest_time

                msg = {
                    "type":      "trade",
                    "ticker":    ticker,
                    "price":     price,
                    "volume":    volume,
                    "timestamp": int(latest_time),
                    "sector":    sector_label,
                }

                # Only include ATR if it is valid. Missing ATR → C++ rejects trade (fail closed).
                if _valid_atr(latest_atr_raw):
                    msg["atr"] = latest_atr_raw
                else:
                    log_info(f"ATR invalid for {ticker} (value={latest_atr_raw}). Tick emitted without ATR.")

                print(json.dumps(msg))
                sys.stdout.flush()

            except Exception as e:
                log_info(f"Feed error for {ticker}: {e}")

        time.sleep(10)

# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Step 1: Market regime check
    regime = determine_market_regime()
    send_regime(regime)

    if regime in ("HIGH_RISK", "MISSING_DATA", "TRADING_DISABLED"):
        log_info(f"Regime is {regime}. Feeder halting. No new entries will occur.")
        sys.exit(0)

    if regime == "ELEVATED_RISK":
        # Per policy: ELEVATED_RISK → C++ will block entries.
        # Feeder continues streaming so open positions can be managed.
        log_info("Regime is ELEVATED_RISK. Feeder running but C++ engine will block new entries.")

    # Step 2: Sector selection
    sector_key, sector_label = get_best_sector()
    if not sector_key:
        log_info("CRITICAL: Could not determine sector. No sector assigned — exiting feeder.")
        sys.exit(1)

    stocks_to_trade = SECTORS[sector_key]["stocks"]
    log_info(f"Selected sector: {sector_label} ({sector_key}). Monitoring: {', '.join(stocks_to_trade)}")

    # Step 3: Stream
    stream_data(stocks_to_trade, sector_label)
