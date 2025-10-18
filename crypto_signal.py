import os
import json
import smtplib
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from email.mime.text import MIMEText
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
from datetime import datetime

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
OUTPUT_HOLD = "utils/holds.txt"

ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")


# ========== FETCH DATA ==========
def fetch_yahoo(symbol):
    try:
        print(f"📉 Fetching Yahoo Finance for {symbol}")
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="90d", interval="1h")
        if df.empty:
            return None
        df = df.reset_index()[["Datetime", "Close"]]
        df.rename(columns={"Datetime": "timestamp", "Close": "close"}, inplace=True)
        return df
    except Exception as e:
        print(f"⚠️ Yahoo Finance error for {symbol}: {e}")
        return None


# ========== TECHNICAL SIGNAL ==========
def generate_signal(df):
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

        if latest["rsi"] < 30 and latest["macd"] > latest["signal"]:
            signal = "BUY"
            reason = "RSI oversold + MACD crossover"
        elif latest["rsi"] > 70 and latest["macd"] < latest["signal"]:
            signal = "SELL"
            reason = "RSI overbought + MACD crossover"

        return signal, reason
    except Exception as e:
        return "HOLD", str(e)


# ========== NOTIFICATIONS ==========
def send_notification(msg):
    """Send notification via Zapier webhook, fallback to email."""
    if ZAPIER_WEBHOOK_URL:
        try:
            r = requests.post(ZAPIER_WEBHOOK_URL, json={"text": msg}, timeout=10)
            if r.status_code == 200:
                print("✅ Notification sent via Zapier.")
                return
            else:
                print(f"⚠️ Zapier webhook failed: {r.status_code}")
        except Exception as e:
            print(f"⚠️ Zapier webhook error: {e}")

    # Fallback to email
    if EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_TO:
        try:
            msg_obj = MIMEText(msg)
            msg_obj["Subject"] = "Crypto AI Signal Alert"
            msg_obj["From"] = EMAIL_SENDER
            msg_obj["To"] = EMAIL_TO
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_TO, msg_obj.as_string())
            print("📧 Email notification sent.")
        except Exception as e:
            print(f"❌ Email send error: {e}")


# ========== MAIN ==========
def main():
    print("🚀 Starting Crypto AI Bot...")
    signals = {}
    os.makedirs("utils", exist_ok=True)
    open(OUTPUT_TXT, "w").close()
    open(OUTPUT_HOLD, "w").close()

    # Load AI predictions if available
    ai_preds = {}
    if os.path.exists("utils/predictions.json"):
        with open("utils/predictions.json") as f:
            ai_preds = json.load(f)
        print(f"🧠 Loaded AI predictions for {len(ai_preds)} coins.")
    else:
        print("⚠️ No AI predictions found — proceeding with TA only.")

    buy_sell_msgs = []

    for coin in COINS:
        symbol = SYMBOL_MAP[coin]
        df = fetch_yahoo(symbol)
        if df is None or df.empty:
            print(f"⚠️ No data for {symbol}, skipping...")
            continue

        ta_signal, reason = generate_signal(df)
        ai_signal = ai_preds.get(symbol, {}).get("pred", "HOLD")

        # Combine TA + AI
        if ta_signal == ai_signal and ta_signal in ["BUY", "SELL"]:
            final_signal = ta_signal
            reason += f" | AI confirmed ({ai_signal})"
        elif ai_signal in ["BUY", "SELL"] and ta_signal == "HOLD":
            final_signal = ai_signal
            reason += f" | AI override ({ai_signal})"
        else:
            final_signal = "HOLD"

        signals[symbol] = {
            "signal": final_signal,
            "reason": reason,
            "time": str(datetime.utcnow())
        }

        line = f"{datetime.utcnow()} - {symbol}: {final_signal} ({reason})"
        if final_signal in ["BUY", "SELL"]:
            buy_sell_msgs.append(line)
            with open(OUTPUT_TXT, "a") as f:
                f.write(line + "\n")
        else:
            with open(OUTPUT_HOLD, "a") as f:
                f.write(line + "\n")

        print(f"✅ {symbol}: {final_signal} ({reason})")

    with open(OUTPUT_JSON, "w") as f:
        json.dump(signals, f, indent=2)

    if buy_sell_msgs:
        send_notification("\n".join(buy_sell_msgs))

    print("📊 ===== SIGNAL SUMMARY =====")
    print(json.dumps(signals, indent=2))
    print("✅ Bot execution completed.")


if __name__ == "__main__":
    main()
