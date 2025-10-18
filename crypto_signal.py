import os
import json
import pandas as pd
import numpy as np
import ta
import yfinance as yf
import requests
import time
import yaml
from datetime import datetime
from pathlib import Path

# === File paths ===
UTILS_DIR = Path(__file__).resolve().parent / "utils"
LAST_SIGNALS_FILE = UTILS_DIR / "last_signals.json"
SIGNALS_TXT_FILE = UTILS_DIR / "signals.txt"

# === Email (optional) ===
from utils.helpers import send_email_alert  # must exist


# === Config ===
DEFAULT_CONFIG = {
    "symbols": ["BTC-USD", "ETH-USD", "XRP-USD", "GALA-USD"],
    "interval": "1h",
    "lookback_days": 90,
    "rsi_buy": 30,
    "rsi_sell": 70,
}

# === Load config if exists ===
CONFIG_PATH = Path("crypto.yml")
if CONFIG_PATH.exists():
    with open(CONFIG_PATH, "r") as f:
        CONFIG = yaml.safe_load(f)
else:
    print("⚠️ crypto.yml not found — using defaults.")
    CONFIG = DEFAULT_CONFIG


# === Helper: Fetch Data (CoinGecko primary, Yahoo fallback) ===
def fetch_crypto_data(symbol: str, days: int = 90):
    """Fetch crypto data from CoinGecko first, then Yahoo Finance as fallback."""
    print(f"📡 Fetching {symbol} data...")

    symbol_map = {
        "BTC-USD": "bitcoin",
        "ETH-USD": "ethereum",
        "GALA-USD": "gala",
        "XRP-USD": "ripple",
        "ADA-USD": "cardano",
        "DOGE-USD": "dogecoin",
        "SOL-USD": "solana",
        "BNB-USD": "binancecoin"
    }

    coin_id = symbol_map.get(symbol.upper())
    end = pd.Timestamp.now()
    start = end - pd.Timedelta(days=days)

    # --- Primary: CoinGecko ---
    if coin_id:
        print(f"🪙 Trying CoinGecko API for {coin_id}")
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": days, "interval": "hourly"}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            prices = data.get("prices", [])
            if prices:
                df = pd.DataFrame(prices, columns=["timestamp", "Close"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df = df.set_index("timestamp").dropna()
                print(f"✅ Loaded {len(df)} data points from CoinGecko for {symbol}")
                return df
            else:
                print(f"⚠️ CoinGecko returned no data for {symbol}")
        except Exception as e:
            print(f"❌ CoinGecko error for {symbol}: {e}")

    # --- Fallback: Yahoo Finance ---
    print(f"📉 Falling back to Yahoo Finance for {symbol}")
    for attempt in range(3):
        try:
            df = yf.download(
                symbol,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1h",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if not df.empty:
                df = df.dropna()
                print(f"✅ Yahoo Finance data loaded for {symbol} ({len(df)} rows)")
                return df
            else:
                print(f"⚠️ Empty dataframe for {symbol}, retrying ({attempt+1}/3)...")
        except Exception as e:
            print(f"❌ Yahoo error for {symbol}: {e} (attempt {attempt+1}/3)")
        time.sleep(3)

    print(f"🚫 Failed to load data for {symbol} from both sources.")
    return pd.DataFrame()


# === Feature Engineering ===
def build_features(df):
    df["rsi"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    macd = ta.trend.MACD(df["Close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df.dropna(inplace=True)
    return df


# === Signal Generation ===
def generate_signal(df, config):
    latest = df.iloc[-1]
    signal = None

    if latest["rsi"] <= config["rsi_buy"] and latest["macd"] > latest["macd_signal"]:
        signal = "BUY"
    elif latest["rsi"] >= config["rsi_sell"] and latest["macd"] < latest["macd_signal"]:
        signal = "SELL"

    return signal


# === Main process ===
def main():
    print("🧹 Cleared old signal files before run.")
    for file in [LAST_SIGNALS_FILE, SIGNALS_TXT_FILE]:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("{}" if file.suffix == ".json" else "")

    results = {}

    for symbol in CONFIG["symbols"]:
        df = fetch_crypto_data(symbol, CONFIG["lookback_days"])
        if df.empty:
            print(f"⚠️ No data for {symbol}, skipping...")
            continue

        df = build_features(df)
        signal = generate_signal(df, CONFIG)
        results[symbol] = signal or "HOLD"

        if signal in ["BUY", "SELL"]:
            msg = f"{datetime.now():%Y-%m-%d %H:%M} — {symbol}: {signal}"
            print(f"🚨 {msg}")
            with open(SIGNALS_TXT_FILE, "a") as f:
                f.write(msg + "\n")
            send_email_alert(symbol, signal)

    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(results, f, indent=2)

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(results, indent=2))
    print("✅ Bot execution completed.")


if __name__ == "__main__":
    print("🚀 Starting Crypto AI Bot...")
    main()
