import yfinance as yf
import pandas as pd
import numpy as np
import ta
import joblib
import os, json
from datetime import datetime
import matplotlib.pyplot as plt
from pathlib import Path
import argparse

# ---------------- CONFIG ----------------
SYMBOLS = ['BTC-USD', 'GALA-USD', 'XRP-USD']
INTERVAL = '30m'
PERIOD = '60d'
HORIZON = 3  # bars ahead for labeling (if training)
MODEL_FILE = 'crypto_ai_model.pkl'
SIGNAL_FILE = 'signals.txt'
LAST_SIGNALS_FILE = 'last_signals.json'
OUT_STATS = 'backtest_stats.csv'
ATR_WINDOW = 14
ATR_MULTIPLIER = 1.5
# ----------------------------------------

def build_features(df):
    df = df.copy()
    df['rsi'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd = ta.trend.MACD(df['Close'])
    df['macd'] = macd.macd()
    bb = ta.volatility.BollingerBands(df['Close'])
    df['bb_mid'] = bb.bollinger_mavg()
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()
    df['bb_width'] = (df['bb_high'] - df['bb_low']) / df['bb_mid']
    df['percent_b'] = (df['Close'] - df['bb_low']) / (df['bb_high'] - df['bb_low'])
    df['volume_change'] = df['Volume'].pct_change().fillna(0)
    # ATR
    atr = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=ATR_WINDOW)
    df['ATR'] = atr.average_true_range()
    # Candlestick heuristics
    o = df['Open']; h = df['High']; l = df['Low']; c = df['Close']
    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l
    df['shooting_star'] = (((body <= 0.3*candle_range) & (upper_shadow >= 2*body) & (lower_shadow <= 0.2*body)).fillna(0)).astype(int)
    df['hammer'] = (((body <= 0.3*candle_range) & (lower_shadow >= 2*body) & (upper_shadow <= 0.2*body)).fillna(0)).astype(int)
    return df.dropna()

def load_last_signals():
    p = Path(LAST_SIGNALS_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}

def save_last_signals(d):
    Path(LAST_SIGNALS_FILE).write_text(json.dumps(d, indent=2))

def ensure_model(train_df=None):
    if os.path.exists(MODEL_FILE):
        print('Loading existing model:', MODEL_FILE)
        try:
            return joblib.load(MODEL_FILE)
        except Exception as e:
            print('Failed to load model:', e)
    # If no model, train a quick RandomForest on provided train_df as fallback
    print('No model found or failed to load. Training a lightweight fallback model if data available...')
    from sklearn.ensemble import RandomForestClassifier
    df = train_df.copy() if train_df is not None else None
    if df is None or df.empty:
        print('No training data; using dummy approver.')
        class Dummy:
            def predict(self, X): return np.ones(len(X), dtype=int)
        return Dummy()
    # label: future return > 0.2%
    df['future_return'] = df['Close'].shift(-HORIZON) / df['Close'] - 1
    df = df.dropna()
    df['label'] = (df['future_return'] > 0.002).astype(int)
    feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
    X = df[feature_cols].fillna(0)
    y = df['label']
    if len(X) < 50:
        print('Not enough data to train fallback model; using constant approve (1)')
        class Dummy:
            def predict(self, X): return np.ones(len(X), dtype=int)
        return Dummy()
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)
    print('Fallback model trained and saved as', MODEL_FILE)
    return model

def analyze_and_backtest(test_mode=False):
    all_stats = []
    model = None
    btc_df_for_train = None
    last_signals = load_last_signals()
    new_signals = []

    for sym in SYMBOLS:
        print('Downloading', sym)
        df = yf.download(sym, period=PERIOD, interval=INTERVAL, progress=False).dropna()
        if df.empty:
            print('No data for', sym); continue
        df = build_features(df)
        if sym == 'BTC-USD':
            btc_df_for_train = df.copy()

        # Bollinger entries/exits
        entries = df['Close'] <= df['bb_low']
        exits = df['Close'] >= df['bb_high']

        # Load or train model
        if model is None:
            model = ensure_model(btc_df_for_train if btc_df_for_train is not None else df)

        feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
        X_sym = df[feature_cols].fillna(0)
        try:
            ai_signal = model.predict(X_sym)
        except Exception as e:
            print('Model predict error:', e)
            ai_signal = np.ones(len(X_sym), dtype=int)

        # final entries: bollinger entry AND ai_signal==1
        final_entries = (entries & (ai_signal == 1)).shift(1).fillna(False)
        final_exits = exits.shift(1).fillna(False)

        # Backtest with vectorbt if available
        stats_row = {'symbol': sym, 'last_close': float(df['Close'].iloc[-1]), 'entries': int(final_entries.sum()), 'exits': int(final_exits.sum())}
        try:
            import vectorbt as vbt
            pf = vbt.Portfolio.from_signals(df['Close'], final_entries, final_exits, init_cash=10000, fees=0.001, slippage=0.0005, freq='30T')
            stats_row.update({
                'total_return': float(pf.total_return()),
                'annual_return': float(pf.annualized_return()),
                'max_drawdown': float(pf.max_drawdown()),
                'sharpe': float(pf.sharpe_ratio())
            })
            # save chart
            try:
                png = f"{sym.replace('/','_').replace('-','_')}_equity.png"
                pf.value().vbt.plot(title=f"Equity - {sym}"); plt.savefig(png); plt.close()
            except Exception as e:
                print('Chart save error:', e)
        except Exception as e:
            print('vectorbt not available or error, skipping advanced stats:', e)
        all_stats.append(stats_row)

        # Detect signal transitions (compare last two bars)
        sigs = []
        if len(final_entries) >= 2:
            last_entry = final_entries.iloc[-1]
            prev_entry = final_entries.iloc[-2]
            last_exit = final_exits.iloc[-1]
            prev_exit = final_exits.iloc[-2]

            entry_price = float(df['Close'].iloc[-1])
            upper = float(df['bb_high'].iloc[-1])
            lower = float(df['bb_low'].iloc[-1])
            atr = float(df['ATR'].iloc[-1])

            if last_entry and not prev_entry:
                # BUY - create dual targets
                boll_target = upper
                atr_target = entry_price + ATR_MULTIPLIER * atr
                msg = f"BUY {sym} at {entry_price:.6f} → Targets: Bollinger {boll_target:.6f}, ATR {atr_target:.6f}"
                sigs.append(msg)
            if last_exit and not prev_exit:
                # SELL - create dual targets (for short/cover)
                boll_target = lower
                atr_target = entry_price - ATR_MULTIPLIER * atr
                msg = f"SELL {sym} at {entry_price:.6f} → Targets: Bollinger {boll_target:.6f}, ATR {atr_target:.6f}"
                sigs.append(msg)

        # Save per-symbol csv for inspection
        out_csv = f"{sym.replace('-','_')}_signals_history.csv"
        df_out = df[['Open','High','Low','Close','bb_low','bb_high','ATR']].copy()
        df_out['ai_signal'] = ai_signal
        df_out['bollinger_entry'] = entries.astype(int)
        df_out['bollinger_exit'] = exits.astype(int)
        df_out.to_csv(out_csv)

        # Append only truly new signals (prevent duplicates)
        for s in sigs:
            results[f"{sym}"] = s.replace('\n', ' ') if isinstance(s, str) else s
            prev = last_signals.get(sym)
            if prev != s:
                new_signals.append(s)
                last_signals[sym] = s
                print('New signal:', s)
            else:
                print('Duplicate signal skipped for', sym)

    # Save aggregated stats and signals state
    pd.DataFrame(all_stats).to_csv(OUT_STATS, index=False)
    save_last_signals(last_signals)
    if new_signals:
        with open(SIGNAL_FILE, 'w') as f:
            for s in new_signals:
                f.write(f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} - {s}\n")
        print('Signals written to', SIGNAL_FILE)
    else:
        # remove signals.txt if exists (no new signals)
        try:
            os.remove(SIGNAL_FILE)
        except OSError:
            pass
    print('Backtest & scan complete. Stats saved to', OUT_STATS)
    if test_mode and new_signals:
        print('\n--- TEST MODE: Signals would be sent ---')
        for s in new_signals:
            print(s)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='Run in test mode (prints signals)')
    args = parser.parse_args()
    analyze_and_backtest(test_mode=args.test)
