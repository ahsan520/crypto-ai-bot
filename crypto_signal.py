import os
import json
import time
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
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
SIGNAL_TXT = "utils/signals/signals.txt"  # BUY/SELL only
HOLD_TXT = "utils/signals/holds.txt"      # HOLD only
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
ZAPIER_URL = os.getenv("ZAPIER_URL")

# Optional Binance
try:
    from binance.client import Client
except ImportError:
    Client = None


# ========== FETCH FUNCTIONS ==========

def fetch_from_coingecko(coin):
    """Fetch historical data from CoinGecko (90 days, hourly)."""
    try:
        print(f"🪙 Trying CoinGecko API for {coin}")
        url = f"https://api.coingecko.com/api/v3/coins/{coin}/market_chart"
        params = {"vs_currency": "usd", "days": "90", "interval": "hourly"}
        headers = {"accept": "application/json", "x-cg-pro-api-key": COINGECKO_API_KEY}

        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        if "prices" not in data:
            raise ValueError("Missing 'prices' in response")

        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["price"].astype(float)
        df.drop(columns=["price"], inplace=True)
        return df

    except Exception as e:
        print(f"❌ CoinGecko error for {coin}: {e}")
        return None


def fetch_from_binance(symbol):
    """Fetch last 90 days of hourly candles from Binance."""
    if Client is None:
        return None
    try:
        print(f"📊 Trying Binance API for {symbol}")
        client = Client()
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
    """Fetch data with multiple fallback sources."""
    symbol = SYMBOL_MAP[coin]
    print(f"📡 Fetching {symbol} data...")

    df = fetch_from_coingecko(coin)
    if df is not None and not df.empty:
        return df

    binance_symbol = symbol.replace("-USD", "USDT")
    df = fetch_from_binance(binance_symbol)
    if df is not None and not df.empty:
        return df

    df = fetch_from_yahoo(symbol)
    if df is not None and not df.empty:
        return df

    print(f"🚫 Failed to load data for {symbol}")
    return None


# ========== SIGNAL GENERATION ==========

def generate_signal(df):
    """Generate BUY/SELL/HOLD signal using RSI, MACD, Bollinger Bands."""
    try:
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
        macd = MACD(df["close"])
        df["macd"] = macd.macd()
        df["signal_line"] = macd.macd_signal()

        bb = BollingerBands(df["close"])
        df["bb_high"] = bb.bollinger_hband()
        df["bb_low"] = bb.bollinger_lband()

        latest = df.iloc[-1]
        signal, reason = "HOLD", "Neutral market"

        if latest["rsi"] < 30 and latest["macd"] > latest["signal_line"]:
            signal, reason = "BUY", "RSI oversold + MACD bullish crossover"
        elif latest["rsi"] > 70 and latest["macd"] < latest["signal_line"]:
            signal, reason = "SELL", "RSI overbought + MACD bearish crossover"

        return signal, reason
    except Exception as e:
        print(f"⚠️ Signal generation error: {e}")
        return "HOLD", str(e)


# ========== MAIN EXECUTION ==========

def main():
    print("🚀 Starting Crypto AI Bot...")
    os.makedirs("utils/signals", exist_ok=True)

    # Reset files
    open(SIGNAL_TXT, "w").close()
    open(HOLD_TXT, "w").close()

    results = {}
    utc_now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    for coin in COINS:
        df = get_crypto_data(coin)
        symbol = SYMBOL_MAP[coin]

        if df is None or df.empty:
            print(f"⚠️ No data for {coin}, skipping...")
            continue

        signal, reason = generate_signal(df)
        results[symbol] = {"signal": signal, "reason": reason, "time": utc_now}
        line = f"{utc_now} - {symbol}: {signal} ({reason})\n"

        if signal in ["BUY", "SELL"]:
            with open(SIGNAL_TXT, "a") as f:
                f.write(line)
        else:
            with open(HOLD_TXT, "a") as f:
                f.write(line)

        print(f"✅ {symbol}: {signal} ({reason})")

    # Save structured output
    with open(OUTPUT_JSON, "w") as f:
        json.dump(results, f, indent=2)

    print("\n📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(results, indent=2))

    # Optional Zapier webhook trigger (primary)
    if ZAPIER_URL and os.path.exists(SIGNAL_TXT) and os.path.getsize(SIGNAL_TXT) > 0:
        try:
            with open(SIGNAL_TXT, "r") as f:
                payload = {"text": f.read()}
            print("🌐 Sending signals to Zapier webhook...")
            r = requests.post(ZAPIER_URL, json=payload, timeout=10)
            if r.status_code >= 200 and r.status_code < 300:
                print(f"✅ Zapier accepted: {r.status_code}")
            else:
                print(f"⚠️ Zapier responded with: {r.status_code}")
        except Exception as e:
            print(f"❌ Failed to send to Zapier: {e}")

    print("🏁 Bot execution completed.")


if __name__ == "__main__":
    main()
