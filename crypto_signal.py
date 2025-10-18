import os
import json
import smtplib
import requests
import pandas as pd
import yfinance as yf
from email.mime.text import MIMEText
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
    "gala": "GALA-USD",
}

# Paths
os.makedirs("utils/signals", exist_ok=True)
OUTPUT_JSON = "utils/last_signals.json"
SIGNAL_TXT = "utils/signals/signals.txt"
HOLD_TXT = "utils/signals/holds.txt"

# API Keys and Secrets
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
ZAPIER_URL = os.getenv("ZAPIER_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

# Lazy import Binance client (optional)
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

        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()

        if "prices" not in data:
            raise ValueError("Missing 'prices' key")

        df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["price"].astype(float)
        return df[["timestamp", "close"]]
    except Exception as e:
        print(f"❌ CoinGecko error for {coin}: {e}")
        return None


def fetch_from_binance(symbol):
    """Fetch hourly data from Binance."""
    if Client is None:
        return None
    try:
        print(f"📊 Trying Binance API for {symbol}")
        client = Client()
        klines = client.get_historical_klines(
            symbol, Client.KLINE_INTERVAL_1HOUR, "90 days ago UTC"
        )
        df = pd.DataFrame(
            klines,
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "trades",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["close"].astype(float)
        return df[["timestamp", "close"]]
    except Exception as e:
        print(f"❌ Binance error for {symbol}: {e}")
        return None


def fetch_from_yahoo(symbol):
    """Fetch hourly data from Yahoo Finance."""
    try:
        print(f"📉 Trying Yahoo Finance for {symbol}")
        df = yf.Ticker(symbol).history(period="90d", interval="1h")
        if df.empty:
            return None
        df = df.reset_index()[["Datetime", "Close"]]
        df.rename(columns={"Datetime": "timestamp", "Close": "close"}, inplace=True)
        return df
    except Exception as e:
        print(f"❌ Yahoo error for {symbol}: {e}")
        return None


def get_crypto_data(coin):
    """Try CoinGecko, Binance, then Yahoo Finance."""
    symbol = SYMBOL_MAP[coin]
    print(f"📡 Fetching {symbol} data...")

    df = fetch_from_coingecko(coin)
    if df is not None and not df.empty:
        return df

    df = fetch_from_binance(symbol.replace("-USD", "USDT"))
    if df is not None and not df.empty:
        return df

    df = fetch_from_yahoo(symbol)
    if df is not None and not df.empty:
        return df

    print(f"🚫 Failed to load data for {symbol}.")
    return None


# ========== SIGNAL LOGIC ==========
def generate_signal(df):
    """Generate BUY/SELL/HOLD signals."""
    try:
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
        macd = MACD(df["close"])
        df["macd"], df["signal"] = macd.macd(), macd.macd_signal()

        bb = BollingerBands(df["close"])
        df["bb_high"], df["bb_low"] = bb.bollinger_hband(), bb.bollinger_lband()

        latest = df.iloc[-1]
        signal, reason = "HOLD", ""

        if latest["rsi"] < 30 and latest["macd"] > latest["signal"]:
            signal, reason = "BUY", "RSI oversold + MACD crossover"
        elif latest["rsi"] > 70 and latest["macd"] < latest["signal"]:
            signal, reason = "SELL", "RSI overbought + MACD crossover"

        return signal, reason
    except Exception as e:
        return "HOLD", f"Signal error: {e}"


# ========== ALERT FUNCTIONS ==========
def send_webhook(data):
    """Send signal via Zapier webhook."""
    if not ZAPIER_URL:
        print("⚠️ ZAPIER_URL not configured.")
        return False
    try:
        response = requests.post(ZAPIER_URL, json=data, timeout=15)
        print(f"🌐 Webhook status: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return False


def send_email(subject, body):
    """Send email alert as fallback."""
    try:
        if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_TO]):
            print("⚠️ Email not fully configured.")
            return False

        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_TO

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("📧 Email sent successfully.")
        return True
    except Exception as e:
        print(f"❌ Email send error: {e}")
        return False


# ========== MAIN ==========
def main():
    print("🚀 Starting Crypto AI Bot...")
    signals = {}

    # Prepare output files
    open(SIGNAL_TXT, "w").close()
    with open(HOLD_TXT, "a") as hf:
        hf.write(f"\n🕒 Run: {datetime.utcnow()} UTC\n")

    buy_sell_found = False

    for coin in COINS:
        df = get_crypto_data(coin)
        if df is None or df.empty:
            print(f"⚠️ No data for {coin}, skipping.")
            continue

        signal, reason = generate_signal(df)
        symbol = SYMBOL_MAP[coin]
        signals[symbol] = {
            "signal": signal,
            "reason": reason,
            "time": str(datetime.utcnow()),
        }

        line = f"{datetime.utcnow()} - {symbol}: {signal} ({reason})\n"

        if signal in ["BUY", "SELL"]:
            buy_sell_found = True
            with open(SIGNAL_TXT, "a") as f:
                f.write(line)
        else:
            with open(HOLD_TXT, "a") as f:
                f.write(line)

        print(f"✅ {symbol}: {signal} ({reason})")

    # Save all signals to JSON
    with open(OUTPUT_JSON, "w") as f:
        json.dump(signals, f, indent=2)

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(signals, indent=2))

    # Trigger alert if BUY/SELL found
    if buy_sell_found:
        print("🚨 BUY/SELL detected! Sending alerts...")
        alert_data = {"time": str(datetime.utcnow()), "signals": signals}
        if not send_webhook(alert_data):
            print("⚠️ Webhook failed — sending email fallback.")
            send_email("Crypto AI Alert", json.dumps(alert_data, indent=2))
    else:
        print("🟢 No BUY/SELL signals — only HOLD this round.")

    print("✅ Bot execution completed.")


if __name__ == "__main__":
    main()
