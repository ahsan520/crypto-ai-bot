#!/usr/bin/env python3
import os
import smtplib
import requests
import json
from email.mime.text import MIMEText
from datetime import datetime

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SIGNAL_EMAIL = os.getenv("SIGNAL_EMAIL")
ZAPIER_URL = os.getenv("ZAPIER_URL")

def generate_signal():
    now = datetime.utcnow()
    signal = "BUY" if now.minute % 2 == 0 else "SELL"
    price = 68000 + (1 if signal == "BUY" else -1) * 50
    message = f"{datetime.now():%Y-%m-%d %H:%M:%S} UTC: {signal} BTC @ ${price}"
    print("📈 Generated signal:", message)
    return message, signal

def send_email(subject, body):
    if not (SMTP_USER and SMTP_PASS and SIGNAL_EMAIL):
        print("⚠️ Email not configured.")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = SIGNAL_EMAIL
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, SIGNAL_EMAIL, msg.as_string())
        print("✅ Email sent.")
    except Exception as e:
        print(f"⚠️ Email failed: {e}")

def send_zapier_notification(message):
    if not ZAPIER_URL:
        print("⚠️ No Zapier URL configured.")
        return
    try:
        r = requests.post(ZAPIER_URL, json={"text": message}, timeout=10)
        if r.status_code == 200:
            print("✅ Zapier notification sent.")
        else:
            print(f"⚠️ Zapier responded with {r.status_code}: {r.text}")
    except Exception as e:
        print(f"⚠️ Zapier failed: {e}")

def save_signal_file(message, signal):
    with open("signals.txt", "w") as f:
        f.write(message + "\n")
    with open("last_signal.json", "w") as f:
        json.dump({"signal": signal, "timestamp": datetime.now().isoformat()}, f)
    print("📁 Saved signals.txt and last_signal.json.")

def main():
    print("🚀 Starting Crypto Bot...")
    msg, signal = generate_signal()
    save_signal_file(msg, signal)
    send_zapier_notification(msg)
    send_email(f"Crypto Signal Alert: {signal}", msg)
    print("✅ Done.")

if __name__ == "__main__":
    main()
