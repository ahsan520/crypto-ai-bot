import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any
from datetime import datetime

# read env (workflow sets these)
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")

def send_to_zapier(payload: Dict[str, Any]) -> bool:
    """Primary notifier: Zapier webhook. Returns True if success."""
    if not ZAPIER_WEBHOOK_URL:
        print("⚠️ ZAPIER_WEBHOOK_URL not configured.")
        return False
    try:
        r = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code in (200, 201):
            print("✅ Zapier webhook accepted payload.")
            return True
        print(f"⚠️ Zapier returned {r.status_code} -> {r.text}")
        return False
    except Exception as e:
        print(f"⚠️ Zapier send error: {e}")
        return False

def send_email_fallback(summary: Dict[str, Any]) -> bool:
    """Fallback email. Returns True on success."""
    if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_TO):
        print("⚠️ Email credentials missing; cannot send fallback.")
        return False
    try:
        # Build human-friendly body
        parts = []
        if summary.get("BUY"):
            parts.append("🔥 BUY signals:\n" + "\n".join([f"{i['symbol']}: ${i['price']}" for i in summary["BUY"]]))
        if summary.get("SELL"):
            parts.append("⚠️ SELL signals:\n" + "\n".join([f"{i['symbol']}: ${i['price']}" for i in summary["SELL"]]))
        body = "\n\n".join(parts) if parts else "No BUY/SELL signals."

        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_TO
        msg["Subject"] = f"Crypto AI Bot Alert - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        msg.attach(MIMEText(body, "plain"))

        # attempt send
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(EMAIL_SENDER, EMAIL_PASSWORD)
            s.sendmail(EMAIL_SENDER, EMAIL_TO.split(","), msg.as_string())
        print("✅ Fallback email sent.")
        return True
    except Exception as e:
        print(f"⚠️ Fallback email error: {e}")
        return False
