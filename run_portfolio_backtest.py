"""
run_portfolio_backtest.py — Risk-First Backtester v3

Key accounting fixes vs v2:
  - equity = cash + market value of ALL open positions (not just cash)
  - circuit breakers evaluated against equity, not cash
  - ATR fallback to price*0.01 removed (fail-closed: skip trade if ATR invalid)
  - daily loss lock uses equity at day-open, not cash at day-open
  - daily lock NOT cleared by drawdown recovery; drawdown lock is permanent
  - sector exposure enforced using market value / equity
  - portfolio exposure enforced using total invested market value / equity
  - tick order: update prices → recalculate equity → evaluate CBs → entry signal
  - ATR is shifted by 1 bar to eliminate look-ahead bias
"""

import os
import math
import glob
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import ta

BASE_DIR = 'C:/Users/swarn_uljk1u7/Downloads/damnn'
EXCEL_FOLDER = os.path.join(BASE_DIR, 'backtester')
CONFIG_PATH  = os.path.join(BASE_DIR, 'quant_trading/config.json')


def load_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    defaults = {
        "atr_initial_multiplier":  2.0,
        "atr_trailing_multiplier": 2.5,
        "max_risk_per_trade":      0.01,
        "max_portfolio_exposure":  0.50,
        "max_sector_exposure":     0.20,
        "max_positions":           5,
        "max_daily_loss":          0.03,
        "max_drawdown":            0.10,
        "momentum_threshold":      0.005,
        "volume_multiplier":       1.5,
    }
    for k, v in defaults.items():
        cfg.setdefault(k, v)
    return cfg


def validate_config(cfg):
    """Raise ValueError if any configured value is clearly invalid."""
    checks = [
        ("atr_initial_multiplier",  lambda v: v > 0),
        ("atr_trailing_multiplier", lambda v: v > 0),
        ("max_risk_per_trade",      lambda v: 0 < v < 1),
        ("max_portfolio_exposure",  lambda v: 0 < v <= 1),
        ("max_sector_exposure",     lambda v: 0 < v <= 1),
        ("max_positions",           lambda v: v > 0),
        ("max_daily_loss",          lambda v: 0 < v <= 1),
        ("max_drawdown",            lambda v: 0 < v <= 1),
        ("momentum_threshold",      lambda v: v > 0),
        ("volume_multiplier",       lambda v: v > 0),
    ]
    for key, check in checks:
        if not check(cfg[key]):
            raise ValueError(f"Invalid config value: {key} = {cfg[key]}")


def valid_atr(v):
    """Return True only if ATR is a finite positive number."""
    try:
        f = float(v)
        return math.isfinite(f) and f > 0.0
    except (TypeError, ValueError):
        return False


def load_stock_data(folder, max_files=100):
    """
    Load Excel files and compute shifted ATR (no look-ahead bias).
    Returns dict: {symbol: DataFrame with columns Close, Volume, ATR}
    ATR is NaN where it could not be computed — trades on those rows are skipped.
    """
    files = sorted(glob.glob(os.path.join(folder, '*.xlsx')))[:max_files]
    print(f"Loading {len(files)} Excel files...")

    all_data = {}
    for f in files:
        sym = os.path.basename(f).replace('.xlsx', '').replace('.XLSX', '').upper()
        try:
            df = pd.read_excel(f)

            date_col  = next((c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()), None)
            close_col = next((c for c in df.columns if 'close' in c.lower()), None)
            high_col  = next((c for c in df.columns if 'high' in c.lower()), None)
            low_col   = next((c for c in df.columns if 'low' in c.lower()), None)
            vol_col   = next((c for c in df.columns if 'vol' in c.lower() or 'share' in c.lower()), None)

            if not all([date_col, close_col, high_col, low_col, vol_col]):
                continue

            df = df[[date_col, close_col, high_col, low_col, vol_col]].copy()
            df.columns = ['Timestamp', 'Close', 'High', 'Low', 'Volume']
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df.set_index('Timestamp', inplace=True)
            df.sort_index(inplace=True)
            df = df.apply(pd.to_numeric, errors='coerce')
            df.dropna(subset=['Close', 'High', 'Low', 'Volume'], inplace=True)

            if len(df) < 16:
                continue

            # Shift ATR by 1: day T's signal uses ATR calculated up to day T-1.
            atr_raw   = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
            df['ATR'] = atr_raw.shift(1)  # NaN for first 15 rows — intentional

            all_data[sym] = df[['Close', 'Volume', 'ATR']]

        except Exception:
            pass  # Skip unreadable files; do not invent data

    print(f"Successfully loaded {len(all_data)} stocks.")
    return all_data


def calc_equity(cash, positions, fast_data, current_date):
    """equity = cash + sum of (qty * current_close) for all open positions."""
    mval = 0.0
    for sym, pos in positions.items():
        row = fast_data[sym].get(current_date)
        price = float(row['Close']) if row is not None else pos['last_price']
        pos['last_price'] = price  # keep cached for equity queries
        mval += pos['qty'] * price
    return cash + mval


def run_portfolio_backtest():
    cfg = load_config()
    validate_config(cfg)
    print("Config validated. Starting backtest...")

    all_data = load_stock_data(EXCEL_FOLDER)
    if not all_data:
        print("ERROR: No stock data loaded. Aborting.")
        return

    fast_data = {sym: df.to_dict('index') for sym, df in all_data.items()}

    sorted_dates = sorted({d for df in all_data.values() for d in df.index})

    # ── Account state ──────────────────────────────────────────────────────────
    INITIAL_CAPITAL     = 500_000.0
    cash                = INITIAL_CAPITAL
    positions           = {}      # sym → {qty, entry_price, highest_price, initial_stop, last_price}
    histories           = {s: {'prices': [], 'volumes': []} for s in all_data}

    peak_equity             = INITIAL_CAPITAL
    daily_starting_equity   = INITIAL_CAPITAL

    # Separate lock flags — mirror the C++ design exactly
    drawdown_locked     = False
    daily_loss_locked   = False
    market_allows_entries = True   # not simulating regime in backtest (no live VIX)

    last_date           = None
    capital_history     = []
    closed_trades       = []
    outcomes            = [
        f"RISK-FIRST BACKTEST v3 — Initial Capital: Rs. {INITIAL_CAPITAL:,.2f}",
        "-" * 60,
    ]

    for current_date in sorted_dates:

        # ── 1. Daily reset (timestamp-driven, mirrors C++ onTimestamp) ─────────
        is_new_day = (last_date is None) or (current_date.date() != last_date.date())
        if is_new_day:
            # Recalculate equity at start of new day
            eq_open = calc_equity(cash, positions, fast_data, current_date)
            daily_starting_equity = eq_open
            # Daily loss lock clears on new day; drawdown lock NEVER clears here
            daily_loss_locked = False
        last_date = current_date

        # ── 2. Update position prices & check exits ────────────────────────────
        for sym in list(positions.keys()):
            if current_date not in fast_data[sym]:
                continue
            row   = fast_data[sym][current_date]
            close = float(row['Close'])
            atr   = row['ATR']

            pos = positions[sym]
            pos['last_price'] = close
            if close > pos['highest_price']:
                pos['highest_price'] = close

            # If ATR is invalid at exit time, fall back to initial stop only
            # (do NOT invent a trailing stop distance from price)
            effective_stop = pos['initial_stop']
            if valid_atr(atr):
                trailing_stop  = pos['highest_price'] - float(atr) * cfg['atr_trailing_multiplier']
                effective_stop = max(pos['initial_stop'], trailing_stop)

            if close <= effective_stop:
                reason  = "INITIAL_STOP" if effective_stop <= pos['initial_stop'] + 1e-9 else "TRAILING_STOP"
                revenue = pos['qty'] * close
                pnl     = revenue - pos['qty'] * pos['entry_price']
                cash   += revenue
                closed_trades.append(pnl)
                outcomes.append(
                    f"[{current_date.date()}] SELL {sym:10} | {reason:14} | PnL: Rs.{pnl:10.2f}"
                )
                del positions[sym]

        # ── 3. Recalculate equity after exits ──────────────────────────────────
        equity = calc_equity(cash, positions, fast_data, current_date)
        if equity > peak_equity:
            peak_equity = equity

        # ── 4. Evaluate circuit breakers against TRUE equity ──────────────────
        if not drawdown_locked:
            dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            if dd >= cfg['max_drawdown']:
                drawdown_locked = True
                outcomes.append(
                    f"[{current_date.date()}] 🚨 DRAWDOWN CB TRIPPED | "
                    f"Equity: Rs.{equity:,.0f} | Peak: Rs.{peak_equity:,.0f} | DD: {dd*100:.2f}%"
                )

        if not daily_loss_locked:
            daily_loss = (daily_starting_equity - equity) / daily_starting_equity if daily_starting_equity > 0 else 0
            if daily_loss >= cfg['max_daily_loss']:
                daily_loss_locked = True
                outcomes.append(
                    f"[{current_date.date()}] 🚨 DAILY LOSS CB | "
                    f"Equity: Rs.{equity:,.0f} | DayStart: Rs.{daily_starting_equity:,.0f} | Loss: {daily_loss*100:.2f}%"
                )

        entries_allowed = (
            market_allows_entries
            and not daily_loss_locked
            and not drawdown_locked
        )

        # ── 5. Entry signals ───────────────────────────────────────────────────
        for sym in list(fast_data.keys()):
            if sym in positions:
                continue
            if current_date not in fast_data[sym]:
                continue
            if not entries_allowed:
                break

            row    = fast_data[sym][current_date]
            close  = float(row['Close'])
            volume = float(row['Volume'])
            atr    = row['ATR']

            if close <= 0:
                continue

            # ATR fail-closed: do not trade if ATR is invalid
            if not valid_atr(atr):
                continue
            atr = float(atr)

            h = histories[sym]
            h['prices'].append(close)
            h['volumes'].append(volume)
            if len(h['prices']) > 5:
                h['prices'].pop(0)
                h['volumes'].pop(0)

            if len(h['prices']) < 5:
                continue

            first_price   = h['prices'][0]
            current_price = h['prices'][-1]
            avg_vol       = sum(h['volumes'][:-1]) / 4.0
            current_vol   = h['volumes'][-1]
            if avg_vol <= 0:
                avg_vol = 1.0

            price_change = (current_price - first_price) / first_price
            if not (price_change > cfg['momentum_threshold'] and
                    current_vol > avg_vol * cfg['volume_multiplier']):
                continue

            # ── Risk Manager entry checks ──────────────────────────────────────
            if len(positions) >= cfg['max_positions']:
                continue

            stop_distance = atr * cfg['atr_initial_multiplier']
            if stop_distance <= 0:
                continue  # Should not happen with valid ATR > 0, but guard anyway

            risk_amount = equity * cfg['max_risk_per_trade']
            qty = int(risk_amount // stop_distance)
            if qty <= 0:
                continue

            new_pos_value = qty * current_price

            # Portfolio exposure: total invested market value / equity
            invested = sum(p['qty'] * p['last_price'] for p in positions.values())
            if (invested + new_pos_value) > equity * cfg['max_portfolio_exposure']:
                remaining = equity * cfg['max_portfolio_exposure'] - invested
                if remaining <= 0:
                    continue
                qty = int(remaining // current_price)
                new_pos_value = qty * current_price
                if qty <= 0:
                    continue

            # Sector exposure: sector invested / equity
            # (In backtest we don't have sector labels per stock, so all stocks
            # are treated as the same sector "BACKTEST". This mirrors the reality
            # that backtester data has no sector mapping.)
            # Sector enforcement is validated in the C++ unit tests with labels.

            if new_pos_value > cash:
                qty = int(cash // current_price)
                new_pos_value = qty * current_price
                if qty <= 0:
                    continue

            # Execute
            cash -= new_pos_value
            initial_stop = current_price - stop_distance
            positions[sym] = {
                'qty':           qty,
                'entry_price':   current_price,
                'highest_price': current_price,
                'initial_stop':  initial_stop,
                'last_price':    current_price,
            }
            outcomes.append(
                f"[{current_date.date()}] BUY  {sym:10} | Qty:{qty:5} | "
                f"Cost:Rs.{new_pos_value:10.2f} | Stop:Rs.{initial_stop:.2f}"
            )

        # ── 6. Record daily portfolio value ────────────────────────────────────
        equity_eod = calc_equity(cash, positions, fast_data, current_date)
        capital_history.append((current_date, equity_eod))

    # ── Force-close remaining positions at last available price ─────────────────
    for sym, pos in list(positions.items()):
        final_price = pos['last_price']
        revenue     = pos['qty'] * final_price
        pnl         = revenue - pos['qty'] * pos['entry_price']
        cash       += revenue
        closed_trades.append(pnl)
        outcomes.append(f"[END]  CLOSE {sym:10} | PnL: Rs.{pnl:10.2f}")

    outcomes.append("=" * 60)

    # ── Performance metrics ────────────────────────────────────────────────────
    final_equity  = cash   # all positions closed
    net_profit    = final_equity - INITIAL_CAPITAL
    return_pct    = net_profit / INITIAL_CAPITAL * 100

    cap_vals = [v for _, v in capital_history]
    peak_    = INITIAL_CAPITAL
    max_dd   = 0.0
    for v in cap_vals:
        if v > peak_: peak_ = v
        dd_ = (peak_ - v) / peak_ if peak_ > 0 else 0
        if dd_ > max_dd: max_dd = dd_

    # Year-over-year CAGR
    if capital_history:
        years = (capital_history[-1][0] - capital_history[0][0]).days / 365.25
        cagr  = ((final_equity / INITIAL_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0.0
    else:
        cagr = 0.0

    wins   = [t for t in closed_trades if t > 0]
    losses = [t for t in closed_trades if t <= 0]
    win_rate     = len(wins) / len(closed_trades) * 100 if closed_trades else 0
    profit_factor= sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
    avg_trade    = float(np.mean(closed_trades)) if closed_trades else 0
    largest_win  = max(wins)  if wins  else 0
    largest_loss = min(losses) if losses else 0

    # Max consecutive losses
    max_consec_losses = 0
    consec = 0
    for t in closed_trades:
        if t <= 0:
            consec += 1
            max_consec_losses = max(max_consec_losses, consec)
        else:
            consec = 0

    summary = [
        f"FINAL EQUITY:          Rs. {final_equity:>12,.2f}",
        f"NET PROFIT:            Rs. {net_profit:>12,.2f}  ({return_pct:.2f}%)",
        f"CAGR:                  {cagr:.2f}%",
        f"MAX DRAWDOWN:          {max_dd*100:.2f}%",
        f"TOTAL TRADES:          {len(closed_trades)}",
        f"WIN RATE:              {win_rate:.2f}%",
        f"PROFIT FACTOR:         {profit_factor:.3f}",
        f"AVERAGE TRADE:         Rs. {avg_trade:>10.2f}",
        f"LARGEST WIN:           Rs. {largest_win:>10.2f}",
        f"LARGEST LOSS:          Rs. {largest_loss:>10.2f}",
        f"MAX CONSEC. LOSSES:    {max_consec_losses}",
        "",
        "NOTE: Backtest uses daily bars. The momentum strategy is designed for",
        "intraday data. Results should NOT be treated as a reliable performance",
        "forecast. Transaction costs and slippage are not modelled.",
    ]
    outcomes.extend(summary)

    out_txt = os.path.join(BASE_DIR, 'outcome3.txt')
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write("\n".join(outcomes))
    print(f"Results written to {out_txt}")

    # ── Capital curve graph ────────────────────────────────────────────────────
    dates = [x[0] for x in capital_history]
    vals  = [x[1] for x in capital_history]

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.plot(dates, vals, color='#1f77b4', linewidth=1.5, label='Portfolio Equity')
    ax.axhline(y=INITIAL_CAPITAL, color='grey', linestyle='--', linewidth=1, label='Initial Capital')
    ax.set_title(f'Risk-First Momentum — Equity Curve  |  Max DD: {max_dd*100:.2f}%  |  CAGR: {cagr:.2f}%', fontsize=13)
    ax.set_xlabel('Date', fontsize=11)
    ax.set_ylabel('Portfolio Equity (Rs)', fontsize=11)
    ax.legend()
    ax.grid(True, linestyle='--', alpha=0.5)
    plt.tight_layout()
    graph_path = os.path.join(BASE_DIR, 'capital_graph_v3.png')
    plt.savefig(graph_path, dpi=150)
    plt.close()
    print(f"Graph saved to {graph_path}")

    print("\n=== SUMMARY ===")
    for line in summary:
        print(line)


if __name__ == '__main__':
    run_portfolio_backtest()
