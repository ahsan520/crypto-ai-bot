import os, requests, smtplib, json, numpy as np, pandas as pd, yfinance as yf, ta
from datetime import datetime
from email.mime.text import MIMEText
from sklearn.ensemble import RandomForestClassifier

# ---------------- CONFIG ----------------
SYMBOLS = ["BTC", "ETH", "ADA", "DOGE", "SOL", "XRP"]
PERIOD = "60d"
INTERVAL = "1h"

ZAPIER_WEBHOOK = os.getenv("ZAPIER_WEBHOOK", "https://hooks.zapier.com/hooks/catch/XXXXXX/XXXXXX")
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "alert@example.com")
SMTP_PASS = os.getenv("SMTP_PASS", "password")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# ------------- DATA FETCHERS -------------
def fetch_yahoo(sym):
    try:
        df = yf.download(f"{sym}-USD", period=PERIOD, interval=INTERVAL, progress=False)
        if not df.empty:
            return df.dropna()
    except Exception as e:
        print(f"⚠️ Yahoo failed for {sym}: {e}")
    return None

def fetch_coingecko(sym):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{sym.lower()}/market_chart?vs_currency=usd&days=60&interval=hourly"
        r = requests.get(url, timeout=10)
        data = r.json()
        prices = pd.DataFrame(data["prices"], columns=["timestamp", "Close"])
        prices["Date"] = pd.to_datetime(prices["timestamp"], unit="ms")
        prices.set_index("Date", inplace=True)
        return prices
    except Exception as e:
        print(f"⚠️ CoinGecko failed for {sym}: {e}")
    return None

def fetch_binance(sym):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym.upper()}USDT&interval=1h&limit=720"
        r = requests.get(url, timeout=10)
        data = r.json()
        df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Vol", "_", "_", "_", "_", "_", "_"])
        df["Date"] = pd.to_datetime(df["Time"], unit="ms")
        df["Close"] = df["Close"].astype(float)
        df.set_index("Date", inplace=True)
        return df[["Close"]]
    except Exception as e:
        print(f"⚠️ Binance failed for {sym}: {e}")
    return None

def fetch_data(sym):
    for fetcher in [fetch_yahoo, fetch_coingecko, fetch_binance]:
        df = fetcher(sym)
        if df is not None and not df.empty:
            print(f"✅ Data fetched for {sym} via {fetcher.__name__}")
            return df
    print(f"❌ Failed to fetch data for {sym}")
    return None

# ------------- FEATURES -----------------
def build_features(df):
    df = df.copy()
    close = df["Close"].squeeze()
    df["rsi"] = ta.momentum.RSIIndicator(close).rsi()
    macd = ta.trend.MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["ema_fast"] = ta.trend.EMAIndicator(close, 12).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(close, 26).ema_indicator()
    df["ema_crossover"] = df["ema_fast"] - df["ema_slow"]
    df.dropna(inplace=True)
    return df

# ------------- AI MODEL -----------------
def ai_predict(df):
    df = df.copy()
    df["target"] = np.where(df["Close"].shift(-1) > df["Close"], 1, 0)
    features = ["rsi", "macd", "macd_signal", "ema_fast", "ema_slow", "ema_crossover"]

    model = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    model.fit(df[features][:-1], df["target"][:-1])

    df["pred"] = model.predict(df[features])
    df["prob"] = model.predict_proba(df[features])[:, 1]
    return df

# ------------- ALERTS -------------------
def send_alert(sym, signal, price, confidence):
    msg = f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} — {sym} {signal.upper()} signal at ${price:.2f} (Confidence: {confidence:.1f}%)"
    print(f"🚨 {msg}")

    try:
        requests.post(ZAPIER_WEBHOOK, json={"symbol": sym, "signal": signal, "price": price, "confidence": confidence})
        print("✅ Sent to Zapier webhook")
        return
    except Exception as e:
        print(f"⚠️ Zapier failed: {e}")

    try:
        s = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        s.starttls()
        s.login(SMTP_EMAIL, SMTP_PASS)
        s.sendmail(SMTP_EMAIL, SMTP_EMAIL, msg)
        s.quit()
        print("📧 Sent email fallback")
    except Exception as e:
        print(f"⚠️ Email failed: {e}")

# ------------- MAIN ---------------------
def analyze():
    for sym in SYMBOLS:
        print(f"📊 Processing {sym}...")
        df = fetch_data(sym)
        if df is None:
            continue

        df = build_features(df)
        df = ai_predict(df)

        last = df.iloc[-1].squeeze()
        prev = df.iloc[-2].squeeze()

        try:
            rsi = float(last["rsi"])
            macd = float(last["macd"])
            macd_signal = float(last["macd_signal"])
            ema_fast = float(last["ema_fast"])
            ema_slow = float(last["ema_slow"])
            prev_ema_fast = float(prev["ema_fast"])
            prev_ema_slow = float(prev["ema_slow"])
        except Exception as e:
            print(f"⚠️ Conversion error for {sym}: {e}")
            continue

        signal = None

        # --- BUY ---
        if (
            rsi < 30
            and macd > macd_signal
            and ema_fast > ema_slow
            and prev_ema_fast <= prev_ema_slow
            and last["pred"] == 1
        ):
            signal = "buy"

        # --- SELL ---
        elif (
            rsi > 70
            and macd < macd_signal
            and ema_fast < ema_slow
            and prev_ema_fast >= prev_ema_slow
            and last["pred"] == 0
        ):
            signal = "sell"

        if signal:
            confidence = float(last["prob"]) * 100
            send_alert(sym, signal, float(last["Close"]), confidence)

if __name__ == "__main__":
    print("🚀 Running crypto_signal.py...")
    analyze()
