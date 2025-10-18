import os
import json
import yaml
import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np
import ta
import joblib
from pathlib import Path

# ------------------------------------------------------------
# 🧹 AUTO CLEANUP OF OLD SIGNAL FILES (Option 1 - Always Fresh Start)
# ------------------------------------------------------------
ROOT_DIR = Path(__file__).parent
UTILS_DIR = ROOT_DIR / "utils"
UTILS_DIR.mkdir(exist_ok=True)

LAST_SIGNALS_FILE = UTILS_DIR / "last_signals.json"
SIGNALS_TXT = UTILS_DIR / "signals.txt"

# Clear last_signals.json
try:
    with open(LAST_SIGNALS_FILE, "w") as f:
        json.dump({}, f)
    print("🧹 Cleared contents of last_signals.json before run.")
except Exception as e:
    print("⚠️ Failed to clear last_signals.json:", e)

# Clear signals.txt
try:
    with open(SIGNALS_TXT, "w") as f:
        f.write("")
    print("🧾 Cleared contents of signals.txt before run.")
except Exception as e:
    print("⚠️ Failed to clear signals.txt:", e)

# ------------------------------------------------------------
# 📦 CONFIGURATION & SETUP
# ------------------------------------------------------------
CONFIG_FILE = ROOT_DIR / "crypto.yml"
MODEL_FILE = UTILS_DIR / "crypto_ai_model.pkl"

CONFIG_DEFAULTS = {
    "symbols": ["BTC-USD", "GALA-USD", "XRP-USD"],
    "interval": "30m",
    "period": "60d",
    "atr_window": 14,
    "atr_multiplier": 1.5,
}

# Load YAML config if available
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, "r") as f:
        config_data = yaml.safe_load(f) or {}
else:
    print("⚠️ crypto.yml not found — using defaults.")
    config_data = {}

config = {**CONFIG_DEFAULTS, **config_data}

# Environment variables
ZAPIER_URL = os.getenv("ZAPIER_URL")
SIGNAL_EMAIL = os.getenv("SIGNAL_EMAIL")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
