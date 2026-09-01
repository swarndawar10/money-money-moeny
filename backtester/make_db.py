import os, glob, sqlite3, pandas as pd

conn = sqlite3.connect('nifty500_history.db')
files = glob.glob('**/*.csv', recursive=True)
print(f'📁 Total CSV files found: {len(files)}')

for f in files:
    try:
        symbol = os.path.basename(f).replace('.csv', '').replace('.CSV', '').upper()
        df = pd.read_csv(f)
        
        # Date column fix
        date_col = [c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()]
        if date_col:
            df.rename(columns={date_col[0]: 'Timestamp'}, inplace=True)
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df.set_index('Timestamp', inplace=True)
            df.sort_index(inplace=True)
            df.to_sql(symbol, conn, if_exists='replace')
            print(f'✅ Processed: {symbol}')
    except Exception as e:
        pass

print('🚀 Database nifty500_history.db is READY!')