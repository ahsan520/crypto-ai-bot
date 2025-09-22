    # Crypto AI Backtest & Alert Bot (Updated)

    This repository scans BTC, GALA, and XRP (30m) and generates BUY/SELL signals using a Bollinger+AI filter.


    ## What this package contains


    - `crypto_ai_backtest_multi.py` - main script (backtest + scan + signal generation)

    - `crypto_ai_backtest_multi.ipynb` - interactive notebook (train & test)

    - `requirements.txt` - Python dependencies

    - `.github/workflows/crypto.yml` - GitHub Actions workflow (runs every 30 minutes)

    - `.gitignore`


    ## Quickstart - Local test (recommended before pushing to GitHub)


    1. Install Python 3.10+ and create a virtual environment:

```
python -m venv venv
source venv/bin/activate  # macOS / Linux
venv\Scripts\activate     # Windows
```

2. Install dependencies:

```
pip install -r requirements.txt
```

3. Run a local test (no emails/pushes) to see signals printed:

```
python crypto_ai_backtest_multi.py --test
```

This will:
- Download recent 30m data for BTC, GALA, XRP
- Compute indicators and AI signals (trains a fallback model if none present)
- Print any NEW BUY/SELL signals (and write them to `signals.txt` only when not duplicates)


## GitHub Actions setup (automated runs & notifications)

1. Create a new GitHub repository and push these files.
2. In your repo, go to **Settings → Secrets and variables → Actions → New repository secret** and add the following secrets:
   - `SMTP_USER` (e.g., your Gmail address)
   - `SMTP_PASS` (app password for Gmail; or SMTP password)
   - `SIGNAL_EMAIL` (destination email for alerts)
   - `IFTTT_KEY` (your IFTTT webhook key)
   - `IFTTT_EVENT` (IFTTT event name, e.g., `crypto_signal`)

3. The workflow `.github/workflows/crypto.yml` runs every 30 minutes. When the script produces a **new** BUY or SELL signal, it will create `signals.txt` and the workflow will:
   - Upload artifacts (`*.csv`, `*.png`, `signals.txt`) for you to inspect.
   - Send an **email** (via SMTP) to `SIGNAL_EMAIL` with the signal summary.
   - Send an **iPhone push** via IFTTT webhook with the signal lines.


## How duplicate suppression works

- The script stores the last sent signal per symbol in `last_signals.json`.
- If the same signal repeats on subsequent runs, it is skipped.
- Only a change (new BUY or SELL) triggers notifications.


## Customization

- To change tracked symbols, edit the `SYMBOLS` list in `crypto_ai_backtest_multi.py`.
- To adjust ATR multiplier, edit `ATR_MULTIPLIER`.
- To use a trained AI model rather than fallback, train using the notebook and add `crypto_ai_model.pkl` to the repo.


## Troubleshooting & testing tips

- Run `python crypto_ai_backtest_multi.py --test` locally to verify signals.txt creation and behavior.
- To test notifications before pushing, manually create a `signals.txt` and trigger workflow dispatch.


## Security note

- Use an **app password** for Gmail and **do not** store plain passwords in code. Use GitHub Secrets.


## Questions or help

If you want, I can:
- Add Telegram push in place of IFTTT.
- Harden the "only new signals" logic to store timestamps and hashes.
- Add paper-trading execution code for testnets.

Happy trading! 🚀
