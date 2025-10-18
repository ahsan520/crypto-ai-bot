import os
import json
import yfinance as yf
import pandas as pd
import ta
from datetime import datetime
from utils.helpers import send_alert  # make sure this helper exists

CONFIG = {
    "symbols": ["BTC-USD", "GALA-USD", "XRP-USD"],
    "period": "90d",
    "interval": "1h"
}

UTILS_DIR = "utils"
SIGNALS_FILE = os.path.join(UTILS_DIR, "signals.txt")
LAST_SIGNALS_FILE = os.path.join(UTILS_DIR, "last_signals.json")


# === Ensure utils folder exists ===
os.makedirs(UTILS_DIR, exist_ok=True)

# === Clear contents before run ===
open(SIGNALS_FILE, "w").close()
open(LAST_SIGNALS_FILE, "w").close()
print("🧹 Cleared old signal files before run.")


# === Feature Engineering ===
def build_features(df):
    df["rsi"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
    df["ema_fast"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
    df["ema_slow"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
    df["macd"] = ta.trend.MACD(df["Close"]).macd()
    df.dropna(inplace=True)
    return df


# === Simple AI Decision Model ===
def get_signal(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    if latest["ema_fast"] > latest["ema_slow"] and prev["ema_fast"] <= prev["ema_slow"]:
        return "BUY"
    elif latest["ema_fast"] < latest["ema_slow"] and prev["ema_fast"] >= prev["ema_slow"]:
        return "SELL"
    else:
        return "HOLD"


# === Generate All Signals ===
def generate_signals():
    signals = {}
    for sym in CONFIG["symbols"]:
        try:
            print(f"📡 Downloading {sym} ...")
            df = yf.download(
                sym,
                period=CONFIG["period"],
                interval=CONFIG["interval"],
                progress=False
            ).dropna()

            if df.empty:
                print(f"⚠️ No data for {sym}, skipping.")
                continue

            df = build_features(df)
            signal = get_signal(df)
            signals[sym] = signal
            print(f"✅ {sym}: {signal}")
        except Exception as e:
            print(f"❌ Error fetching {sym}: {e}")
    return signals


# === Save and Notify ===
def save_and_notify(signals):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    last_signals = {}

    # Write signals.txt log
    with open(SIGNALS_FILE, "a") as f:
        for sym, signal in signals.items():
            f.write(f"{timestamp} - {sym}: {signal}\n")
            last_signals[sym] = {"signal": signal, "timestamp": timestamp}

            if signal in ["BUY", "SELL"]:
                print(f"📡 Sending signal '{signal}' for {sym} ...")
                send_alert(sym, signal, source="auto-bot")
                print(f"✅ Alert sent for {sym}: {signal}")

    # Save to last_signals.json
    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump(last_signals, f, indent=2)

    print("\n📊 ===== SIGNAL SUMMARY =====")
    for sym, s in last_signals.items():
        print(f"🪙 {sym}: {s['signal']} at {s['timestamp']}")


# === MAIN ===
if __name__ == "__main__":
    print("🚀 Starting Crypto AI Bot...")
    signals = generate_signals()
    save_and_notify(signals)
    print("✅ Bot execution completed.")
