import os
import json
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands

# ========== CONFIG ==========
COINS = ["bitcoin", "ethereum", "ripple", "gala"]
SYMBOL_MAP = {
    "bitcoin": "BTC-USD",
    "ethereum": "ETH-USD",
    "ripple": "XRP-USD",
    "gala": "GALA-USD"
}
OUTPUT_JSON = "utils/last_signals.json"
OUTPUT_TXT = "utils/signals.txt"
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

# Lazy import Binance client (only if available)
try:
    from binance.client import Client
except ImportError:
    Client = None


# ========== FETCH FUNCTIONS ==========

def fetch_from_coingecko(coin):
    """Fetch historical data from CoinGecko (90 days, hourly) using API key headers."""
    try:
        print(f"🪙 Trying CoinGecko API for {coin}")
        url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
        params = {
            "vs_currency": "usd",
            "days": "90",
            "interval": "hourly"
        }
        headers = {
            "accept": "application/json",
            "x-cg-pro-api-key": COINGECKO_API_KEY  # ✅ Correct header usage
        }

        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        if "prices" not in data:
            raise ValueError("❌ No 'prices' key in CoinGecko response")

        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["price"].astype(float)
        df.drop(columns=["price"], inplace=True)
        return df

    except requests.exceptions.HTTPError as e:
        print(f"❌ CoinGecko HTTP error for {coin}: {e}")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ CoinGecko connection error for {coin}: {e}")
    except Exception as e:
        print(f"❌ CoinGecko error for {coin}: {e}")
    return None


def fetch_from_binance(symbol):
    """Fetch last 90 days of hourly candles from Binance."""
    if Client is None:
        print("⚠️ Binance library not available.")
        return None
    try:
        print(f"📊 Trying Binance API for {symbol}")
        client = Client()  # Create on demand
        klines = client.get_historical_klines(symbol, Client.KLINE_INTERVAL_1HOUR, "90 days ago UTC")
        if not klines:
            return None
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_asset_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["close"].astype(float)
        return df[["timestamp", "close"]]
    except Exception as e:
        print(f"❌ Binance error for {symbol}: {e}")
        return None


def fetch_from_yahoo(symbol):
    """Fetch last 90 days of hourly data from Yahoo Finance."""
    try:
        print(f"📉 Trying Yahoo Finance for {symbol}")
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="90d", interval="1h")
        if df.empty:
            return None
        df = df.reset_index()[["Datetime", "Close"]]
        df.rename(columns={"Datetime": "timestamp", "Close": "close"}, inplace=True)
        return df
    except Exception as e:
        print(f"❌ Yahoo Finance error for {symbol}: {e}")
        return None


def get_crypto_data(coin):
    """Main fetch function with fallback logic."""
    symbol = SYMBOL_MAP[coin]
    print(f"📡 Fetching {symbol} data...")

    # 1️⃣ Try CoinGecko
    df = fetch_from_coingecko(coin)
    if df is not None and not df.empty:
        return df

    # 2️⃣ Try Binance (remove '-USD' suffix)
    binance_symbol = symbol.replace("-USD", "USDT")
    df = fetch_from_binance(binance_symbol)
    if df is not None and not df.empty:
        return df

    # 3️⃣ Try Yahoo Finance
    df = fetch_from_yahoo(symbol)
    if df is not None and not df.empty:
        return df

    print(f"🚫 Failed to load data for {symbol} from all sources.")
    return None


# ========== SIGNAL GENERATION ==========

def generate_signal(df):
    """Generate BUY/SELL signal based on RSI, MACD, and Bollinger Bands."""
    try:
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
        macd = MACD(df["close"])
        df["macd"] = macd.macd()
        df["signal"] = macd.macd_signal()

        bb = BollingerBands(df["close"])
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()

        latest = df.iloc[-1]
        signal = "HOLD"
        reason = ""

        # Basic rule set
        if latest["rsi"] < 30 and latest["macd"] > latest["signal"]:
            signal = "BUY"
            reason = "RSI oversold + MACD crossover"
        elif latest["rsi"] > 70 and latest["macd"] < latest["signal"]:
            signal = "SELL"
            reason = "RSI overbought + MACD crossover"

        return signal, reason
    except Exception as e:
        print(f"⚠️ Signal generation error: {e}")
        return "HOLD", str(e)


# ========== MAIN EXECUTION ==========

def main():
    print("🚀 Starting Crypto AI Bot...")
    signals = {}

    os.makedirs("utils", exist_ok=True)
    open(OUTPUT_TXT, "w").close()

    for coin in COINS:
        df = get_crypto_data(coin)
        if df is not None and not df.empty:
            signal, reason = generate_signal(df)
            symbol = SYMBOL_MAP[coin]
            signals[symbol] = {"signal": signal, "reason": reason, "time": str(datetime.utcnow())}
            print(f"✅ {symbol}: {signal} ({reason})")

            with open(OUTPUT_TXT, "a") as f:
                f.write(f"{datetime.utcnow()} - {symbol}: {signal} ({reason})\n")
        else:
            print(f"⚠️ No data for {coin}, skipping...")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(signals, f, indent=2)

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(signals, indent=2))
    print("✅ Bot execution completed.")


if __name__ == "__main__":
    main()
