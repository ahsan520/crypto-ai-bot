import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

def send_via_zapier(signal_text):
    zapier_url = os.getenv("ZAPIER_URL")
    if not zapier_url:
        print("⚠️ ZAPIER_URL not found, skipping Zapier notification.")
        return False

    try:
        print("📡 Sending signal to Zapier...")
        response = requests.post(zapier_url, json={"signal": signal_text})
        if response.status_code == 200:
            print("✅ Zapier notification sent successfully!")
            return True
        else:
            print(f"⚠️ Zapier returned status {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Error sending to Zapier: {e}")
        return False


def send_via_email(subject, body):
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    signal_email = os.getenv("SIGNAL_EMAIL")

    if not smtp_user or not smtp_pass or not signal_email:
        print("⚠️ Missing SMTP credentials or SIGNAL_EMAIL. Skipping email notification.")
        return False

    try:
        print("📨 Sending email notification...")
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = signal_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        print("✅ Email notification sent successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def read_signal():
    """Read signal from last_signal.json or signals.txt"""
    if os.path.exists("last_signal.json"):
        with open("last_signal.json") as f:
            data = json.load(f)
            return data.get("signal", "No signal found")

    elif os.path.exists("signals.txt"):
        with open("signals.txt") as f:
            return f.read().strip()

    return "No signal file found."


def main():
    signal_text = read_signal()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"🪙 Crypto Signal ({timestamp})\n\n{signal_text}"

    print(f"🔍 Current signal: {signal_text}")

    # 1️⃣ Try Zapier first
    zapier_ok = send_via_zapier(message)

    # 2️⃣ Fallback to email only if Zapier fails
    if not zapier_ok:
        print("🔁 Zapier failed, attempting email fallback...")
        send_via_email("Crypto Signal Alert", message)


if __name__ == "__main__":
    main()
