import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from datetime import datetime

def read_signal():
    """Read BUY/HOLD/SELL signal from last_signal.json or signals.txt"""
    signal = None

    if os.path.exists("last_signal.json"):
        try:
            with open("last_signal.json") as f:
                data = json.load(f)
                signal = str(data.get("signal", "")).strip().upper()
        except Exception as e:
            print(f"⚠️ Error reading last_signal.json: {e}")

    elif os.path.exists("signals.txt"):
        try:
            with open("signals.txt") as f:
                signal = f.read().strip().upper()
        except Exception as e:
            print(f"⚠️ Error reading signals.txt: {e}")

    # Default to NONE if empty or missing
    if not signal:
        signal = "NONE"

    return signal


def send_via_zapier(signal_text):
    zapier_url = os.getenv("ZAPIER_URL")
    if not zapier_url:
        print("⚠️ ZAPIER_URL not set. Skipping Zapier notification.")
        return False

    try:
        payload = {"signal": signal_text}
        print(f"📡 Sending signal '{signal_text}' to Zapier...")
        response = requests.post(zapier_url, json=payload)
        if response.status_code == 200:
            print("✅ Zapier notification sent successfully.")
            return True
        else:
            print(f"⚠️ Zapier responded with {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending to Zapier: {e}")
        return False


def send_via_email(signal_text):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    signal_email = os.getenv("SIGNAL_EMAIL")

    if not smtp_user or not smtp_pass or not signal_email:
        print("⚠️ Missing SMTP credentials. Skipping email notification.")
        return False

    try:
        print(f"📨 Sending email alert: {signal_text}")
        msg = MIMEText(f"Crypto Signal: {signal_text}", "plain")
        msg["Subject"] = f"Crypto Signal: {signal_text}"
        msg["From"] = smtp_user
        msg["To"] = signal_email

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        print("✅ Email sent successfully.")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def main():
    signal = read_signal()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🪙 Current Signal: {signal} at {timestamp}")

    alert_method = "NONE"

    if send_via_zapier(signal):
        alert_method = "ZAPIER"
    else:
        print("🔁 Zapier failed or not set. Using email fallback...")
        if send_via_email(signal):
            alert_method = "SMTP"

    print(f"📊 Alert method used: {alert_method}")


if __name__ == "__main__":
    main()
