#!/usr/bin/env python3
"""
crypto_signal.py

- Loads utils/summary.json (created by crypto_ai_backtest_multi.py) if present.
- If summary.json has BUY/SELL -> notify (Zapier primary, SMTP fallback).
- If summary.json is missing or empty, computes signals itself:
    * Fetch historical series via CoinGecko market_chart (primary) or yfinance (fallback)
    * Compute technical indicators (RSI, MACD, Bollinger)
    * Try ML model (crypto_ai_model.pkl) if present (root or utils)
    * Combine ML + technical rules to decide BUY/SELL/HOLD
- Writes outputs to utils/{signals.txt, holds.txt, last_signals.json, summary.json}
- Uses utils/notify.py for webhook/email
"""
import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf
import joblib
import ta

# local notify helper
from utils.notify import send_to_zapier, send_email_fallback

# ---------- CONFIG ----------
UTILS = Path("utils")
UTILS.mkdir(exist_ok=True)
SIGNALS_TXT = UTILS / "signals.txt"
HOLDS_TXT = UTILS / "holds.txt"
LAST_SIGNALS_JSON = UTILS / "last_signals.json"
SUMMARY_JSON = UTILS / "summary.json"

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")  # used by utils.notify
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

SYMBOLS = ["BTC", "ETH", "XRP", "GALA"]  # use same list as before
ID_MAP = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "GALA": "gala"}
MODEL_CANDIDATES = ["crypto_ai_model.pkl", str(UTILS / "crypto_ai_model.pkl")]

# time window (hours/days)
CG_DAYS = 90
YFIN_PERIOD = "90d"
YFIN_INTERVAL = "1h"

# ---------- UTILITIES ----------
def write_line(path: Path, text: str):
    with open(path, "a") as f:
        f.write(text + "\n")

def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2))

def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

# ---------- FETCHING HISTORICAL SERIES ----------
def fetch_history_coingecko(coin_id: str, days: int = CG_DAYS):
    """Return DataFrame with columns ['timestamp','close'] from CoinGecko market_chart."""
    try:
        headers = {"accept": "application/json"}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY

        url = "https://api.coingecko.com/api/v3/coins/{id}/market_chart".format(id=coin_id)
        params = {"vs_currency": "usd", "days": str(days), "interval": "hourly"}
        r = requests.get(url, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()
        if "prices" not in data:
            return None
        df = pd.DataFrame(data["prices"], columns=["timestamp", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        print(f"⚠️ CoinGecko fetch error for {coin_id}: {e}")
        return None

def fetch_history_yfinance(symbol: str, period: str = YFIN_PERIOD, interval: str = YFIN_INTERVAL):
    """Return DataFrame with index timestamp and column 'close'."""
    try:
        t = yf.Ticker(symbol + "-USD")
        df = t.history(period=period, interval=interval)
        if df.empty:
            return None
        df = df.reset_index()[["Datetime", "Close"]].rename(columns={"Datetime": "timestamp", "Close": "close"})
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        return df
    except Exception as e:
        print(f"⚠️ yfinance fetch error for {symbol}: {e}")
        return None

# ---------- SIGNAL COMPUTATION ----------
def compute_technical_signals(df):
    """Return dict with latest technical values and a simple entry/exit boolean."""
    out = {}
    try:
        # Ensure column name 'close'
        if "close" not in df.columns and "Close" in df.columns:
            df = df.rename(columns={"Close": "close"})
        s = df["close"].astype(float)

        # RSI
        rsi = ta.momentum.RSIIndicator(s, window=14).rsi()
        # MACD
        macd_obj = ta.trend.MACD(s)
        macd = macd_obj.macd()
        macd_signal = macd_obj.macd_signal()
        # Bollinger
        bb = ta.volatility.BollingerBands(s)
        bb_high = bb.bollinger_hband()
        bb_low = bb.bollinger_lband()

        out["rsi"] = float(rsi.iloc[-1]) if not rsi.isna().all() else None
        out["macd"] = float(macd.iloc[-1]) if not macd.isna().all() else None
        out["macd_signal"] = float(macd_signal.iloc[-1]) if not macd_signal.isna().all() else None
        out["bb_high"] = float(bb_high.iloc[-1]) if not bb_high.isna().all() else None
        out["bb_low"] = float(bb_low.iloc[-1]) if not bb_low.isna().all() else None

        # entry: close <= bb_low
        out["entry"] = bool(s.iloc[-1] <= out["bb_low"]) if out["bb_low"] else False
        # exit: close >= bb_high
        out["exit"] = bool(s.iloc[-1] >= out["bb_high"]) if out["bb_high"] else False
        out["close"] = float(s.iloc[-1])
    except Exception as e:
        print(f"⚠️ compute_technical_signals error: {e}")
    return out

def load_model():
    for p in MODEL_CANDIDATES:
        if Path(p).exists():
            try:
                model = joblib.load(p)
                print("✅ ML model loaded from", p)
                return model
            except Exception as e:
                print("⚠️ Failed to load model at", p, ":", e)
    return None

def decide_signal(tech, ml_pred=None):
    """
    Combine ML prediction (if available) and technical signals.
    Rules:
      - If ML predicts 1 (bull) AND technical entry -> BUY
      - Else if technical exit -> SELL
      - Else -> HOLD
    """
    try:
        if ml_pred is not None and ml_pred == 1 and tech.get("entry"):
            return "BUY"
        if tech.get("exit"):
            return "SELL"
    except Exception as e:
        print("⚠️ decide_signal error:", e)
    return "HOLD"

# ---------- MAIN PROCESS ----------
def main():
    print("🚀 crypto_signal.py starting:", datetime.utcnow().isoformat())

    # load summary if predictor produced it
    summary = load_json(SUMMARY_JSON)

    # If summary exists and contains BUY/SELL, use it directly
    actionable_present = False
    if isinstance(summary, dict) and (summary.get("BUY") or summary.get("SELL")):
        actionable_present = True

    # If no actionable summary, compute signals locally (will still respect ML model if present)
    if not actionable_present:
        print("ℹ️ No actionable summary.json found — computing signals locally.")
        # clear outputs for fresh run
        open(SIGNALS_TXT, "w").close()
        open(HOLDS_TXT, "w").close()

        model = load_model()
        last_signals = load_json(LAST_SIGNALS_JSON)
        summary = {"BUY": [], "SELL": [], "HOLD": []}
        new_last = {}

        for sym in SYMBOLS:
            coin_id = ID_MAP.get(sym, sym.lower())
            df = fetch_history_coingecko(coin_id)
            if df is None or df.empty:
                df = fetch_history_yfinance(sym)
            if df is None or df.empty:
                print(f"⚠️ No data for {sym}, skipping.")
                continue

            tech = compute_technical_signals(df)
            ml_pred = None
            if model is not None:
                # build features for model: we'll try to match training features if present
                try:
                    # simplest: compute feature vector from latest row
                    feat = {
                        "rsi": tech.get("rsi"),
                        "macd": tech.get("macd"),
                        "bb_high": tech.get("bb_high"),
                        "bb_low": tech.get("bb_low"),
                        "bb_width": (tech.get("bb_high") - tech.get("bb_low")) / tech.get("close") if tech.get("bb_high") and tech.get("bb_low") and tech.get("close") else 0,
                        "percent_b": (tech.get("close") - tech.get("bb_low")) / (tech.get("bb_high") - tech.get("bb_low")) if tech.get("bb_high") and tech.get("bb_low") else 0,
                        "volume_change": 0.0,
                        "shooting_star": 0,
                        "hammer": 0
                    }
                    X = pd.DataFrame([feat]).fillna(0)
                    ml_pred = int(model.predict(X)[0])
                except Exception as e:
                    print("⚠️ ML prediction failed:", e)
                    ml_pred = None

            sig = decide_signal(tech, ml_pred)
            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            price = tech.get("close") or None
            entry = {"symbol": sym, "signal": sig, "price": price, "time": ts}
            # write files
            if sig in ("BUY", "SELL"):
                write_line(SIGNALS_TXT, f"{ts} | {sym} | {sig} | ${price:.6f}" if price else f"{ts} | {sym} | {sig}")
                summary.setdefault(sig, []).append(entry)
            else:
                write_line(HOLDS_TXT, f"{ts} | {sym} | {sig} | ${price:.6f}" if price else f"{ts} | {sym} | {sig}")
                summary.setdefault("HOLD", []).append(entry)

            new_last[sym] = {"signal": sig, "price": price, "time": ts}

        # save summary and last_signals.json
        save_json(SUMMARY_JSON, summary)
        save_json(LAST_SIGNALS_JSON, new_last)
        print("ℹ️ Local computation complete; summary.json and last_signals.json written.")

    else:
        # summary.json already produced by predictor — ensure signals/holds reflect it
        print("ℹ️ Using predictor's summary.json")
        # normalize and write text files
        open(SIGNALS_TXT, "w").close()
        open(HOLDS_TXT, "w").close()
        last = {}
        for group in ("BUY", "SELL", "HOLD"):
            for item in summary.get(group, []):
                ts = item.get("time") or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                sym = item.get("symbol")
                price = item.get("price")
                sig = group
                if sig in ("BUY", "SELL"):
                    write_line(SIGNALS_TXT, f"{ts} | {sym} | {sig} | ${price:.6f}" if price else f"{ts} | {sym} | {sig}")
                else:
                    write_line(HOLDS_TXT, f"{ts} | {sym} | {sig} | ${price:.6f}" if price else f"{ts} | {sym} | {sig}")
                last[sym] = {"signal": sig, "price": price, "time": ts}
        save_json(LAST_SIGNALS_JSON, last)
        print("ℹ️ summary.json processed; text files and last_signals.json updated.")

    # ---------- Notifications ----------
    # Only notify if any BUY or SELL exist
    summary = load_json(SUMMARY_JSON)
    buy_count = len(summary.get("BUY", []))
    sell_count = len(summary.get("SELL", []))
    if buy_count + sell_count == 0:
        print("🕊 No BUY/SELL signals => no notifications sent.")
        return

    print(f"🚨 Found {buy_count} BUY and {sell_count} SELL signals — sending to Zapier (primary) ...")
    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "Crypto AI Bot",
        "summary": summary
    }

    zap_ok = send_to_zapier(payload)
    if not zap_ok:
        print("⚠️ Zapier send failed — attempting SMTP fallback email.")
        send_email_fallback(summary)

    print("✅ Notification flow completed.")

if __name__ == "__main__":
    main()
