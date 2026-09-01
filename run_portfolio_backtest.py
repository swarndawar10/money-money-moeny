import pandas as pd
import glob
import os
import matplotlib.pyplot as plt
import ta
import json
import numpy as np

def load_config():
    cfg_path = 'C:/Users/swarn_uljk1u7/Downloads/damnn/quant_trading/config.json'
    try:
        with open(cfg_path, 'r') as f:
            return json.load(f)
    except Exception:
        # Defaults
        return {
            "atr_initial_multiplier": 2.0,
            "atr_trailing_multiplier": 2.5,
            "max_risk_per_trade": 0.01,
            "max_portfolio_exposure": 0.50,
            "max_positions": 5,
            "max_daily_loss": 0.03,
            "max_drawdown": 0.10,
            "momentum_threshold": 0.005,
            "volume_multiplier": 1.5
        }

def run_portfolio_backtest():
    cfg = load_config()
    folder = 'C:/Users/swarn_uljk1u7/Downloads/damnn/backtester'
    files = glob.glob(os.path.join(folder, '*.xlsx'))
    
    files = files[:100]
    print(f"Loading {len(files)} Excel files for portfolio backtest...")
    
    all_data = {}
    for f in files:
        try:
            sym = os.path.basename(f).replace('.xlsx', '').replace('.XLSX', '').upper()
            df = pd.read_excel(f)
            
            date_col = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
            if date_col:
                df.rename(columns={date_col[0]: 'Timestamp'}, inplace=True)
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                df.set_index('Timestamp', inplace=True)
                df.sort_index(inplace=True)
                
                vol_col = [c for c in df.columns if 'vol' in c.lower() or 'share' in c.lower()]
                close_col = [c for c in df.columns if 'close' in c.lower()]
                high_col = [c for c in df.columns if 'high' in c.lower()]
                low_col = [c for c in df.columns if 'low' in c.lower()]
                
                if vol_col and close_col and high_col and low_col:
                    df['Volume'] = df[vol_col[-1]]
                    df['Close'] = df[close_col[-1]]
                    df['High'] = df[high_col[-1]]
                    df['Low'] = df[low_col[-1]]
                    
                    if len(df) > 15:
                        # SHIFT ATR to avoid look-ahead bias (using yesterday's ATR for today's decisions)
                        atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)
                        df['ATR'] = atr.shift(1).fillna(df['Close'] * 0.01)
                        all_data[sym] = df[['Close', 'Volume', 'ATR']]
        except Exception:
            pass
            
    print(f"Successfully loaded {len(all_data)} stocks. Aligning dates...")
    all_dates = set()
    for sym, df in all_data.items():
        all_dates.update(df.index)
    sorted_dates = sorted(list(all_dates))
    
    initial_capital = 500000.0
    capital = initial_capital
    peak_capital = capital
    daily_starting_capital = capital
    trading_enabled = True
    
    positions = {}
    histories = {sym: {'prices': [], 'volumes': []} for sym in all_data.keys()}
    capital_history = []
    
    outcomes = []
    outcomes.append(f"STARTING RISK-FIRST BACKTEST - Initial Capital: Rs. {capital}")
    outcomes.append("-" * 50)
    
    fast_data = {}
    for sym, df in all_data.items():
        fast_data[sym] = df.to_dict('index')
        
    closed_trades = []

    last_date = None
    for current_date in sorted_dates:
        # Check if new day for Daily Loss Limit reset
        if last_date is None or current_date.date() != last_date.date():
            daily_starting_capital = capital
            if capital > peak_capital * (1.0 - cfg['max_drawdown']):
                trading_enabled = True
        last_date = current_date
        
        daily_portfolio_value = capital
        
        # 1. Circuit Breakers
        if capital <= peak_capital * (1.0 - cfg['max_drawdown']):
            if trading_enabled:
                outcomes.append(f"[{current_date.date()}] 🚨 CIRCUIT BREAKER TRIPPED! Max DD exceeded.")
                trading_enabled = False
                
        if capital <= daily_starting_capital * (1.0 - cfg['max_daily_loss']):
            if trading_enabled:
                outcomes.append(f"[{current_date.date()}] 🚨 DAILY LOSS LIMIT HIT! Trading Disabled.")
                trading_enabled = False
        
        for sym in list(fast_data.keys()):
            if current_date not in fast_data[sym]:
                continue
                
            row = fast_data[sym][current_date]
            close = float(row.get('Close', 0))
            volume = float(row.get('Volume', 0))
            atr = float(row.get('ATR', close * 0.01))
            
            if close == 0: continue
            
            # --- RISK MANAGER (SELL LOGIC) ---
            if sym in positions:
                pos = positions[sym]
                pos['highest_price'] = max(pos['highest_price'], close)
                
                trailing_stop = pos['highest_price'] - (atr * cfg['atr_trailing_multiplier'])
                effective_stop = max(pos['initial_stop'], trailing_stop)
                
                sell_reason = None
                if close <= effective_stop:
                    sell_reason = "INITIAL_STOP" if effective_stop == pos['initial_stop'] else "TRAILING_STOP"
                    
                if sell_reason:
                    revenue = pos['qty'] * close
                    capital += revenue
                    if capital > peak_capital: peak_capital = capital
                    
                    pnl = revenue - (pos['qty'] * pos['entry_price'])
                    outcomes.append(f"[{current_date.date()}] SELL {sym:10} | Reason: {sell_reason:15} | PnL: Rs. {pnl:8.2f}")
                    closed_trades.append(pnl)
                    del positions[sym]
                    
            # --- STRATEGY ENGINE (BUY LOGIC) ---
            if sym not in positions:
                h = histories[sym]
                h['prices'].append(close)
                h['volumes'].append(volume)
                
                if len(h['prices']) > 5:
                    h['prices'].pop(0)
                    h['volumes'].pop(0)
                    
                if len(h['prices']) == 5:
                    first_price = h['prices'][0]
                    current_price = h['prices'][-1]
                    avg_vol = sum(h['volumes'][:-1]) / 4.0
                    current_vol = h['volumes'][-1]
                    if avg_vol == 0: avg_vol = 1
                    
                    price_change = (current_price - first_price) / first_price
                    
                    if price_change > cfg['momentum_threshold'] and current_vol > (avg_vol * cfg['volume_multiplier']):
                        # Risk Manager Approval
                        if not trading_enabled:
                            continue
                            
                        if len(positions) >= cfg['max_positions']:
                            continue
                            
                        stop_distance = atr * cfg['atr_initial_multiplier']
                        if stop_distance <= 0: stop_distance = 0.01 * current_price
                        
                        risk_amount = capital * cfg['max_risk_per_trade']
                        qty = int(risk_amount // stop_distance)
                        
                        if qty > 0:
                            cost = qty * current_price
                            # Cap by Portfolio Exposure
                            if cost > capital * cfg['max_portfolio_exposure']:
                                qty = int((capital * cfg['max_portfolio_exposure']) // current_price)
                                cost = qty * current_price
                                
                            if qty > 0 and cost <= capital:
                                capital -= cost
                                initial_stop = current_price - stop_distance
                                positions[sym] = {
                                    'qty': qty, 
                                    'entry_price': current_price, 
                                    'highest_price': current_price,
                                    'initial_stop': initial_stop
                                }
                                outcomes.append(f"[{current_date.date()}] BUY  {sym:10} | Qty: {qty:4} | Cost: Rs. {cost:.2f} | Risk: {risk_amount:.2f}")
                                
        # Daily Portfolio Value
        for sym, pos in positions.items():
            if current_date in fast_data[sym]:
                daily_portfolio_value += pos['qty'] * fast_data[sym][current_date]['Close']
                
        capital_history.append((current_date, daily_portfolio_value))

    # Force close at end
    for sym, pos in positions.items():
        if len(all_data[sym]) > 0:
            final_price = all_data[sym].iloc[-1]['Close']
            revenue = pos['qty'] * final_price
            capital += revenue
            pnl = revenue - (pos['qty'] * pos['entry_price'])
            closed_trades.append(pnl)
            outcomes.append(f"[END]        CLOSE {sym:9} | PnL: Rs. {pnl:8.2f}")
            
    outcomes.append("=" * 50)
    
    # Calculate Institutional Metrics
    net_profit = capital - initial_capital
    return_pct = (net_profit / initial_capital) * 100
    
    # Max Drawdown
    peak = initial_capital
    max_dd = 0.0
    for _, val in capital_history:
        if val > peak: peak = val
        dd = (peak - val) / peak
        if dd > max_dd: max_dd = dd
        
    # Trade Stats
    wins = [t for t in closed_trades if t > 0]
    losses = [t for t in closed_trades if t <= 0]
    win_rate = (len(wins) / len(closed_trades) * 100) if closed_trades else 0
    profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')
    avg_trade = np.mean(closed_trades) if closed_trades else 0
    largest_loss = min(losses) if losses else 0
    largest_win = max(wins) if wins else 0

    outcomes.append(f"FINAL CAPITAL: Rs. {capital:.2f}")
    outcomes.append(f"NET PROFIT: Rs. {net_profit:.2f} ({return_pct:.2f}%)")
    outcomes.append(f"MAX DRAWDOWN: {max_dd*100:.2f}%")
    outcomes.append(f"TOTAL TRADES: {len(closed_trades)}")
    outcomes.append(f"WIN RATE: {win_rate:.2f}%")
    outcomes.append(f"PROFIT FACTOR: {profit_factor:.2f}")
    outcomes.append(f"AVERAGE TRADE: Rs. {avg_trade:.2f}")
    outcomes.append(f"LARGEST WIN: Rs. {largest_win:.2f}")
    outcomes.append(f"LARGEST LOSS: Rs. {largest_loss:.2f}")
    
    with open('C:/Users/swarn_uljk1u7/Downloads/damnn/outcome2.txt', 'w', encoding='utf-8') as f:
        f.write("\n".join(outcomes))
    with open('C:/Users/swarn_uljk1u7/Downloads/damnn/outcome2', 'w', encoding='utf-8') as f:
        f.write("\n".join(outcomes))
        
    dates = [x[0] for x in capital_history]
    vals = [x[1] for x in capital_history]
    
    plt.figure(figsize=(12, 6))
    plt.plot(dates, vals, label='Portfolio Value', color='#d62728', linewidth=2)
    plt.title(f'Risk-First Momentum Strategy (Max DD: {max_dd*100:.2f}%)', fontsize=14)
    plt.xlabel('Year', fontsize=12)
    plt.ylabel('Total Capital (Rs)', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('C:/Users/swarn_uljk1u7/Downloads/damnn/capital_graph_v2.png', dpi=150)
    
    print("Risk-First Backtest finished! outcome2.txt and capital_graph_v2.png created.")

if __name__ == '__main__':
    run_portfolio_backtest()
