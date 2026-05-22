"""
Titan Quantum Pro V2 - Master EOD Scanner
Runs at 5:00 AM IST and 5:00 PM IST via GitHub Actions.
"""
import pandas_ta as ta  # REQUIRED to register the .ta accessor
import pandas as pd
import numpy as np
import yfinance as yf
import time, os
from supabase import create_client
from probability_core import ProbabilityEngine

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def safe_float(val, default=0.0):
    if pd.isna(val) or np.isinf(val): return default
    return float(val)

if __name__ == "__main__":
    print("🚀 Titan Quantum Pro V2 - Master Scan Initiating...")
    engine = ProbabilityEngine()

    # Fetch NIFTY baseline
    print("Fetching NIFTY 50 baseline...")
    try:
        nifty_data = yf.download("^NSEI", period="6mo", progress=False, ignore_tz=True)
        if isinstance(nifty_data.columns, pd.MultiIndex):
            nifty_data.columns = [c[0] for c in nifty_data.columns]
        nifty_return_50d = (nifty_data['Close'].iloc[-1] - nifty_data['Close'].iloc[-50]) / nifty_data['Close'].iloc[-50]
        print(f"NIFTY 50D Return: {nifty_return_50d*100:.2f}%")
    except Exception as e:
        print(f"NIFTY fetch failed: {e}")
        nifty_return_50d = 0.0
        nifty_data = pd.DataFrame()

    # Market sentiment
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        import feedparser
        analyzer = SentimentIntensityAnalyzer()
        rss_urls = [
            "https://www.moneycontrol.com/rss/business.xml",
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
        ]
        news_text = ""
        for url in rss_urls:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                news_text += entry.title + ". "
        market_sentiment = analyzer.polarity_scores(news_text)['compound']
        print(f"Market Sentiment: {market_sentiment:.2f}")
    except Exception as e:
        print(f"Sentiment fetch failed: {e}")
        market_sentiment = 0.0

    # Load tickers
    master = pd.read_csv("Tickers.csv")
    symbols = [f"{str(s).strip()}.NS" for s in master['SYMBOL'].dropna().unique()]

    # Sector mapping
    sector_col = None
    for col in master.columns:
        if 'SECTOR' in str(col).upper() or 'INDUSTRY' in str(col).upper():
            sector_col = col
            break
    sector_map = {}
    if sector_col:
        master['Clean_Sym'] = master['SYMBOL'].astype(str).str.strip() + '.NS'
        sector_map = dict(zip(master['Clean_Sym'], master[sector_col].fillna("Unknown")))

    sector_scores = {}
    results = []
    success_count = 0
    BATCH_SIZE = 100
    CHUNK_SIZE = 300

    print(f"Scanning {len(symbols)} stocks in chunks...")

    for i in range(0, len(symbols), CHUNK_SIZE):
        chunk = symbols[i:i+CHUNK_SIZE]
        print(f"\n📥 Batch {i+1}-{min(i+CHUNK_SIZE, len(symbols))}...")

        try:
            data = yf.download(chunk, period="1y", group_by="ticker", threads=True, ignore_tz=True)
            time.sleep(1)
        except Exception as e:
            print(f"Chunk download failed: {e}")
            continue

        for t in chunk:
            try:
                if len(chunk) > 1 and isinstance(data.columns, pd.MultiIndex):
                    if t not in data.columns.get_level_values(0).unique():
                        continue
                    df = data[t].copy()
                else:
                    df = data.copy()

                df.dropna(inplace=True)
                if df.empty or len(df) < 100:
                    continue

                curr_p = safe_float(df['Close'].iloc[-1])
                if curr_p == 0:
                    continue

                # Indicators
                df.ta.ema(length=20, append=True)
                df.ta.ema(length=50, append=True)
                df.ta.rsi(length=14, append=True)
                df.ta.bbands(length=20, append=True)
                df.ta.atr(length=14, append=True)
                df.ta.macd(fast=12, slow=26, signal=9, append=True)
                df.ta.stoch(k=14, d=3, append=True)

                df['Vol_20_MA'] = df['Volume'].rolling(window=20).mean()
                avg_vol = safe_float(df['Vol_20_MA'].iloc[-1])
                curr_vol = safe_float(df['Volume'].iloc[-1])
                rvol = curr_vol / avg_vol if avg_vol > 0 else 0

                # Weekly trend
                df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
                weekly_ema20 = df_w['Close'].ewm(span=20, adjust=False).mean().iloc[-1] if len(df_w) >= 20 else 0
                weekly_trend = "Bullish" if curr_p > weekly_ema20 and weekly_ema20 > 0 else "Bearish"

                # Pattern detection
                res_20 = safe_float(df['High'].rolling(20).max().iloc[-1])
                sup_20 = safe_float(df['Low'].rolling(20).min().iloc[-1])

                open_tdy, close_tdy = safe_float(df['Open'].iloc[-1]), safe_float(df['Close'].iloc[-1])
                open_yst, close_yst = safe_float(df['Open'].iloc[-2]), safe_float(df['Close'].iloc[-2])

                is_bull_engulf = (close_yst < open_yst) and (open_tdy < close_yst) and (close_tdy > open_yst)

                bb_width = 100
                if 'BBU_20_2.0' in df and 'BBL_20_2.0' in df:
                    bb_upper = safe_float(df['BBU_20_2.0'].iloc[-1])
                    bb_lower = safe_float(df['BBL_20_2.0'].iloc[-1])
                    bb_width = (bb_upper - bb_lower) / curr_p * 100

                # VCP detection
                recent_df = df.iloc[-15:]
                up_vol = recent_df[recent_df['Close'] > recent_df['Open']]['Volume'].mean()
                down_vol = recent_df[recent_df['Close'] < recent_df['Open']]['Volume'].mean()
                up_vol = safe_float(up_vol, 1.0)
                down_vol = safe_float(down_vol, 1.0)
                is_vcp = down_vol < (up_vol * 0.75)

                # Pre-breakout
                is_pre_breakout = False
                macd_hist = safe_float(df['MACDh_12_26_9'].iloc[-1]) if 'MACDh_12_26_9' in df else 0
                macd_hist_prev = safe_float(df['MACDh_12_26_9'].iloc[-2]) if 'MACDh_12_26_9' in df else 0

                if bb_width < 6.0 and ((res_20 - curr_p) / curr_p) < 0.03 and macd_hist > macd_hist_prev:
                    is_pre_breakout = True

                pattern = "Uptrending" if curr_p > safe_float(df['EMA_20'].iloc[-1]) else "Consolidating"
                if is_bull_engulf: pattern = "🟢 Bullish Engulfing"
                if is_pre_breakout: pattern = "⚡ VCP Squeeze" if is_vcp else "⚡ Pre-Breakout Squeeze"

                # Probability calculation
                sector = str(sector_map.get(t, "Unknown"))
                sector_breadth = 50  # Will be refined after full scan

                confluence, prob, regime_name, regime_mult, session_label = engine.calculate_entry_probability(
                    df, nifty_return_50d, sector_breadth, market_sentiment, session_info=None
                )

                # ATR-based targets + Monte Carlo (7-day hold for your strategy)
                atr = safe_float(df['ATRr_14'].iloc[-1]) if 'ATRr_14' in df else 0
                mc_target, mc_optimistic, mc_desc = engine.monte_carlo_target(df, curr_p, atr, 7, 500)

                # Standard targets: 10% minimum target for your strategy
                target_price = max(curr_p * 1.10, curr_p + (2.5 * atr))
                stop_loss_price = curr_p - (1.8 * atr)

                # Override with Monte Carlo if higher
                if mc_target > curr_p * 1.08:
                    target_price = mc_target

                rr_ratio = ((target_price - curr_p) / (curr_p - stop_loss_price)) if (curr_p - stop_loss_price) > 0 else 0
                rr_ratio = min(10.0, rr_ratio)

                # Earnings risk
                earnings_risk = "✅ Clear"
                if confluence >= 60:
                    try:
                        tkr = yf.Ticker(t)
                        edates = tkr.get_earnings_dates(limit=3)
                        if edates is not None and not edates.empty:
                            now = pd.Timestamp.now().tz_localize(None)
                            edates.index = edates.index.tz_localize(None)
                            future_dates = edates[edates.index > now]
                            if not future_dates.empty:
                                next_earnings = future_dates.index[0]
                                days_to_earnings = (next_earnings - now).days
                                if 0 <= days_to_earnings <= 7:
                                    earnings_risk = f"⚠️ EARNINGS IN {days_to_earnings}D"
                                    prob *= 0.85
                    except:
                        pass

                turnover = avg_vol * curr_p
                cap_category = "Large/Mid Cap" if turnover >= 20000000 else "Small/Penny Cap"

                if sector not in sector_scores:
                    sector_scores[sector] = []
                sector_scores[sector].append(confluence)

                results.append({
                    "SYMBOL": t.replace(".NS", ""),
                    "PRICE": round(curr_p, 2),
                    "SCORE": round(confluence, 1),
                    "PROBABILITY": round(prob, 1),
                    "REGIME": regime_name,
                    "RSI": round(safe_float(df['RSI_14'].iloc[-1]), 2) if 'RSI_14' in df else 0,
                    "RVOL": round(rvol, 2),
                    "TARGET": round(target_price, 2),
                    "OPTIMISTIC_TARGET": round(mc_optimistic, 2),
                    "STOP_LOSS": round(stop_loss_price, 2),
                    "RR_RATIO": round(rr_ratio, 2),
                    "SUPPORT": round(sup_20, 2),
                    "RESISTANCE": round(res_20, 2),
                    "PATTERN": pattern,
                    "EARNINGS_RISK": earnings_risk,
                    "SECTOR": sector,
                    "INSTITUTIONAL_TREND": weekly_trend,
                    "CAP_CATEGORY": cap_category,
                    "MC_DESCRIPTION": mc_desc,
                    "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                })
                success_count += 1

                if len(results) >= BATCH_SIZE:
                    supabase.table('market_scans').upsert(results, on_conflict="SYMBOL").execute()
                    print(f"📦 Pushed {BATCH_SIZE} stocks. Validated: {success_count}")
                    results = []

            except Exception as e:
                continue

    if results:
        supabase.table('market_scans').upsert(results, on_conflict="SYMBOL").execute()

    print(f"✅ Scan complete. {success_count} stocks processed.")

    # Update sector breadth
    try:
        breadth_data = []
        for sector, scores in sector_scores.items():
            if len(scores) >= 3:
                bullish = sum(1 for s in scores if s >= 60)
                breadth = (bullish / len(scores)) * 100
                breadth_data.append({
                    "SECTOR": sector,
                    "BREADTH_PCT": round(breadth, 1),
                    "AVG_SCORE": round(np.mean(scores), 1),
                    "TOTAL_STOCKS": len(scores),
                    "BULLISH_STOCKS": bullish,
                    "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                })
        if breadth_data:
            supabase.table('sector_breadth').upsert(breadth_data, on_conflict="SECTOR").execute()
            print(f"📊 Sector breadth updated for {len(breadth_data)} sectors.")
    except Exception as e:
        print(f"Sector breadth update failed: {e}")
