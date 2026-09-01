import pandas as pd
import glob
import os
import matplotlib.pyplot as plt

def run_portfolio_backtest():
    folder = 'C:/Users/swarn_uljk1u7/Downloads/damnn/backtester'
    files = glob.glob(os.path.join(folder, '*.xlsx'))
    
    # Process the first 100 files to get a good portfolio sample without taking 10 minutes to load
    files = files[:100]
    print(f"Loading {len(files)} Excel files for portfolio backtest...")
    
    all_data = {}
    for f in files:
        try:
            sym = os.path.basename(f).replace('.xlsx', '').replace('.XLSX', '').upper()
            df = pd.read_excel(f)
            # Find date col
            date_col = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
            if date_col:
                df.rename(columns={date_col[0]: 'Timestamp'}, inplace=True)
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                df.set_index('Timestamp', inplace=True)
                df.sort_index(inplace=True)
                
                # Keep only Close and Volume
                vol_col = [c for c in df.columns if 'vol' in c.lower() or 'share' in c.lower()]
                close_col = [c for c in df.columns if 'close' in c.lower()]
                
                if vol_col and close_col:
                    df['Volume'] = df[vol_col[-1]]
                    df['Close'] = df[close_col[-1]]
                    all_data[sym] = df[['Close', 'Volume']]
        except Exception as e:
            pass
            
    print(f"Successfully loaded {len(all_data)} stocks. Aligning dates...")
    all_dates = set()
    for sym, df in all_data.items():
        all_dates.update(df.index)
    sorted_dates = sorted(list(all_dates))
    
    capital = 500000.0
    initial_capital = capital
    # We allocate 10% of our starting capital to any signal we see, until we run out of cash
    trade_allocation = 50000.0 
    
    positions = {}
    histories = {sym: {'prices': [], 'volumes': []} for sym in all_data.keys()}
    capital_history = []
    
    outcomes = []
    outcomes.append(f"STARTING PORTFOLIO BACKTEST - Initial Capital: Rs. {capital}")
    outcomes.append("-" * 50)
    
    fast_data = {}
    for sym, df in all_data.items():
        fast_data[sym] = df.to_dict('index')
        
    for current_date in sorted_dates:
        daily_portfolio_value = capital
        
        for sym in list(fast_data.keys()):
            if current_date not in fast_data[sym]:
                continue
                
            row = fast_data[sym][current_date]
            close = float(row.get('Close', 0))
            volume = float(row.get('Volume', 0))
            
            if close == 0: continue
            
            # --- RISK MANAGER (SELL LOGIC) ---
            if sym in positions:
                pos = positions[sym]
                pos['highest_price'] = max(pos['highest_price'], close)
                
                hard_stop = pos['entry_price'] * 0.99
                
                sell_reason = None
                if close <= hard_stop:
                    sell_reason = "HARD STOP (1%)"
                elif close < pos['highest_price']:
                    sell_reason = "TRAILING STOP"
                    
                if sell_reason:
                    revenue = pos['qty'] * close
                    capital += revenue
                    pnl = revenue - (pos['qty'] * pos['entry_price'])
                    outcomes.append(f"[{current_date.date()}] SELL {sym:10} | Reason: {sell_reason:20} | PnL: Rs. {pnl:8.2f}")
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
                    
                    if price_change > 0.0005 and current_vol > (avg_vol * 1.5):
                        # Signal! Do we have free capital?
                        if capital >= trade_allocation:
                            qty = int(trade_allocation // current_price)
                            if qty > 0:
                                cost = qty * current_price
                                capital -= cost
                                positions[sym] = {'qty': qty, 'entry_price': current_price, 'highest_price': current_price}
                                outcomes.append(f"[{current_date.date()}] BUY  {sym:10} | Qty: {qty:4} | Cost: Rs. {cost:.2f}")
                                h['prices'].clear()
                                h['volumes'].clear()
                                
        # Calculate daily portfolio value for the graph
        for sym, pos in positions.items():
            if current_date in fast_data[sym]:
                daily_portfolio_value += pos['qty'] * fast_data[sym][current_date]['Close']
                
        capital_history.append((current_date, daily_portfolio_value))

    # Force close all positions at the very end
    for sym, pos in positions.items():
        if len(all_data[sym]) > 0:
            final_price = all_data[sym].iloc[-1]['Close']
            revenue = pos['qty'] * final_price
            capital += revenue
            pnl = revenue - (pos['qty'] * pos['entry_price'])
            outcomes.append(f"[END]        CLOSE {sym:9} | PnL: Rs. {pnl:8.2f}")
            
    outcomes.append("=" * 50)
    outcomes.append(f"FINAL CAPITAL: Rs. {capital:.2f}")
    net_profit = capital - initial_capital
    outcomes.append(f"NET PROFIT: Rs. {net_profit:.2f} ({(net_profit/initial_capital)*100:.2f}%)")
    
    with open('C:/Users/swarn_uljk1u7/Downloads/damnn/outcomes.txt', 'w', encoding='utf-8') as f:
        f.write("\n".join(outcomes))
        
    # Plot graph
    dates = [x[0] for x in capital_history]
    vals = [x[1] for x in capital_history]
    
    plt.figure(figsize=(12, 6))
    plt.plot(dates, vals, label='Portfolio Value (Cash + Stock)', color='#2ca02c', linewidth=2)
    plt.title('Capital Growth: Momentum Strategy (Multi-Stock Allocation)', fontsize=14)
    plt.xlabel('Year', fontsize=12)
    plt.ylabel('Total Capital (Rs)', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend()
    plt.tight_layout()
    plt.savefig('C:/Users/swarn_uljk1u7/Downloads/damnn/capital_graph.png', dpi=150)
    
    print("Backtest finished! outcomes.txt and capital_graph.png created.")

if __name__ == '__main__':
    run_portfolio_backtest()
