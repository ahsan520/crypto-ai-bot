import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from datetime import datetime


def generate_signal():
    """Generate or update last_signal.json if it doesn't exist or is empty"""
    signal_file = "last_signal.json"

    if os.path.exists(signal_file):
        try:
            with open(signal_file) as f:
                data = json.load(f)
                if data.get("signal"):
                    print("✅ Existing signal found in last_signal.json.")
                    return  # no need to overwrite
        except Exception as e:
            print(f"⚠️ Could not read {signal_file}: {e}")

    # --- Generate a sample/test signal ---
    signal_data = {
        "symbol": "BTCUSDT",
        "signal": "BUY",
        "confidence": 0.87,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "source": "auto-test"
    }

    with open(signal_file, "w") as f:
        json.dump(signal_data, f, indent=2)

    print("🆕 Created new last_signal.json:")
    print(json.dumps(signal_data, indent=2))


def read_signal():
    """Read BUY/HOLD/SELL signal from last_signal.json or signals.txt"""
    signal = None
    extra_info = {}

    if os.path.exists("last_signal.json"):
        try:
            with open("last_signal.json") as f:
                data = json.load(f)
                print("📁 Contents of last_signal.json:")
                print(json.dumps(data, indent=2))
                signal = str(data.get("signal", "")).strip().upper()
                extra_info = data
        except Exception as e:
            print(f"⚠️ Error reading last_signal.json: {e}")

    elif os.path.exists("signals.txt"):
        try:
            with open("signals.txt") as f:
                signal = f.read().strip().upper()
                print(f"📁 Contents of signals.txt: {signal}")
        except Exception as e:
            print(f"⚠️ Error reading signals.txt: {e}")

    if not signal or signal not in ["BUY", "SELL", "HOLD"]:
        signal = "NONE"

    return signal, extra_info


def send_via_zapier(signal_text, timestamp, extra_info=None):
    zapier_url = os.getenv("ZAPIER_URL")
    if not zapier_url:
        print("⚠️ ZAPIER_URL not set. Skipping Zapier notification.")
        return False

    try:
        payload = {
            "signal": signal_text,
            "time": timestamp,
            "details": extra_info or {}
        }
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


def send_via_email(signal_text, timestamp, extra_info=None):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    signal_email = os.getenv("SIGNAL_EMAIL")

    if not smtp_user or not smtp_pass or not signal_email:
        print("⚠️ Missing SMTP credentials. Skipping email notification.")
        return False

    try:
        subject = f"Crypto Signal: {signal_text}"
        body = f"Crypto Signal: {signal_text}\nTime: {timestamp}\n\nDetails:\n{json.dumps(extra_info or {}, indent=2)}"

        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = signal_email

        print(f"📨 Sending email alert: {signal_text}")
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
    # ✅ Step 1: Make sure we have a signal
    generate_signal()

    # ✅ Step 2: Read and send it
    signal, extra_info = read_signal()
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"🪙 Current Signal: {signal} at {timestamp}")

    alert_method = "NONE"

    if signal in ["BUY", "SELL"]:
        if send_via_zapier(signal, timestamp, extra_info):
            alert_method = "ZAPIER"
        else:
            print("🔁 Zapier failed or not set. Trying email fallback...")
            if send_via_email(signal, timestamp, extra_info):
                alert_method = "SMTP"
    else:
        print(f"ℹ️ Signal is '{signal}'. No alert sent.")

    print(f"📊 Alert method used: {alert_method}")


if __name__ == "__main__":
    main()
