# ------------------------------------------------------------
# 🧹 ENSURE CLEAN START BEFORE IMPORTS
# ------------------------------------------------------------
import json
import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent
UTILS_DIR = ROOT_DIR / "utils"
UTILS_DIR.mkdir(exist_ok=True)

LAST_SIGNALS_FILE = UTILS_DIR / "last_signals.json"
SIGNALS_TXT = UTILS_DIR / "signals.txt"

# Clear both files before anything else runs
for file, label in [(LAST_SIGNALS_FILE, "last_signals.json"), (SIGNALS_TXT, "signals.txt")]:
    try:
        with open(file, "w") as f:
            if file.suffix == ".json":
                json.dump({}, f)
            else:
                f.write("")
        print(f"🧹 Cleared contents of {label} before run.")
    except Exception as e:
        print(f"⚠️ Failed to clear {label}: {e}")

# ------------------------------------------------------------
# 📦 IMPORTS & CONFIGURATION
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# 📦 FILE PATHS & CONFIG
# ------------------------------------------------------------
CONFIG_FILE = ROOT_DIR / "crypto.yml"
MODEL_FILE = UTILS_DIR / "crypto_ai_model.pkl"

# Default fallback values
CONFIG_DEFAULTS = {
    "symbols": ["BTC-USD", "GALA-USD", "XRP-USD"],
    "interval": "30m",
    "period": "60d",
    "atr_window": 14,
    "atr_multiplier": 1.5,
}

# Load YAML config if available
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r") as f:
        config_data = yaml.safe_load(f) or {}
else:
    print("⚠️ crypto.yml not found — using defaults.")
    config_data = {}

# Merge defaults
config = {**CONFIG_DEFAULTS, **config_data}

# Environment variables
ZAPIER_URL = os.getenv("ZAPIER_URL")
SIGNAL_EMAIL = os.getenv("SIGNAL_EMAIL")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# ------------------------------------------------------------
# ⚙️ UTILITY HELPERS
# ------------------------------------------------------------
def load_last_signals():
    if LAST_SIGNALS_FILE.exists():
        try:
            with open(LAST_SIGNALS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print("⚠️ Failed to load last_signals.json:", e)
    return {}

def save_last_signals(data):
    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ------------------------------------------------------------
# 🤖 STRATEGY SECTION (AI-BASED)
# ------------------------------------------------------------
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
    atr = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=config["atr_window"])
    df['ATR'] = atr.average_true_range()

    o, h, l, c = df['Open'], df['High'], df['Low'], df['Close']
    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l
    df['shooting_star'] = (((body <= 0.3*candle_range) & (upper_shadow >= 2*body) & (lower_shadow <= 0.2*body)).fillna(0)).astype(int)
    df['hammer'] = (((body <= 0.3*candle_range) & (lower_shadow >= 2*body) & (upper_shadow <= 0.2*body)).fillna(0)).astype(int)
    return df.dropna()

def ensure_model(df):
    if MODEL_FILE.exists():
        try:
            return joblib.load(MODEL_FILE)
        except:
            pass

    from sklearn.ensemble import RandomForestClassifier
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

# ------------------------------------------------------------
# 📊 SIGNAL GENERATION
# ------------------------------------------------------------
def generate_signals():
    print("📡 Generating AI-based crypto signals ...")
    last_signals = load_last_signals()
    model = None
    new_signals = {}

    for sym in config["symbols"]:
        print(f"Downloading {sym} ...")
        df = yf.download(sym, period=config["period"], interval=config["interval"], progress=False).dropna()
        if df.empty:
            print(f"⚠️ No data for {sym}")
            continue

        df = build_features(df)
        if model is None:
            model = ensure_model(df)

        X = df[['rsi','macd','bb_mid','bb_high','bb_low','bb_width','percent_b','volume_change','shooting_star','hammer']].fillna(0)
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

    return new_signals

# ------------------------------------------------------------
# 📤 NOTIFICATION LOGIC
# ------------------------------------------------------------
def send_via_zapier(signals):
    if not ZAPIER_URL:
        print("⚠️ ZAPIER_URL not set. Skipping Zapier notification.")
        return
    try:
        payload = {"timestamp": datetime.utcnow().isoformat(), "signals": signals}
        r = requests.post(ZAPIER_URL, json=payload)
        print(f"✅ Sent to Zapier ({r.status_code})")
    except Exception as e:
        print("❌ Zapier send failed:", e)

def send_via_email(signals):
    if not (SMTP_USER and SMTP_PASS and SIGNAL_EMAIL):
        print("⚠️ Email credentials not set. Skipping email send.")
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

# ------------------------------------------------------------
# 🚀 MAIN BOT LOGIC
# ------------------------------------------------------------
def main():
    print("🚀 Starting Crypto AI Bot ...")
    last_signals = load_last_signals()
    new_signals = generate_signals()

    if not new_signals or all(v == "HOLD" for v in new_signals.values()):
        print("ℹ️ No actionable signals.")
        return

    changed = {}
    for sym, sig in new_signals.items():
        prev = last_signals.get(sym)
        if sig != prev:
            changed[sym] = sig
            last_signals[sym] = sig

    if not changed:
        print("✅ No changes since last signal run.")
        return

    print("📈 New signals detected:")
    for sym, sig in changed.items():
        print(f" - {sym}: {sig}")

    save_last_signals(last_signals)
    with open(SIGNALS_TXT, "a") as f:
        for sym, sig in changed.items():
            f.write(f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} - {sym}: {sig}\n")

    send_via_zapier(changed)
    send_via_email(changed)

    print("✅ Signals processed and saved.")

if __name__ == "__main__":
    main()
