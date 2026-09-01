import csv

def run_backtest():
    # 1. Load data
    file_path = 'C:/Users/swarn_uljk1u7/Downloads/damnn/NIFTY 50-01-09-2025-to-01-09-2026.csv'
    
    rows = []
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        # Clean column names (strip spaces)
        cleaned_fieldnames = [c.strip() for c in reader.fieldnames]
        reader.fieldnames = cleaned_fieldnames
        for row in reader:
            rows.append(row)
            
    # Reverse to chronological order (oldest to newest)
    rows.reverse()
    
    capital = 500000.0
    initial_capital = capital
    position = 0
    entry_price = 0
    highest_price = 0
    
    history_prices = []
    history_volumes = []
    
    with open('C:/Users/swarn_uljk1u7/Downloads/damnn/result1', 'w', encoding='utf-8') as f:
        f.write(f"STARTING BACKTEST - Initial Capital: Rs. {capital}\n")
        f.write("-" * 50 + "\n\n")
        
        for row in rows:
            date = row['Date']
            close = float(row['Close'])
            volume = float(row['Shares Traded'])
            
            # --- RISK MANAGER (SELL LOGIC) ---
            if position > 0:
                highest_price = max(highest_price, close)
                
                hard_stop = entry_price * 0.99
                
                sell_reason = None
                if close <= hard_stop:
                    sell_reason = "HARD STOP LOSS (1%)"
                elif close < highest_price:
                    sell_reason = "MOMENTUM REVERSAL (TRAILING STOP)"
                    
                if sell_reason:
                    revenue = position * close
                    capital += revenue
                    pnl = revenue - (position * entry_price)
                    f.write(f"[{date}] SELL {position} units @ {close:.2f} | Reason: {sell_reason} | PnL: Rs. {pnl:.2f} | Capital: Rs. {capital:.2f}\n\n")
                    position = 0
                    entry_price = 0
                    highest_price = 0
                    
            # --- STRATEGY ENGINE (BUY LOGIC) ---
            # We don't append to history if we are currently holding a position
            if position == 0:
                history_prices.append(close)
                history_volumes.append(volume)
                
                if len(history_prices) > 5:
                    history_prices.pop(0)
                    history_volumes.pop(0)
                    
                if len(history_prices) == 5:
                    first_price = history_prices[0]
                    current_price = history_prices[-1]
                    avg_vol = sum(history_volumes[:-1]) / 4.0
                    current_vol = history_volumes[-1]
                    
                    if avg_vol == 0: avg_vol = 1
                    
                    price_change = (current_price - first_price) / first_price
                    
                    # C++ Logic: Price > 0.05% and Vol > 1.5x average
                    if price_change > 0.0005 and current_vol > (avg_vol * 1.5):
                        f.write(f"[{date}] UNUSUAL MOMENTUM DETECTED | Price Change: {price_change*100:.2f}% | Vol Spike: {current_vol/avg_vol:.2f}x\n")
                        
                        qty = int(capital // current_price)
                        if qty > 0:
                            cost = qty * current_price
                            capital -= cost
                            position = qty
                            entry_price = current_price
                            highest_price = current_price
                            f.write(f"[{date}] BUY {qty} units @ {current_price:.2f} | Cost: Rs. {cost:.2f} | Rem. Capital: Rs. {capital:.2f}\n")
                            
                            # Clear history after buy
                            history_prices.clear()
                            history_volumes.clear()
        
        # Close out any remaining position at end of backtest
        if position > 0:
            final_price = float(rows[-1]['Close'])
            revenue = position * final_price
            capital += revenue
            pnl = revenue - (position * entry_price)
            f.write(f"[{date}] CLOSING OPEN POSITION @ END OF DATA | Price: {final_price:.2f} | PnL: Rs. {pnl:.2f}\n")
            
        f.write("\n" + "=" * 50 + "\n")
        f.write(f"FINAL CAPITAL: Rs. {capital:.2f}\n")
        net_profit = capital - initial_capital
        f.write(f"NET PROFIT: Rs. {net_profit:.2f} ({(net_profit/initial_capital)*100:.2f}%)\n")
        f.write("=" * 50 + "\n")

if __name__ == '__main__':
    run_backtest()
