import os
import requests
import smtplib
from email.mime.text import MIMEText

# === Configuration ===
ZAPIER_WEBHOOK = os.getenv("ZAPIER_WEBHOOK_URL", "")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")


def send_alert(symbol, signal, source="auto-bot"):
    """Send alert via Zapier first, then fallback to email."""
    message = f"Crypto Signal Alert:\n\nSymbol: {symbol}\nSignal: {signal}\nSource: {source}"

    # Try Zapier webhook first
    if ZAPIER_WEBHOOK:
        try:
            res = requests.post(ZAPIER_WEBHOOK, json={"symbol": symbol, "signal": signal, "source": source})
            if res.status_code == 200:
                print(f"✅ Zapier alert sent for {symbol}.")
                return
            else:
                print(f"⚠️ Zapier failed: {res.status_code}, using email fallback...")
        except Exception as e:
            print(f"⚠️ Zapier error: {e}, using email fallback...")

    # Fallback to email
    if SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO:
        try:
            msg = MIMEText(message)
            msg["Subject"] = f"Crypto Signal: {symbol} → {signal}"
            msg["From"] = SMTP_USER
            msg["To"] = ALERT_EMAIL_TO

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.send_message(msg)
            print(f"✅ Email alert sent to {ALERT_EMAIL_TO}.")
        except Exception as e:
            print(f"❌ Email alert failed: {e}")
    else:
        print("⚠️ No alert method configured. Set ZAPIER_WEBHOOK_URL or SMTP creds.")
