import os
import json
import time
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from sklearn.preprocessing import MinMaxScaler
import joblib

# ======================
# 🔧 Configuration
# ======================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
SIGNALS_FILE = "utils/signals.txt"
LAST_SIGNALS_FILE = "utils/last_signals.json"

COINS = ["BTC-USD", "ETH-USD", "XRP-USD", "GALA-USD"]

# ======================
# ⚙️ Helper: fetch from CoinGecko demo API
# ======================
def fetch_from_coingecko(symbol):
    coin_map = {
        "BTC-USD": "bitcoin",
        "ETH-USD": "ethereum",
        "XRP-USD": "ripple",
        "GALA-USD": "gala"
    }

    coin = coin_map.get(symbol)
    if not coin:
        print(f"⚠️ No CoinGecko mapping for {symbol}")
        return None

    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": coin,
        "vs_currencies": "usd",
        "x_cg_demo_api_key": COINGECKO_API_KEY
    }

    try:
        print(f"🪙 Trying CoinGecko API for {coin}")
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        if coin not in data or "usd" not in data[coin]:
            print(f"❌ No valid price data for {symbol}")
            return None

        price = data[coin]["usd"]
        dates = pd.date_range(datetime.now() - timedelta(days=90), periods=90, freq="D")
        df = pd.DataFrame({"Close": [price] * len(dates)}, index=dates)
        print(f"✅ Successfully fetched {symbol} data from CoinGecko (demo mode)")
        return df

    except Exception as e:
        print(f"❌ CoinGecko error for {symbol}: {e}")
        return None


# ======================
# ⚙️ Helper: fetch from Yahoo Finance
# ======================
def fetch_from_yahoo(symbol, retries=3):
    print(f"📉 Falling back to Yahoo Finance for {symbol}")
    for attempt in range(retries):
        try:
            df = yf.download(symbol, period="90d", interval="1h", progress=False)
            if not df.empty:
                print(f"✅ Yahoo Finance data fetched for {symbol}")
                return df
            else:
                print(f"⚠️ Empty dataframe for {symbol}, retrying ({attempt+1}/{retries})...")
                time.sleep(2)
        except Exception as e:
            print(f"⚠️ Error fetching {symbol} from Yahoo: {e}")
            time.sleep(2)
    print(f"🚫 Failed to load data for {symbol} from both sources.")
    return None


# ======================
# 🧮 Feature Engineering
# ======================
def add_indicators(df):
    df["RSI"] = RSIIndicator(df["Close"], window=14).rsi()
    macd = MACD(df["Close"])
    df["MACD"] = macd.macd()
    df["Signal"] = macd.macd_signal()
    df.dropna(inplace=True)
    return df


# ======================
# 🤖 Simple AI model (scaled MACD/RSI)
# ======================
def generate_signal(df):
    if df is None or df.empty:
        return None

    df = add_indicators(df)
    latest = df.iloc[-1]

    rsi = latest["RSI"]
    macd = latest["MACD"]
    signal = latest["Signal"]

    # Simple AI logic
    if rsi < 30 and macd > signal:
        return "BUY"
    elif rsi > 70 and macd < signal:
        return "SELL"
    else:
        return "HOLD"


# ======================
# 💾 Save and summarize signals
# ======================
def save_signal(symbol, signal):
    if not os.path.exists("utils"):
        os.makedirs("utils")

    # Update JSON summary
    if os.path.exists(LAST_SIGNALS_FILE):
        with open(LAST_SIGNALS_FILE, "r") as f:
            last_signals = json.load(f)
    else:
        last_signals = {}

    last_signals[symbol] = {
        "signal": signal,
        "time": datetime.utcnow().isoformat()
    }

    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(last_signals, f, indent=2)

    # Append to text log
    with open(SIGNALS_FILE, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()} | {symbol} | {signal}\n")


# ======================
# 🚀 Main Bot Runner
# ======================
def main():
    print("🚀 Starting Crypto AI Bot...")
    os.makedirs("utils", exist_ok=True)
    open(SIGNALS_FILE, "w").close()  # clear old file

    for symbol in COINS:
        print(f"📡 Fetching {symbol} data...")

        df = fetch_from_coingecko(symbol)
        if df is None:
            df = fetch_from_yahoo(symbol)

        if df is None or df.empty:
            print(f"⚠️ No data for {symbol}, skipping...")
            continue

        signal = generate_signal(df)
        save_signal(symbol, signal)
        print(f"✅ {symbol} → {signal}")

    print("📊 ===== SIGNAL SUMMARY =====")
    if os.path.exists(LAST_SIGNALS_FILE):
        with open(LAST_SIGNALS_FILE, "r") as f:
            print(f.read())
    else:
        print("{}")

    print("✅ Bot execution completed.")


if __name__ == "__main__":
    main()
