import os
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

# ---------------- CONFIG ----------------
UTILS_DIR = "utils"
SUMMARY_FILE = f"{UTILS_DIR}/summary.json"
SIGNALS_FILE = f"{UTILS_DIR}/signals.txt"
HOLDS_FILE = f"{UTILS_DIR}/holds.txt"
ZAPIER_WEBHOOK_URL = os.getenv("ZAPIER_WEBHOOK_URL")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
# ----------------------------------------

def load_summary():
    """Load summary.json containing BUY/SELL/HOLD groups"""
    if not Path(SUMMARY_FILE).exists():
        print("⚠️ No summary.json found.")
        return None
    try:
        return json.loads(Path(SUMMARY_FILE).read_text())
    except Exception as e:
        print(f"⚠️ Failed to load summary.json: {e}")
        return None

def has_buy_or_sell(summary):
    """Check if any actionable signal exists"""
    return (summary and (len(summary.get("BUY", [])) > 0 or len(summary.get("SELL", [])) > 0))

def send_to_zapier(summary):
    """Send JSON payload to Zapier webhook"""
    if not ZAPIER_WEBHOOK_URL:
        print("⚠️ Zapier webhook URL missing.")
        return False
    try:
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source": "Crypto AI Bot",
            "summary": summary
        }
        r = requests.post(ZAPIER_WEBHOOK_URL, json=payload, timeout=15)
        if r.status_code in [200, 201]:
            print(f"✅ Sent {len(summary.get('BUY', []))} BUY / {len(summary.get('SELL', []))} SELL to Zapier.")
            return True
        else:
            print(f"⚠️ Zapier webhook failed with status {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print(f"⚠️ Zapier send error: {e}")
        return False

def send_email_fallback(summary):
    """Send email if Zapier webhook fails"""
    if not (EMAIL_SENDER and EMAIL_PASSWORD and EMAIL_TO):
        print("⚠️ Email credentials not set.")
        return False
    try:
        body = []
        if summary.get("BUY"):
            body.append("🔥 **BUY Signals** 🔥\n" + "\n".join(
                [f"{x['symbol']} @ ${x['price']:.4f}" for x in summary["BUY"]]
            ))
        if summary.get("SELL"):
            body.append("⚠️ **SELL Signals** ⚠️\n" + "\n".join(
                [f"{x['symbol']} @ ${x['price']:.4f}" for x in summary["SELL"]]
            ))
        if not body:
            body.append("No actionable BUY/SELL signals today.")
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_TO
        msg["Subject"] = f"🚨 Crypto AI Bot Alert – {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        msg.attach(MIMEText("\n\n".join(body), "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_TO.split(","), msg.as_string())
        print("✅ Email alert sent successfully.")
        return True
    except Exception as e:
        print(f"⚠️ Email fallback failed: {e}")
        return False

def main():
    summary = load_summary()
    if not summary:
        print("⚠️ No summary file found or invalid. Exiting.")
        return
    if not has_buy_or_sell(summary):
        print("🕊 No BUY/SELL signals detected — only HOLDs. Skipping notifications.")
        return

    print("🚀 Actionable signal detected! Attempting webhook send...")
    if not send_to_zapier(summary):
        print("⚠️ Webhook failed — using SMTP fallback...")
        send_email_fallback(summary)

    # Final console report
    print("\n📊 ===== SUMMARY =====")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
