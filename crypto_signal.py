import os
import json
import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands

# === Load settings ===
CONFIG_FILE = "crypto.yml"
UTILS_DIR = "utils"
os.makedirs(UTILS_DIR, exist_ok=True)
SIGNALS_FILE = os.path.join(UTILS_DIR, "signals.txt")
LAST_FILE = os.path.join(UTILS_DIR, "last_signals.json")

# === Load config ===
if os.path.exists(CONFIG_FILE):
    import yaml
    with open(CONFIG_FILE, "r") as f:
        cfg = yaml.safe_load(f)
    TICKERS = cfg.get("tickers", ["BTC-USD", "ETH-USD"])
    LOOKBACK = cfg.get("lookback_days", 90)
    INTERVAL = cfg.get("interval", "1h")
else:
    print("⚠️ crypto.yml not found — using defaults.")
    TICKERS = ["BTC-USD", "ETH-USD"]
    LOOKBACK = 90
    INTERVAL = "1h"

# === Env vars ===
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
API_BASE = "https://api.coingecko.com/api/v3/simple/price"

# === Helpers ===
def fetch_from_coingecko(symbol):
    """Fetch simple price data for 90 days from CoinGecko"""
    mapping = {
        "BTC-USD": "bitcoin",
        "ETH-USD": "ethereum",
        "XRP-USD": "ripple",
        "GALA-USD": "gala"
    }
    coin = mapping.get(symbol, symbol.lower().replace("-usd", ""))
    print(f"🪙 Trying CoinGecko API for {coin}")
    try:
        url = (
            f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
            f"?vs_currency=usd&days={LOOKBACK}&interval=hourly&x_cg_demo_api_key={COINGECKO_API_KEY}"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "prices" not in data:
            return None
        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        print(f"❌ CoinGecko error for {symbol}: {e}")
        return None


def fetch_from_binance(symbol):
    """Try Binance API fallback"""
    print(f"📡 Trying Binance API for {symbol}")
    pair = symbol.replace("-USD", "USDT")
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval=1h&limit=1000"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data, columns=[
            "time", "open", "high", "low", "close", "volume",
            "_", "_", "_", "_", "_", "_"
        ])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df.set_index("time", inplace=True)
        df["price"] = df["close"].astype(float)
        return df[["price"]]
    except Exception as e:
        print(f"❌ Binance error for {symbol}: {e}")
        return None


def fetch_from_yahoo(symbol):
    """Try Yahoo Finance fallback"""
    print(f"📉 Falling back to Yahoo Finance for {symbol}")
    try:
        df = yf.download(symbol, period=f"{LOOKBACK}d", interval="1h", progress=False)
        if df.empty:
            return None
        df = df.rename(columns={"Close": "price"})
        return df[["price"]]
    except Exception as e:
        print(f"❌ Yahoo error for {symbol}: {e}")
        return None


def get_data(symbol):
    """Get data from multiple sources"""
    for fetcher in [fetch_from_coingecko, fetch_from_binance, fetch_from_yahoo]:
        df = fetcher(symbol)
        if df is not None and not df.empty:
            return df
    print(f"🚫 Failed to load data for {symbol} from all sources.")
    return None


def generate_signals(df):
    """Generate BUY/SELL signals"""
    df["rsi"] = RSIIndicator(df["price"]).rsi()
    macd = MACD(df["price"])
    df["macd"] = macd.macd()
    df["signal"] = macd.macd_signal()
    bb = BollingerBands(df["price"])
    df["bb_low"] = bb.bollinger_lband()
    df["bb_high"] = bb.bollinger_hband()

    latest = df.iloc[-1]
    if latest["rsi"] < 30 and latest["macd"] > latest["signal"] and latest["price"] < latest["bb_low"]:
        return "BUY"
    elif latest["rsi"] > 70 and latest["macd"] < latest["signal"] and latest["price"] > latest["bb_high"]:
        return "SELL"
    return "HOLD"


# === Main ===
signals = {}
for symbol in TICKERS:
    print(f"📡 Fetching {symbol} data...")
    df = get_data(symbol)
    if df is not None and not df.empty:
        signal = generate_signals(df)
        signals[symbol] = signal
        print(f"✅ {symbol} → {signal}")
    else:
        print(f"⚠️ No data for {symbol}, skipping...")

# === Save results ===
with open(LAST_FILE, "w") as f:
    json.dump(signals, f, indent=2)

with open(SIGNALS_FILE, "w") as f:
    for k, v in signals.items():
        f.write(f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} {k}: {v}\n")

print("✅ Bot execution completed.")
