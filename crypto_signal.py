import os
import json
import smtplib
import pandas as pd
import requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === Load Config ===
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

utils_dir = "utils"
os.makedirs(utils_dir, exist_ok=True)

signals_file = os.path.join(utils_dir, "signals.txt")
holds_file = os.path.join(utils_dir, "holds.txt")
last_signals_file = os.path.join(utils_dir, "last_signals.json")

# === Universal Save Helpers ===
def save_signal(signal_type, content):
    file_path = signals_file if signal_type in ["BUY", "SELL"] else holds_file
    with open(file_path, "a") as f:
        f.write(content + "\n")

def load_last_signals():
    if os.path.exists(last_signals_file):
        with open(last_signals_file, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_last_signals(data):
    with open(last_signals_file, "w") as f:
        json.dump(data, f, indent=2)

# === Email Fallback ===
def send_email(subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("📧 Email sent successfully.")
    except Exception as e:
        print(f"❌ Email send failed: {e}")

# === Webhook Notification ===
def send_to_zapier(payload):
    if not ZAPIER_WEBHOOK_URL:
        print("⚠️ No Zapier webhook URL configured.")
        return False
    try:
        r = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=10)
        if r.status_code == 200:
            print("✅ Sent to Zapier webhook.")
            return True
        else:
            print(f"⚠️ Zapier returned status {r.status_code}")
            return False
    except Exception as e:
        print(f"❌ Webhook failed: {e}")
        return False

# === Price Fetching (CoinGecko API → Binance → Yahoo) ===
def fetch_price(symbol):
    symbol = symbol.upper()

    # --- CoinGecko with API Key ---
    try:
        headers = {"accept": "application/json"}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY

        # Map common tickers to CoinGecko IDs
        gecko_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "ADA": "cardano",
            "DOGE": "dogecoin",
            "GALA": "gala"
        }

        if symbol in gecko_map:
            resp = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price",
                params={"ids": gecko_map[symbol], "vs_currencies": "usd"},
                headers=headers,
                timeout=10
            )
            data = resp.json()
            if gecko_map[symbol] in data:
                return float(data[gecko_map[symbol]]["usd"])
    except Exception as e:
        print(f"⚠️ CoinGecko failed for {symbol}: {e}")

    # --- Binance fallback ---
    try:
        resp = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT", timeout=10)
        data = resp.json()
        if "price" in data:
            return float(data["price"])
    except Exception as e:
        print(f"⚠️ Binance failed for {symbol}: {e}")

    # --- Yahoo Finance fallback ---
    try:
        resp = requests.get(f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={symbol}-USD", timeout=10)
        data = resp.json()
        return float(data["quoteResponse"]["result"][0]["regularMarketPrice"])
    except Exception as e:
        print(f"⚠️ Yahoo failed for {symbol}: {e}")

    print(f"❌ Could not fetch price for {symbol}")
    return None

# === Simple AI-Like Logic ===
def analyze_symbol(symbol, prices):
    if len(prices) < 3:
        return "HOLD"

    short_ma = sum(prices[-3:]) / 3
    long_ma = sum(prices) / len(prices)

    if short_ma > long_ma * 1.02:
        return "BUY"
    elif short_ma < long_ma * 0.98:
        return "SELL"
    else:
        return "HOLD"

# === Main Bot Logic ===
def main():
    print("🚀 Starting Crypto AI Bot...")

    symbols = ["BTC", "ETH", "ADA", "DOGE", "GALA"]
    last_signals = load_last_signals()
    new_signals = {}

    for sym in symbols:
        print(f"📊 Checking {sym}...")
        price = fetch_price(sym)
        if price is None:
            continue

        prices = last_signals.get(sym, {}).get("history", [])
        prices.append(price)
        if len(prices) > 20:
            prices = prices[-20:]

        signal = analyze_symbol(sym, prices)
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        entry = f"{timestamp} | {sym} | {signal} | ${price:.4f}"
        new_signals[sym] = {"signal": signal, "price": price, "time": timestamp, "history": prices}

        save_signal(signal, entry)
        print(entry)

        # Send notifications for BUY/SELL only
        if signal in ["BUY", "SELL"]:
            payload = {"symbol": sym, "signal": signal, "price": price, "time": timestamp}
            sent = send_to_zapier(payload)
            if not sent:
                send_email(f"{signal} ALERT: {sym}", f"{sym} is now {signal} at ${price:.4f}")

    save_last_signals(new_signals)
    print("✅ Signals updated.")

if __name__ == "__main__":
    main()
