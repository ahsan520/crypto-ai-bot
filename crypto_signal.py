import os
import json
import time
import yaml
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from ta.trend import SMAIndicator, MACD
from ta.momentum import RSIIndicator
from sklearn.preprocessing import MinMaxScaler
from sklearn.linear_model import LogisticRegression

# === Environment Variables ===
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

# === Utils Paths ===
SIGNAL_FILE = "utils/signals.txt"
LAST_SIGNALS_FILE = "utils/last_signals.json"
CONFIG_FILE = "crypto.yml"


# === CoinGecko + Yahoo Fetch Logic ===
def fetch_crypto_data(symbol, days=90, interval="hourly"):
    coin_map = {
        "BTC-USD": "bitcoin",
        "ETH-USD": "ethereum",
        "XRP-USD": "ripple",
        "GALA-USD": "gala"
    }
    coin_id = coin_map.get(symbol, None)
    if not coin_id:
        print(f"⚠️ Unknown symbol mapping for {symbol}, skipping CoinGecko.")
        return None

    # Try CoinGecko Pro API first
    if COINGECKO_API_KEY:
        url = f"https://pro-api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}
        params = {"vs_currency": "usd", "days": days, "interval": interval}
        try:
            print(f"🪙 Trying CoinGecko API for {coin_id}")
            r = requests.get(url, headers=headers, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            prices = data.get("prices", [])
            if not prices:
                raise ValueError("Empty price list from CoinGecko.")
            df = pd.DataFrame(prices, columns=["timestamp", "price"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df.rename(columns={"price": "Close"}, inplace=True)
            return df
        except Exception as e:
            print(f"❌ CoinGecko error for {symbol}: {e}")

    # Fallback to Yahoo Finance
    print(f"📉 Falling back to Yahoo Finance for {symbol}")
    for i in range(3):
        try:
            data = yf.download(symbol, period=f"{days}d", interval="1h", progress=False)
            if not data.empty:
                return data
            print(f"⚠️ Empty dataframe for {symbol}, retrying ({i+1}/3)...")
            time.sleep(2)
        except Exception as e:
            print(f"❌ Error fetching {symbol} from Yahoo: {e}")
            time.sleep(2)

    print(f"🚫 Failed to load data for {symbol} from both sources.")
    return None


# === AI Signal Generator ===
def generate_signals(df):
    if df is None or df.empty:
        return None

    df["SMA_20"] = SMAIndicator(df["Close"], window=20).sma_indicator()
    df["SMA_50"] = SMAIndicator(df["Close"], window=50).sma_indicator()
    macd = MACD(df["Close"])
    df["MACD"] = macd.macd()
    df["RSI"] = RSIIndicator(df["Close"]).rsi()
    df.dropna(inplace=True)

    X = df[["SMA_20", "SMA_50", "MACD", "RSI"]]
    y = np.where(df["Close"].shift(-1) > df["Close"], 1, 0)
    scaler = MinMaxScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression()
    model.fit(X_scaled[:-1], y[:-1])
    df["signal"] = model.predict(X_scaled)
    last_signal = df["signal"].iloc[-1]

    return "BUY" if last_signal == 1 else "SELL"


# === Load Configuration ===
def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("⚠️ crypto.yml not found — using defaults.")
        return {"symbols": ["BTC-USD", "ETH-USD", "XRP-USD", "GALA-USD"]}
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


# === Main Execution ===
def main():
    print("🧹 Cleared old signal files before run.")
    open(SIGNAL_FILE, "w").close()
    config = load_config()
    symbols = config.get("symbols", [])

    all_signals = {}
    for symbol in symbols:
        print(f"📡 Fetching {symbol} data...")
        df = fetch_crypto_data(symbol)
        if df is None or df.empty:
            print(f"⚠️ No data for {symbol}, skipping...")
            continue

        signal = generate_signals(df)
        all_signals[symbol] = signal
        print(f"📈 {symbol}: {signal}")
        with open(SIGNAL_FILE, "a") as f:
            f.write(f"{symbol}: {signal}\n")

    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(all_signals, f, indent=2)

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(all_signals, indent=2))
    print("✅ Bot execution completed.")


if __name__ == "__main__":
    print("🚀 Starting Crypto AI Bot...")
    main()
