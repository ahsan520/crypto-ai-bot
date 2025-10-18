import smtplib
from email.mime.text import MIMEText
import os

def send_email_alert(symbol, signal):
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_TO")

    if not all([sender, password, recipient]):
        print("⚠️ Email not configured, skipping alert.")
        return

    msg = MIMEText(f"{symbol} triggered a {signal} signal.")
    msg["Subject"] = f"Crypto Alert: {symbol} {signal}"
    msg["From"] = sender
    msg["To"] = recipient

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.send_message(msg)
        print(f"📧 Email alert sent for {symbol} {signal}")
    except Exception as e:
        print(f"❌ Email failed: {e}")
