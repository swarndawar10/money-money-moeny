import os
import json
import sqlite3
import pandas as pd
import numpy as np
import ta
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception:
        pass

DB_PATH = 'nifty500_history.db'
INITIAL_CAPITAL = 500000.0

class V8_Backtester:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.capital = INITIAL_CAPITAL
        self.positions = {}
        self.closed_trades = []
        self.losing_trades_report = []

    def load_symbols(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        return [t for t in tables if t != 'sqlite_sequence']

    def load_stock_data(self, symbol):
        try:
            df = pd.read_sql(f"SELECT * FROM '{symbol}'", self.conn)
            date_cols = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower() or 'timestamp' in c.lower()]
            if date_cols:
                df[date_cols[0]] = pd.to_datetime(df[date_cols[0]])
                df.set_index(date_cols[0], inplace=True)
            df.sort_index(inplace=True)
            return self.add_indicators(df)
        except Exception:
            return None

    def add_indicators(self, df):
        if df is None or len(df) < 50:
            return None
        try:
            df['ATR'] = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], 14).average_true_range()
            df['RSI'] = ta.momentum.RSIIndicator(df['Close'], 14).rsi()
            df['ADX'] = ta.trend.ADXIndicator(df['High'], df['Low'], df['Close'], 14).adx()
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()

            hl2 = (df['High'] + df['Low']) / 2
            basic_ub = hl2 + (3 * df['ATR'])
            basic_lb = hl2 - (3 * df['ATR'])
            
            final_ub = np.zeros(len(df))
            final_lb = np.zeros(len(df))
            st_dir = np.ones(len(df), dtype=bool)
            close = df['Close'].values
            
            for i in range(1, len(df)):
                final_ub[i] = basic_ub.iloc[i] if close[i-1] > final_ub[i-1] else min(basic_ub.iloc[i], final_ub[i-1])
                final_lb[i] = basic_lb.iloc[i] if close[i-1] < final_lb[i-1] else max(basic_lb.iloc[i], final_lb[i-1])
                if close[i] > final_ub[i-1]: st_dir[i] = True
                elif close[i] < final_lb[i-1]: st_dir[i] = False
                else: st_dir[i] = st_dir[i-1]

            df['SuperTrend_Bullish'] = st_dir
            return df
        except Exception:
            return None

    def run_backtest(self):
        symbols = self.load_symbols()
        print(f"📊 Running 8-Year V8 Strategy Backtest on {len(symbols)} Stocks...")

        data_dict = {}
        for sym in symbols:
            df = self.load_stock_data(sym)
            if df is not None and len(df) > 200:
                data_dict[sym] = df

        if not data_dict:
            print("❌ No valid stock data found in Database!")
            return

        all_dates = sorted(list(set().union(*[df.index for df in data_dict.values()])))

        for current_date in all_dates:
            # 1. DEFENSE LOOP (Exits)
            for sym in list(self.positions.keys()):
                pos = self.positions[sym]
                df = data_dict[sym]
                if current_date not in df.index: continue
                
                bar = df.loc[current_date]
                close_price = float(bar['Close'])
                high_price = float(bar['High'])
                low_price = float(bar['Low'])

                # Cost Guard
                if high_price >= (pos['entry_price'] * 1.02) and pos['sl'] < pos['entry_price']:
                    pos['sl'] = pos['entry_price']

                # Trailing Stop Loss
                trail_sl = close_price - (float(bar['ATR']) * 1.5)
                if trail_sl > pos['sl']:
                    pos['sl'] = trail_sl

                # Stop Loss Hit
                if low_price <= pos['sl']:
                    pnl = (pos['sl'] - pos['entry_price']) * pos['qty']
                    self.record_exit(sym, current_date, pos['sl'], pnl, "SL_HIT", bar)
                    del self.positions[sym]
                    continue

                # EMA20 Exit
                if close_price < float(bar['EMA20']):
                    pnl = (close_price - pos['entry_price']) * pos['qty']
                    self.record_exit(sym, current_date, close_price, pnl, "EMA20_BREAK", bar)
                    del self.positions[sym]

            # 2. ATTACK LOOP (Entries)
            if len(self.positions) >= 5: continue

            for sym, df in data_dict.items():
                if len(self.positions) >= 5: break
                if sym in self.positions: continue
                if current_date not in df.index: continue

                idx = df.index.get_loc(current_date)
                if idx < 200: continue

                sub_df = df.iloc[:idx+1]
                completed = sub_df.iloc[-2]
                live = sub_df.iloc[-1]

                c_close, e20, e50, e200 = float(completed['Close']), float(completed['EMA20']), float(completed['EMA50']), float(completed['EMA200'])
                if not (c_close > e20 and e20 > e50 and e50 > e200): continue
                if float(completed['RSI']) < 50: continue
                if float(completed['ADX']) < 20: continue
                if not completed.get('SuperTrend_Bullish', True): continue

                # VCP Filter
                recent_rng = float(sub_df['High'].tail(5).max() - sub_df['Low'].tail(5).min())
                old_rng = float(sub_df['High'].iloc[-20:-5].max() - sub_df['Low'].iloc[-20:-5].min())
                if old_rng > 0 and recent_rng >= (0.85 * old_rng): continue

                # Smart Sizing Entry
                entry_price = float(live['Close'])
                atr = float(completed['ATR'])
                sl_price = entry_price - (atr * 2)
                risk_amount = self.capital * 0.01
                qty = max(1, int(risk_amount / max(1.0, entry_price - sl_price)))

                self.positions[sym] = {
                    'symbol': sym,
                    'entry_date': current_date,
                    'entry_price': entry_price,
                    'qty': qty,
                    'sl': sl_price,
                    'entry_rsi': float(completed['RSI']),
                    'entry_adx': float(completed['ADX']),
                    'vcp_ratio': round(recent_rng / old_rng, 2) if old_rng > 0 else 0
                }

        self.print_summary()

    def record_exit(self, sym, exit_date, exit_price, pnl, reason, bar):
        pos = self.positions[sym]
        trade_record = {
            'symbol': sym,
            'entry_date': str(pos['entry_date'].date()),
            'exit_date': str(exit_date.date()),
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'qty': pos['qty'],
            'pnl': round(pnl, 2),
            'reason': reason,
            'entry_rsi': pos['entry_rsi'],
            'entry_adx': pos['entry_adx'],
            'vcp_ratio': pos['vcp_ratio']
        }
        self.closed_trades.append(trade_record)
        self.capital += pnl

        if pnl < 0:
            self.losing_trades_report.append(trade_record)

    def print_summary(self):
        total_trades = len(self.closed_trades)
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] < 0]
        net_pnl = sum([t['pnl'] for t in self.closed_trades])
        win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0

        print("\n" + "="*50)
        print("📈 BACKTEST PERFORMANCE SUMMARY")
        print("="*50)
        print(f"💰 Final Capital: ₹{self.capital:,.2f} (Start: ₹{INITIAL_CAPITAL:,.2f})")
        print(f"📊 Net P&L: ₹{net_pnl:,.2f}")
        print(f"🔢 Total Trades: {total_trades}")
        print(f"🎯 Win Rate: {win_rate:.2f}% (Wins: {len(wins)} | Losses: {len(losses)})")
        print("="*50)

        if self.losing_trades_report and GEMINI_KEY:
            self.analyze_failures_with_gemini()

    def analyze_failures_with_gemini(self):
        print("\n🤖 Sending Failure Diagnostics to Gemini AI...")
        sample_losses = self.losing_trades_report[:30]
        
        prompt = f"""
You are an expert Quantitative Trading Strategy Optimizer.
Analyze the following sample of LOSING TRADES from my V8 Swing Trading Strategy backtest:

{json.dumps(sample_losses, indent=2)}

Task:
1. Identify common technical patterns where the strategy failed (e.g., RSI levels, ADX, VCP compression ratio).
2. Explain WHY these trades failed (False Breakouts, Market Whipsaws, Loose Stop Loss, etc.).
3. Give me EXACT code/parameter adjustments to reduce these losses without missing good winning trades.
Write the analysis in clear Hindi / Hinglish.
"""
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            print("\n🧠 GEMINI AI STRATEGY OPTIMIZATION REPORT:\n")
            print(response.text)
        except Exception as e:
            print(f"❌ Gemini AI Error: {e}")

if __name__ == "__main__":
    if os.path.exists(DB_PATH):
        bt = V8_Backtester(DB_PATH)
        bt.run_backtest()
    else:
        print(f"❌ Database file {DB_PATH} not found!")