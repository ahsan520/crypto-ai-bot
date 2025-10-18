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

# ======================
# 🔧 Configuration
# ======================
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
SIGNALS_FILE = "utils/signals.txt"
LAST_SIGNALS_FILE = "utils/last_signals.json"

COINS = ["BTC-USD", "ETH-USD", "XRP-USD", "GALA-USD"]

# ======================
# ⚙️ Helper: fetch from CoinGecko
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
# ⚙️ Helper: fetch from Binance
# ======================
def fetch_from_binance(symbol, retries=3):
    binance_map = {
        "BTC-USD": "BTCUSDT",
        "ETH-USD": "ETHUSDT",
        "XRP-USD": "XRPUSDT",
        "GALA-USD": "GALAUSDT"
    }

    pair = binance_map.get(symbol)
    if not pair:
        print(f"⚠️ No Binance mapping for {symbol}")
        return None

    url = f"https://api.binance.com/api/v3/klines"
    params = {"symbol": pair, "interval": "1h", "limit": 500}

    print(f"🏦 Trying Binance API for {pair}")
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if not data:
                print(f"⚠️ Empty Binance response for {symbol}, retry {attempt+1}/{retries}")
                time.sleep(2)
                continue

            df = pd.DataFrame(
                data,
                columns=[
                    "timestamp", "Open", "High", "Low", "Close", "Volume",
                    "Close_time", "Quote_asset_volume", "Trades",
                    "TBBAV", "TBQAV", "ignore"
                ],
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df["Close"] = df["Close"].astype(float)
            print(f"✅ Successfully fetched {symbol} data from Binance")
            return df[["Close"]]

        except Exception as e:
            print(f"⚠️ Binance error for {symbol}: {e}")
            time.sleep(2)

    print(f"🚫 Failed to fetch data from Binance for {symbol}")
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
