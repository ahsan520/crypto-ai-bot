import os
import json
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import ta
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ===========================
# CONFIG
# ===========================
COINS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "XRP-USD": "ripple",
    "GALA-USD": "gala"
}
LAST_SIGNAL_FILE = "utils/last_signals.json"
SIGNALS_TXT = "utils/signals.txt"
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
ZAPIER_WEBHOOK = os.getenv("ZAPIER_WEBHOOK_URL", "")
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ===========================
# UTILITIES
# ===========================
def clear_old_files():
    for f in [LAST_SIGNAL_FILE, SIGNALS_TXT]:
        if os.path.exists(f):
            open(f, "w").close()
    print("🧹 Cleared old signal files before run.")

def save_signal(symbol, signal, confidence):
    data = {
        "symbol": symbol,
        "signal": signal,
        "confidence": round(confidence, 2),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    with open(LAST_SIGNAL_FILE, "w") as f:
        json.dump(data, f, indent=2)
    with open(SIGNALS_TXT, "a") as f:
        f.write(f"{data}\n")
    print(f"💾 Saved signal: {symbol} → {signal} ({confidence:.2f})")

def send_email_alert(symbol, signal, confidence):
    if not EMAIL_USER or not EMAIL_PASS or not EMAIL_TO:
        print("⚠️ Email credentials not configured — skipping email.")
        return
    subject = f"Crypto Signal Alert: {symbol} = {signal}"
    body = f"""
    New crypto signal generated:

    🪙 Coin: {symbol}
    📈 Signal: {signal}
    🎯 Confidence: {confidence:.2f}
    ⏰ Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
    """
    msg = MIMEMultipart()
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        print(f"📧 Email sent: {symbol} → {signal}")
    except Exception as e:
        print(f"❌ Email failed: {e}")

def send_zapier_alert(symbol, signal, confidence):
    if not ZAPIER_WEBHOOK:
        print("⚠️ No Zapier webhook configured — skipping.")
        return
    payload = {"symbol": symbol, "signal": signal, "confidence": confidence}
    try:
        requests.post(ZAPIER_WEBHOOK, json=payload, timeout=10)
        print("📡 Zapier alert sent.")
    except Exception as e:
        print(f"❌ Zapier alert failed: {e}")

# ===========================
# DATA FETCHING
# ===========================
def fetch_from_coingecko(coin_id, days=90):
    if not COINGECKO_API_KEY:
        raise Exception("Missing CoinGecko API key")

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    headers = {"accept": "application/json", "x-cg-pro-api-key": COINGECKO_API_KEY}
    params = {"vs_currency": "usd", "days": days, "interval": "hourly"}
    r = requests.get(url, headers=headers, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    prices = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    prices["timestamp"] = pd.to_datetime(prices["timestamp"], unit="ms")
    prices = prices.set_index("timestamp")
    return pd.DataFrame({"Close": prices["price"]})

def fetch_from_yahoo(symbol, period="90d", interval="1h"):
    df = yf.download(symbol, period=period, interval=interval, progress=False)
    if df is None or df.empty:
        return pd.DataFrame()
    return df[["Close"]].dropna()

def get_crypto_data(symbol, coin_id):
    print(f"📡 Fetching {symbol} data...")
    try:
        print(f"🪙 Trying CoinGecko API for {coin_id}")
        return fetch_from_coingecko(coin_id)
    except Exception as e:
        print(f"❌ CoinGecko error for {symbol}: {e}")
        print(f"📉 Falling back to Yahoo Finance for {symbol}")
        for i in range(3):
            df = fetch_from_yahoo(symbol)
            if not df.empty:
                return df
            print(f"⚠️ Empty dataframe for {symbol}, retrying ({i+1}/3)...")
            time.sleep(2)
    print(f"🚫 Failed to load data for {symbol} from both sources.")
    return pd.DataFrame()

# ===========================
# FEATURE ENGINEERING
# ===========================
def build_features(df):
    df["rsi"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["ema_20"] = ta.trend.EMAIndicator(df["Close"], 20).ema_indicator()
    df["ema_50"] = ta.trend.EMAIndicator(df["Close"], 50).ema_indicator()
    df["sma_200"] = ta.trend.SMAIndicator(df["Close"], 200).sma_indicator()
    df["momentum"] = df["Close"].pct_change(3)
    df = df.dropna()
    return df

# ===========================
# SIGNAL GENERATION
# ===========================
def generate_signal(df):
    df["target"] = np.where(df["Close"].shift(-1) > df["Close"], 1, 0)
    features = ["rsi", "ema_20", "ema_50", "sma_200", "momentum"]
    X = df[features]
    y = df["target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = RandomForestClassifier(n_estimators=150, random_state=42)
    model.fit(X_train_scaled, y_train)

    prob = model.predict_proba([X_test_scaled[-1]])[0][1]
    signal = "BUY" if prob > 0.65 else "SELL" if prob < 0.35 else "HOLD"
    return signal, prob

# ===========================
# MAIN
# ===========================
def main():
    print("🚀 Starting Crypto AI Bot...")
    clear_old_files()
    all_signals = {}

    for symbol, coin_id in COINS.items():
        df = get_crypto_data(symbol, coin_id)
        if df.empty:
            print(f"⚠️ No data for {symbol}, skipping...")
            continue
        df = build_features(df)
        signal, confidence = generate_signal(df)
        print(f"📊 {symbol}: {signal} ({confidence:.2f})")
        all_signals[symbol] = {"signal": signal, "confidence": round(confidence, 2)}

        if signal in ["BUY", "SELL"]:
            save_signal(symbol, signal, confidence)
            send_email_alert(symbol, signal, confidence)
            send_zapier_alert(symbol, signal, confidence)

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(all_signals, indent=2))
    print("✅ Bot execution completed.")

if __name__ == "__main__":
    main()
