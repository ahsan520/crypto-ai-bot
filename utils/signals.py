from datetime import datetime

def log_signal(filepath, symbol, signal, price):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"{timestamp} | {symbol} | {signal} | ${price:.4f}"
    with open(filepath, "a") as f:
        f.write(entry + "\n")
    return entry
