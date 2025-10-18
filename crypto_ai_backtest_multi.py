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
UTILS_DIR = Path("utils")
SIGNAL_FILE = UTILS_DIR / 'signals.txt'
HOLDS_FILE = UTILS_DIR / 'holds.txt'
LAST_SIGNALS_FILE = UTILS_DIR / 'last_signals.json'
OUT_STATS = UTILS_DIR / 'backtest_stats.csv'
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
    atr = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=ATR_WINDOW)
    df['ATR'] = atr.average_true_range()
    # Candlestick patterns
    o, h, l, c = df['Open'], df['High'], df['Low'], df['Close']
    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l
    df['shooting_star'] = (((body <= 0.3*candle_range) & (upper_shadow >= 2*body) & (lower_shadow <= 0.2*body)).fillna(0)).astype(int)
    df['hammer'] = (((body <= 0.3*candle_range) & (lower_shadow >= 2*body) & (upper_shadow <= 0.2*body)).fillna(0)).astype(int)
    return df.dropna()

def load_last_signals():
    if LAST_SIGNALS_FILE.exists():
        try:
            return json.loads(LAST_SIGNALS_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_last_signals(d):
    UTILS_DIR.mkdir(exist_ok=True)
    LAST_SIGNALS_FILE.write_text(json.dumps(d, indent=2))

def ensure_model(train_df=None):
    if os.path.exists(MODEL_FILE):
        try:
            print('✅ Loading model:', MODEL_FILE)
            return joblib.load(MODEL_FILE)
        except Exception as e:
            print('⚠️ Failed to load model:', e)
    print('🔧 Training fallback RandomForest model...')
    from sklearn.ensemble import RandomForestClassifier
    df = train_df.copy() if train_df is not None else None
    if df is None or df.empty:
        class Dummy:
            def predict(self, X): return np.ones(len(X), dtype=int)
        return Dummy()
    df['future_return'] = df['Close'].shift(-HORIZON) / df['Close'] - 1
    df = df.dropna()
    df['label'] = (df['future_return'] > 0.002).astype(int)
    feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
    X = df[feature_cols].fillna(0)
    y = df['label']
    if len(X) < 50:
        class Dummy:
            def predict(self, X): return np.ones(len(X), dtype=int)
        return Dummy()
    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)
    print('✅ Fallback model trained and saved.')
    return model

def analyze_and_backtest(test_mode=False):
    UTILS_DIR.mkdir(exist_ok=True)
    all_stats = []
    model = None
    btc_df_for_train = None
    last_signals = load_last_signals()
    new_signals = []
    results = {}

    for sym in SYMBOLS:
        print(f"📈 Processing {sym} ...")
        df = yf.download(sym, period=PERIOD, interval=INTERVAL, progress=False).dropna()
        if df.empty:
            print('⚠️ No data for', sym)
            continue

        df = build_features(df)
        if sym == 'BTC-USD':
            btc_df_for_train = df.copy()

        entries = df['Close'] <= df['bb_low']
        exits = df['Close'] >= df['bb_high']

        if model is None:
            model = ensure_model(btc_df_for_train if btc_df_for_train is not None else df)

        feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
        X_sym = df[feature_cols].fillna(0)
        try:
            ai_signal = model.predict(X_sym)
        except Exception as e:
            print('⚠️ Model predict error:', e)
            ai_signal = np.ones(len(X_sym), dtype=int)

        final_entries = (entries & (ai_signal == 1)).shift(1).fillna(False)
        final_exits = exits.shift(1).fillna(False)

        stats_row = {'symbol': sym, 'last_close': float(df['Close'].iloc[-1]),
                     'entries': int(final_entries.sum()), 'exits': int(final_exits.sum())}
        all_stats.append(stats_row)

        sigs = []
        if len(final_entries) >= 2:
            last_entry, prev_entry = final_entries.iloc[-1], final_entries.iloc[-2]
            last_exit, prev_exit = final_exits.iloc[-1], final_exits.iloc[-2]
            entry_price = float(df['Close'].iloc[-1])
            upper, lower, atr = float(df['bb_high'].iloc[-1]), float(df['bb_low'].iloc[-1]), float(df['ATR'].iloc[-1])

            if last_entry and not prev_entry:
                boll_target = upper
                atr_target = entry_price + ATR_MULTIPLIER * atr
                msg = f"BUY {sym} at {entry_price:.6f} → Targets: Bollinger {boll_target:.6f}, ATR {atr_target:.6f}"
                sigs.append(msg)
            elif last_exit and not prev_exit:
                boll_target = lower
                atr_target = entry_price - ATR_MULTIPLIER * atr
                msg = f"SELL {sym} at {entry_price:.6f} → Targets: Bollinger {boll_target:.6f}, ATR {atr_target:.6f}"
                sigs.append(msg)
            else:
                msg = f"HOLD {sym} ({entry_price:.6f})"
                sigs.append(msg)

        for s in sigs:
            results[sym] = s
            prev = last_signals.get(sym)
            if "HOLD" in s:
                continue  # skip adding hold to new_signals
            if prev != s:
                new_signals.append(s)
                last_signals[sym] = s
                print('✅ New signal:', s)
            else:
                print('➡️ No change for', sym)

    pd.DataFrame(all_stats).to_csv(OUT_STATS, index=False)
    save_last_signals(last_signals)

    # Write signals
    if new_signals:
        SIGNAL_FILE.write_text(
            "\n".join(f"{datetime.utcnow():%Y-%m-%d %H:%M:%S UTC} - {s}" for s in new_signals)
        )
        print('✅ Signals written:', SIGNAL_FILE)
    else:
        HOLDS_FILE.write_text(
            "\n".join([f"{datetime.utcnow():%Y-%m-%d %H:%M:%S UTC} - {v}" for v in results.values()])
        )
        print('ℹ️ No BUY/SELL signals. Holds written to', HOLDS_FILE)

    print('✅ Backtest complete. Stats saved to', OUT_STATS)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    analyze_and_backtest(test_mode=args.test)
