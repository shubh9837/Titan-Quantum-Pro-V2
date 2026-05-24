"""
Titan Quantum Pro V2.1 - Master EOD Scanner
Runs at 5:00 AM IST and 5:00 PM IST via GitHub Actions.
Includes Batching, Liquidity Filters, MTFA, and Relative Strength.
"""
import pandas as pd
import pandas_ta_classic as ta
import numpy as np
import yfinance as yf
import time, os
from supabase import create_client
from probability_core import ProbabilityEngine

# Pandas 2.0+ compatibility patch for pandas_ta
if not hasattr(pd.Series, "append"):
    pd.Series.append = pd.Series._append

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def safe_float(val, default=0.0):
    if pd.isna(val) or np.isinf(val): return default
    return float(val)

if __name__ == "__main__":
    print("🚀 Titan Quantum Pro V2.1 - Master Scan Initiating...")
    engine = ProbabilityEngine()
    
    # AI Self-Calibration
    engine.calibrate_base_rates(supabase)

    # 1. Fetch NIFTY 50 baseline for Relative Strength calculation
    print("📊 Fetching NIFTY 50 baseline for Relative Strength...")
    try:
        nifty_data = yf.download("^NSEI", period="6mo", progress=False, ignore_tz=True)
        if isinstance(nifty_data.columns, pd.MultiIndex):
            nifty_data.columns = [c[0] for c in nifty_data.columns]
        nifty_close = nifty_data['Close']
    except Exception as e:
        print(f"⚠️ Warning: Failed to fetch Nifty data: {e}")
        nifty_close = None

    # Load Tickers
    master = pd.read_csv("Tickers.csv")
    symbols = [f"{str(s).strip()}.NS" for s in master['SYMBOL'].dropna().unique()]
    
    results = []
    sector_scores = {}
    BATCH_SIZE = 50
    success_count = 0

    print(f"🔍 Starting batch processing for {len(symbols)} tickers...")

    # 2. BATCH PROCESSING LOOP (To avoid yfinance rate limits)
    for i in range(0, len(symbols), BATCH_SIZE):
        chunk = symbols[i:i + BATCH_SIZE]
        print(f"⏳ Processing Batch {i // BATCH_SIZE + 1}/{(len(symbols) // BATCH_SIZE) + 1}...")
        
        try:
            # Download Daily AND Weekly data for the chunk
            daily_data = yf.download(chunk, period="6mo", group_by="ticker", threads=False, progress=False, ignore_tz=True)
            weekly_data = yf.download(chunk, period="1y", interval="1wk", group_by="ticker", threads=False, progress=False, ignore_tz=True)
        except Exception as e:
            print(f"⚠️ Failed to download batch: {e}")
            time.sleep(5)
            continue

        # Process each symbol in the downloaded chunk
        for sym in chunk:
            try:
                # Handle single vs multi-index dataframe structure
                df = daily_data[sym].copy() if len(chunk) > 1 else daily_data.copy()
                w_df = weekly_data[sym].copy() if len(chunk) > 1 else weekly_data.copy()
                df.dropna(inplace=True)
                w_df.dropna(inplace=True)
                
                if len(df) < 50: 
                    continue

                # Technical Indicators
                df.ta.rsi(length=14, append=True)
                df.ta.atr(length=14, append=True)
                
                cmp = float(df['Close'].iloc[-1])
                atr = float(df['ATRr_14'].iloc[-1]) if 'ATRr_14' in df.columns else (cmp * 0.02)
                
                volume_ma = df['Volume'].rolling(20).mean().iloc[-1]
                rvol = float(df['Volume'].iloc[-1] / volume_ma) if volume_ma > 0 else 1.0

                # 3. STRICT LIQUIDITY FILTER (Turnover in Crores)
                turnover_cr = (volume_ma * cmp) / 10000000 
                if turnover_cr < 5.0: 
                    continue # Skip illiquid stocks to save API calls

                # 4. DEFERRED API CALLS (Only fetch Sector & Earnings for liquid stocks)
                sector = 'Others'
                earnings_risk = False
                try:
                    ticker_obj = yf.Ticker(sym)
                    info = ticker_obj.info
                    sector = info.get('sector', info.get('industry', 'Others'))
                    if sector == 'Unknown': sector = 'Others'
                    
                    cal = ticker_obj.calendar
                    if cal and len(cal) > 0: earnings_risk = True 
                except:
                    pass

                # 5. RELATIVE STRENGTH (Mansfield RS)
                rs_status = "Neutral"
                if nifty_close is not None and not nifty_close.empty:
                    aligned_df, aligned_nifty = df['Close'].align(nifty_close, join='inner')
                    if len(aligned_df) > 50:
                        rs_line = aligned_df / aligned_nifty
                        rs_ema50 = rs_line.ewm(span=50, adjust=False).mean()
                        if rs_line.iloc[-1] > rs_ema50.iloc[-1]:
                            rs_status = "Outperforming"
                        else:
                            rs_status = "Underperforming"

                # 6. Advanced Risk & Volume Profile S&R
                support, resistance = engine.calculate_volume_profile_sr(df)
                dynamic_stop = engine.calculate_dynamic_stop(df, atr)

                # 7. COMPOSITE STRENGTH & VETO
                score, w_trend, verdict_override = engine.calculate_composite_score(df, w_df, rs_status, earnings_risk)
                
                # Probability calculation
                prob = 0
                for (low, high), rate in engine.base_rates.items():
                    if low <= score <= high:
                        prob = rate * 100
                        break

                # 8. PRE-COMPUTE UI FIELDS
                upside_pct = ((resistance - cmp) / cmp) * 100 if cmp > 0 else 0
                risk = cmp - dynamic_stop
                reward = resistance - cmp
                rr_ratio = reward / risk if risk > 0 else 0
                
                if verdict_override:
                    verdict = verdict_override
                else:
                    verdict = ("💎 ALPHA" if score >= 90 and prob >= 80 else
                               "🟢 STRONG BUY" if score >= 75 else
                               "🟢 BUY" if score >= 60 else
                               "🟡 WATCH" if score >= 45 else "🔴 AVOID")
                               
                est_period = "5-7 Days" if score >= 85 else "7-10 Days" if score >= 70 else "14+ Days"

                clean_sym = sym.replace('.NS', '')
                results.append({
                    "SYMBOL": clean_sym,
                    "PRICE": round(cmp, 2),
                    "SCORE": round(score, 1),
                    "PROBABILITY": round(prob, 1),
                    "RVOL": round(rvol, 2),
                    "SUPPORT": round(support, 2),
                    "RESISTANCE": round(resistance, 2),
                    "TARGET": round(resistance, 2),
                    "STOP_LOSS": round(dynamic_stop, 2),
                    "RR_RATIO": round(rr_ratio, 2),
                    "SECTOR": sector,
                    "UPSIDE_PCT": round(upside_pct, 2),
                    "VERDICT": verdict,
                    "EST_PERIOD": est_period,
                    "WEEKLY_TREND": w_trend,
                    "SR_METHOD": "Volume Profile",
                    "RELATIVE_STRENGTH": rs_status,
                    "TURNOVER_CR": round(turnover_cr, 2),
                    "EARNINGS_RISK": "YES" if earnings_risk else "NO",
                    "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                })

                # Track sectors for Breadth map
                if sector not in sector_scores: sector_scores[sector] = []
                sector_scores[sector].append(score)

                success_count += 1

            except Exception as e:
                continue

        # Push to Supabase after each chunk finishes to ensure data isn't lost if the script crashes
        if results:
            supabase.table('market_scans').upsert(results, on_conflict="SYMBOL").execute()
            results = []
            
        # Throttling to respect yfinance API limits
        time.sleep(3)

    print(f"✅ Master Scan Complete! {success_count} liquid stocks successfully processed and pushed.")

    # 9. Update Sector Breadth Map
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
            print("🗺️ Sector Breadth Updated.")
    except Exception as e:
        print(f"⚠️ Breadth Map Error: {e}")
