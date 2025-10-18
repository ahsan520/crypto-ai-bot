# ------------------------------------------------------------
# 🤖 STRATEGY SECTION (AI-BASED)
# ------------------------------------------------------------
def build_features(df):
    """Add technical indicators and candlestick features."""
    df = df.copy()

    # --- Core indicators ---
    df['rsi'] = ta.momentum.RSIIndicator(df['Close']).rsi()
    macd = ta.trend.MACD(df['Close'])
    df['macd'] = macd.macd()
    bb = ta.volatility.BollingerBands(df['Close'])
    df['bb_mid'] = bb.bollinger_mavg()
    df['bb_high'] = bb.bollinger_hband()
    df['bb_low'] = bb.bollinger_lband()
    df['bb_width'] = (df['bb_high'] - df['bb_low']) / df['bb_mid']
    df['percent_b'] = (df['Close'] - df['bb_low']) / (df['bb_high'] - df['bb_low'])
    df['volume_change'] = df['Volume'].pct_change().fillna(0)

    # --- ATR ---
    atr = ta.volatility.AverageTrueRange(df['High'], df['Low'], df['Close'], window=config["atr_window"])
    df['ATR'] = atr.average_true_range()

    # --- Candlestick patterns ---
    o, h, l, c = df['Open'], df['High'], df['Low'], df['Close']
    body = (c - o).abs()
    candle_range = (h - l).replace(0, np.nan)
    upper_shadow = h - np.maximum(o, c)
    lower_shadow = np.minimum(o, c) - l

    df['shooting_star'] = (
        ((body <= 0.3 * candle_range) & (upper_shadow >= 2 * body) & (lower_shadow <= 0.2 * body))
        .fillna(0).astype(int)
    )
    df['hammer'] = (
        ((body <= 0.3 * candle_range) & (lower_shadow >= 2 * body) & (upper_shadow <= 0.2 * body))
        .fillna(0).astype(int)
    )

    return df.dropna()


# ------------------------------------------------------------
# 📊 SIGNAL GENERATION (patched with safer YF handling)
# ------------------------------------------------------------
def generate_signals():
    print("📡 Generating AI-based crypto signals ...")
    last_signals = load_last_signals()
    model = None
    new_signals = {}

    for sym in config["symbols"]:
        print(f"📥 Downloading {sym} data ...")
        try:
            df = yf.download(
                sym,
                period=config["period"],
                interval=config["interval"],
                progress=False
            ).dropna()

            # 🧩 Flatten multi-index columns if needed
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

            # 🧹 Ensure Close is 1D (some yfinance versions return DataFrame instead of Series)
            if isinstance(df.get('Close'), pd.DataFrame):
                df['Close'] = df['Close'].squeeze()
            if df['Close'].ndim > 1:
                df['Close'] = df['Close'].iloc[:, 0]

            # 🧠 Build AI features
            df = build_features(df)
            if model is None:
                model = ensure_model(df)

            feature_cols = [
                'rsi', 'macd', 'bb_mid', 'bb_high', 'bb_low', 'bb_width',
                'percent_b', 'volume_change', 'shooting_star', 'hammer'
            ]
            X = df[feature_cols].fillna(0)
            ai_pred = model.predict(X)

            # --- Entry/Exit logic ---
            entry = (df['Close'] <= df['bb_low']) & (ai_pred == 1)
            exit_ = df['Close'] >= df['bb_high']

            signal = "HOLD"
            if len(entry) >= 2:
                if entry.iloc[-1] and not entry.iloc[-2]:
                    signal = "BUY"
                elif exit_.iloc[-1] and not exit_.iloc[-2]:
                    signal = "SELL"

            new_signals[sym] = signal
            print(f"🔹 {sym}: {signal}")

        except Exception as e:
            print(f"⚠️ Skipping {sym} due to error: {e}")
            continue

    return new_signals
