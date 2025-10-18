import yfinance as yf
import pandas as pd
import numpy as np
import ta
import joblib
import os, json, requests, smtplib
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from sklearn.ensemble import RandomForestClassifier

# ---------------- CONFIG ----------------
SYMBOLS = ["BTC", "ETH", "XRP", "GALA"]
INTERVAL = "1h"
PERIOD = "90d"
MODEL_FILE = "crypto_ai_model.pkl"
UTILS_DIR = "utils"
SIGNALS_DIR = f"{UTILS_DIR}/signals"
SIGNALS_FILE = f"{SIGNALS_DIR}/signals.txt"
HOLDS_FILE = f"{SIGNALS_DIR}/holds.txt"
LAST_SIGNALS_FILE = f"{UTILS_DIR}/last_signals.json"
SUMMARY_FILE = f"{UTILS_DIR}/summary.json"
ATR_WINDOW = 14
ATR_MULTIPLIER = 1.5

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
# ----------------------------------------

os.makedirs(SIGNALS_DIR, exist_ok=True)
for f in [SIGNALS_FILE, HOLDS_FILE, SUMMARY_FILE]:
    try:
        open(f, "a").close()
    except Exception:
        pass


# ---------------- HELPERS ----------------
def fetch_price(symbol):
    """Try Yahoo → CoinGecko → Binance fallback."""
    sym = symbol.upper()

    # Yahoo Finance
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={sym}-USD", timeout=10
        )
        d = r.json()
        return float(d["quoteResponse"]["result"][0]["regularMarketPrice"])
    except Exception as e:
        print(f"⚠️ Yahoo failed for {symbol}: {e}")

    # CoinGecko
    try:
        headers = {"accept": "application/json"}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
        id_map = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "GALA": "gala"}
        if sym in id_map:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": id_map[sym], "vs_currencies": "usd"},
                headers=headers,
                timeout=10,
            )
            d = r.json()
            if id_map[sym] in d:
                return float(d[id_map[sym]]["usd"])
    except Exception as e:
        print(f"⚠️ CoinGecko failed for {symbol}: {e}")

    # Binance
    try:
        r = requests.get(
            f"https://api.binance.com/api/v3/ticker/price?symbol={sym}USDT", timeout=10
        )
        d = r.json()
        if "price" in d:
            return float(d["price"])
    except Exception as e:
        print(f"⚠️ Binance failed for {symbol}: {e}")

    return None


def build_features(df):
    df = df.copy()
    df["rsi"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    macd = ta.trend.MACD(df["Close"])
    df["macd"] = macd.macd()
    bb = ta.volatility.BollingerBands(df["Close"])
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_high"] - df["bb_low"]) / df["Close"]
    df["percent_b"] = (df["Close"] - df["bb_low"]) / (df["bb_high"] - df["bb_low"])
    atr = ta.volatility.AverageTrueRange(df["High"], df["Low"], df["Close"], window=ATR_WINDOW)
    df["ATR"] = atr.average_true_range()
    return df.dropna()


def send_notification(message, subject="Crypto Signal Alert"):
    """Try Zapier webhook, fallback to SMTP."""
    # 1️⃣ Try Zapier
    if ZAPIER_WEBHOOK_URL:
        try:
            r = requests.post(ZAPIER_WEBHOOK_URL, json={"text": message}, timeout=10)
            if r.status_code == 200:
                print("✅ Sent via Zapier webhook.")
                return
        except Exception as e:
            print(f"⚠️ Zapier failed: {e}")

    # 2️⃣ Fallback: SMTP email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_TO:
        try:
            msg = MIMEText(message)
            msg["Subject"] = subject
            msg["From"] = EMAIL_SENDER
            msg["To"] = EMAIL_TO

            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_TO, msg.as_string())
            server.quit()
            print("📧 Email sent successfully.")
        except Exception as e:
            print(f"⚠️ Email send failed: {e}")


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


def ensure_model(train_df):
    """Train fallback ML model if missing."""
    if os.path.exists(MODEL_FILE):
        try:
            return joblib.load(MODEL_FILE)
        except Exception as e:
            print(f"⚠️ Model load failed: {e}")

    print("🚀 Training lightweight RandomForest model...")
    df = train_df.copy()
    df["future_return"] = df["Close"].shift(-3) / df["Close"] - 1
    df.dropna(inplace=True)
    df["label"] = (df["future_return"] > 0.002).astype(int)
    features = ["rsi", "macd", "bb_high", "bb_low", "bb_width", "percent_b", "ATR"]
    X, y = df[features].fillna(0), df["label"]

    model = RandomForestClassifier(n_estimators=120, max_depth=6, random_state=42)
    model.fit(X, y)
    joblib.dump(model, MODEL_FILE)
    print("✅ Model trained and saved.")
    return model


def analyze():
    last_signals = load_last_signals()
    new_signals = {}
    summary = {"BUY": [], "SELL": [], "HOLD": []}
    model = None

    for sym in SYMBOLS:
        print(f"📊 Processing {sym}...")
        try:
            df = yf.download(f"{sym}-USD", period=PERIOD, interval=INTERVAL, progress=False).dropna()
        except Exception as e:
            print(f"⚠️ Data fetch failed for {sym}: {e}")
            continue

        if df.empty:
            print(f"⚠️ No data for {sym}")
            continue

        df = build_features(df)
        if model is None:
            model = ensure_model(df)

        X = df[["rsi", "macd", "bb_high", "bb_low", "bb_width", "percent_b", "ATR"]].fillna(0)
        preds = model.predict(X)
        df["ai_signal"] = preds

        # Technical + AI combo decision
        rsi, macd_val, prev_macd = df["rsi"].iloc[-1], df["macd"].iloc[-1], df["macd"].iloc[-2]
        if preds[-1] == 1 and rsi < 70 and macd_val > prev_macd:
            signal = "BUY"
        elif rsi > 65 and macd_val < prev_macd:
            signal = "SELL"
        else:
            signal = "HOLD"

        price = fetch_price(sym) or df["Close"].iloc[-1]
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"{ts} | {sym} | {signal} | ${price:.4f}"

        if signal in ["BUY", "SELL"]:
            with open(SIGNALS_FILE, "a") as f:
                f.write(entry + "\n")
        else:
            with open(HOLDS_FILE, "a") as f:
                f.write(entry + "\n")

        new_signals[sym] = {"signal": signal, "price": price, "time": ts}
        summary[signal].append({"symbol": sym, "price": price, "time": ts})
        print(entry)

        # Notify only on signal change or new buy/sell
        if (
            sym not in last_signals
            or last_signals[sym]["signal"] != signal
            or signal in ["BUY", "SELL"]
        ):
            send_notification(entry, subject=f"Crypto {signal} Signal for {sym}")

    # Save outputs
    save_last_signals(new_signals)
    Path(SUMMARY_FILE).write_text(json.dumps(summary, indent=2))
    print("✅ Signals processed and summary saved.")


if __name__ == "__main__":
    analyze()
