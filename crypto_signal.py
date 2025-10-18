import os
import json
import yaml
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier

# ============================================================
# 🧹 CLEANUP OLD SIGNAL FILES
# ============================================================
UTILS_DIR = Path(__file__).parent / "utils"
UTILS_DIR.mkdir(exist_ok=True)
LAST_SIGNALS_FILE = UTILS_DIR / "last_signals.json"
SIGNALS_TXT = UTILS_DIR / "signals.txt"
MODEL_FILE = UTILS_DIR / "crypto_ai_model.pkl"

for f in [LAST_SIGNALS_FILE, SIGNALS_TXT]:
    with open(f, "w") as fp:
        fp.write("{}" if f.suffix == ".json" else "")
print("🧹 Cleared old signal files before run.")

# ============================================================
# ⚙️ CONFIGURATION
# ============================================================
CONFIG_FILE = Path(__file__).parent / "crypto.yml"
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r") as f:
        config_data = yaml.safe_load(f) or {}
else:
    print("⚠️ crypto.yml not found — using defaults.")
    config_data = {}

config = {
    "symbols": config_data.get("symbols", ["BTC-USD", "GALA-USD", "XRP-USD"]),
    "interval": config_data.get("interval", "30m"),
    "period": config_data.get("period", "60d"),
    "atr_window": config_data.get("atr_window", 14),
    "atr_multiplier": config_data.get("atr_multiplier", 1.5),
}

ZAPIER_URL = os.getenv("ZAPIER_URL")
SIGNAL_EMAIL = os.getenv("SIGNAL_EMAIL")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# ============================================================
# 🧩 HELPERS
# ============================================================
def load_last_signals():
    try:
        with open(LAST_SIGNALS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_last_signals(data):
    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ============================================================
# 🧠 FEATURE ENGINEERING
# ============================================================
def build_features(df):
    df = df.copy()
    # 🩹 Flatten any 2D data from yfinance
    for col in df.columns:
        if isinstance(df[col].iloc[0], (np.ndarray, list)):
            df[col] = [v[0] if isinstance(v, (list, np.ndarray)) else v for v in df[col]]

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

    atr = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=config["atr_window"])
    df['ATR'] = atr.average_true_range()

    # Candle patterns
    o, h, l, c = df['Open'], df['High'], df['Low'], df['Close']
    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l
    df['shooting_star'] = (((body <= 0.3*candle_range) & (upper_shadow >= 2*body) & (lower_shadow <= 0.2*body)).fillna(0)).astype(int)
    df['hammer'] = (((body <= 0.3*candle_range) & (lower_shadow >= 2*body) & (upper_shadow <= 0.2*body)).fillna(0)).astype(int)

    return df.dropna()

# ============================================================
# 🤖 MODEL TRAINING / LOAD
# ============================================================
def ensure_model(df):
    if MODEL_FILE.exists():
        try:
            return joblib.load(MODEL_FILE)
        except Exception:
            pass

    df['future_return'] = df['Close'].shift(-3) / df['Close'] - 1
    df = df.dropna()
    df['label'] = (df['future_return'] > 0.002).astype(int)

    feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
    X = df[feature_cols].fillna(0)
    y = df['label']

    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)
    return model

# ============================================================
# 📊 SIGNAL GENERATION
# ============================================================
def generate_signals():
    print("📡 Generating AI-based crypto signals ...")
    last_signals = load_last_signals()
    model = None
    new_signals = {}

    for sym in config["symbols"]:
        print(f"📡 Downloading {sym} ...")
        try:
            df = yf.download(sym, period=config["period"], interval=config["interval"], progress=False).dropna()
            df = build_features(df)
            if model is None:
                model = ensure_model(df)

            feature_cols = ['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']
            X = df[feature_cols].fillna(0)
            ai_pred = model.predict(X)

            entry = (df['Close'] <= df['bb_low']) & (ai_pred == 1)
            exit_ = df['Close'] >= df['bb_high']

            signal = "HOLD"
            if len(entry) >= 2:
                if entry.iloc[-1] and not entry.iloc[-2]:
                    signal = "BUY"
                elif exit_.iloc[-1] and not exit_.iloc[-2]:
                    signal = "SELL"

            new_signals[sym] = signal
            print(f"🔹 {sym}: {signal}")

        except Exception as e:
            print(f"❌ Error fetching {sym}:", e)

    return new_signals

# ============================================================
# 📤 ALERT LOGIC
# ============================================================
def send_via_zapier(signals):
    if not ZAPIER_URL:
        print("⚠️ ZAPIER_URL not set.")
        return
    try:
        payload = {"timestamp": datetime.utcnow().isoformat(), "signals": signals}
        r = requests.post(ZAPIER_URL, json=payload)
        print(f"✅ Sent to Zapier ({r.status_code})")
    except Exception as e:
        print("❌ Zapier send failed:", e)

def send_via_email(signals):
    if not (SMTP_USER and SMTP_PASS and SIGNAL_EMAIL):
        print("⚠️ Email credentials missing.")
        return
    try:
        msg = MIMEText(json.dumps(signals, indent=2))
        msg["Subject"] = f"Crypto Signals - {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
        msg["From"] = SMTP_USER
        msg["To"] = SIGNAL_EMAIL
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"📧 Signals emailed to {SIGNAL_EMAIL}")
    except Exception as e:
        print("❌ Email send failed:", e)

# ============================================================
# 🚀 MAIN
# ============================================================
def main():
    print("🚀 Starting Crypto AI Bot...")
    new_signals = generate_signals()

    actionable = {s: sig for s, sig in new_signals.items() if sig in ["BUY", "SELL"]}
    if not actionable:
        print("ℹ️ No actionable BUY/SELL signals.")
        return

    save_last_signals(actionable)
    with open(SIGNALS_TXT, "a") as f:
        for sym, sig in actionable.items():
            f.write(f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} - {sym}: {sig}\n")

    print("📈 New actionable signals:")
    for sym, sig in actionable.items():
        print(f" - {sym}: {sig}")

    send_via_zapier(actionable)
    send_via_email(actionable)
    print("✅ Bot execution completed.")

if __name__ == "__main__":
    main()
