import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_alert(message: str):
    zapier_url = os.getenv("ZAPIER_URL")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    signal_email = os.getenv("SIGNAL_EMAIL")

    print("🔍 Checking alert configuration...")

    zapier_success = False

    # 1️⃣ Try Zapier first (if configured)
    if zapier_url:
        print("⚙️ ZAPIER_URL found → trying Zapier webhook...")
        try:
            response = requests.post(zapier_url, json={"text": message}, timeout=10)
            if response.status_code == 200:
                print("✅ Sent successfully via Zapier webhook.")
                zapier_success = True
            else:
                print(f"⚠️ Zapier returned {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ Zapier send error: {e}")
    else:
        print("⚠️ No Zapier URL configured. Will skip webhook and try SMTP.")

    # 2️⃣ Only use SMTP if Zapier not configured OR Zapier failed
    if not zapier_success and smtp_user and smtp_pass and signal_email:
        print(f"📧 Falling back to email alert → {signal_email}")
        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = signal_email
            msg["Subject"] = "Crypto AI Bot Signal"
            msg.attach(MIMEText(message, "plain"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            print("✅ Alert email sent successfully via SMTP.")
            return "smtp"
        except Exception as e:
            print(f"❌ SMTP send error: {e}")
            return "smtp_failed"

    elif zapier_success:
        return "zapier"
    else:
        print("⚠️ No alert method configured (ZAPIER_URL or SMTP_USER missing).")
        return "none"


# Example usage:
if __name__ == "__main__":
    signal_message = "BTC BUY signal detected at 65,200 USD"
    result = send_alert(signal_message)
    print(f"::notice::Alert method used: {result.upper()}")
