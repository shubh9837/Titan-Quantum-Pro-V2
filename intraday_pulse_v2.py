"""
Titan Quantum Pro V2 - Intraday Pulse
Updates live prices and recalculates scores with session-aware logic.
"""
import os, time, datetime
import pandas as pd
import pandas_ta_classic as ta
import numpy as np
import yfinance as yf
from supabase import create_client
from probability_core import ProbabilityEngine

# Pandas 2.0+ compatibility patch for pandas_ta
if not hasattr(pd.Series, "append"):
    pd.Series.append = pd.Series._append

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
engine = ProbabilityEngine()

def safe_float(val, default=0.0):
    if pd.isna(val) or np.isinf(val): return default
    return float(val)

def update_live_prices():
    print("🔄 Live Price Sync...")
    master = pd.read_csv("Tickers.csv")
    symbols = [f"{str(s).strip()}.NS" for s in master['SYMBOL'].dropna().unique()]

updates = []
    for i in range(0, len(symbols), 50): # Reduced to 50
        chunk = symbols[i:i+50] # Reduced to 50
        try:
            # Turned threads off
            data = yf.download(chunk, period="5d", group_by="ticker", threads=False, ignore_tz=True)
            time.sleep(1) # Added a small delay
            for t in chunk:
                try:
                    if len(chunk) > 1 and isinstance(data.columns, pd.MultiIndex):
                        if t not in data.columns.get_level_values(0).unique(): continue
                        df = data[t].copy()
                    else:
                        df = data.copy()
                    df.dropna(inplace=True)
                    if df.empty: continue
                    curr_p = safe_float(df['Close'].iloc[-1])
                    if curr_p == 0: continue
                    updates.append({
                        "SYMBOL": t.replace(".NS", ""),
                        "PRICE": round(curr_p, 2),
                        "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                    })
                except: continue
        except Exception as e:
            print(f"Chunk error: {e}")

        if len(updates) >= 200:
            supabase.table('market_scans').upsert(updates, on_conflict="SYMBOL").execute()
            updates = []

    if updates:
        supabase.table('market_scans').upsert(updates, on_conflict="SYMBOL").execute()
    print("✅ Prices updated.")

def intraday_score_update():
    """Recalculates scores for top 200 stocks with session-aware logic."""
    print("📊 Intraday Score Recalculation...")

    # Get current market scan data
    res = supabase.table('market_scans').select('*').limit(200).execute()
    if not res.data:
        print("No data to update.")
        return

    existing = pd.DataFrame(res.data)
    # Sort by score to update top movers
    existing = existing.sort_values('SCORE', ascending=False).head(150)

    session_info = engine.get_intraday_adjustment()
    print(f"Session: {session_info[2]} | Confidence: {session_info[0]:.0%} | Vol Expectation: {session_info[1]:.0%}")

    # Fetch NIFTY once
    try:
        nifty_data = yf.download("^NSEI", period="6mo", progress=False, ignore_tz=True)
        if isinstance(nifty_data.columns, pd.MultiIndex):
            nifty_data.columns = [c[0] for c in nifty_data.columns]
        nifty_return_50d = (nifty_data['Close'].iloc[-1] - nifty_data['Close'].iloc[-50]) / nifty_data['Close'].iloc[-50]
    except:
        nifty_return_50d = 0.0
        nifty_data = pd.DataFrame()

    # Sector breadth
    try:
        sb_res = supabase.table('sector_breadth').select('*').execute()
        sb_df = pd.DataFrame(sb_res.data) if sb_res.data else pd.DataFrame()
        sector_breadth_map = dict(zip(sb_df['SECTOR'], sb_df['BREADTH_PCT'])) if not sb_df.empty else {}
    except:
        sector_breadth_map = {}

    # Build symbol-to-sector map
    symbol_to_sector = {}
    if 'SECTOR' in existing.columns:
        symbol_to_sector = dict(zip(existing['SYMBOL'], existing['SECTOR']))

    updates = []
    symbols_to_update = [f"{row['SYMBOL']}.NS" for _, row in existing.iterrows()]

    for i in range(0, len(symbols_to_update), 100):
        chunk = symbols_to_update[i:i+100]
        print(f"📥 Intraday batch {i+1}-{min(i+100, len(symbols_to_update))}...")
        try:
            batch_data = yf.download(chunk, period="3mo", group_by="ticker", threads=False, ignore_tz=True)
            time.sleep(1)
        except Exception as e:
            print(f"Batch download failed: {e}")
            continue

        for sym in chunk:
            try:
                if len(chunk) > 1 and isinstance(batch_data.columns, pd.MultiIndex):
                    if sym not in batch_data.columns.get_level_values(0).unique():
                        continue
                    hist = batch_data[sym].copy()
                else:
                    hist = batch_data.copy()

                hist.dropna(inplace=True)
                if hist.empty or len(hist) < 30:
                    continue

                hist.ta.ema(length=20, append=True)
                hist.ta.ema(length=50, append=True)
                hist.ta.rsi(length=14, append=True)
                hist.ta.macd(fast=12, slow=26, signal=9, append=True)
                hist.ta.atr(length=14, append=True)
                hist.ta.bbands(length=20, append=True)
                hist['Vol_20_MA'] = hist['Volume'].rolling(window=20).mean()

                sector = symbol_to_sector.get(sym.replace('.NS', ''), 'Unknown')
                sector_breadth = sector_breadth_map.get(sector, 50)

                confluence, prob, regime_name, regime_mult, session_label = engine.calculate_entry_probability(
                    hist, nifty_return_50d, sector_breadth, 0.0, session_info=session_info, nifty_df_full=nifty_data
                )

                # Override price with latest
                curr_p = safe_float(hist['Close'].iloc[-1])
                atr = safe_float(hist['ATRr_14'].iloc[-1]) if 'ATRr_14' in hist else 0
                target = max(curr_p * 1.10, curr_p + (2.5 * atr))
                stop = curr_p - (1.8 * atr)

                updates.append({
                    "SYMBOL": sym.replace(".NS", ""),
                    "PRICE": round(curr_p, 2),
                    "SCORE": round(confluence, 1),
                    "PROBABILITY": round(prob, 1),
                    "REGIME": regime_name,
                    "TARGET": round(target, 2),
                    "STOP_LOSS": round(stop, 2),
                    "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                })

                if len(updates) >= 50:
                    supabase.table('market_scans').upsert(updates, on_conflict="SYMBOL").execute()
                    updates = []
            except Exception as e:
                continue

    if updates:
        supabase.table('market_scans').upsert(updates, on_conflict="SYMBOL").execute()
    print(f"✅ Intraday scores updated for {len(existing)} stocks.")

def check_portfolio_emergency():
    print("🔍 Portfolio Emergency Check...")
    res = supabase.table('portfolio').select("*").execute()
    portfolio = res.data

    if not portfolio:
        print("Portfolio empty.")
        return

    alerts = []
    for item in portfolio:
        sym = item['symbol']
        entry = float(item['entry_price'])
        entry_date = item.get('date', datetime.date.today())

        try:
            hist = yf.download(f"{sym}.NS", period="3mo", progress=False, ignore_tz=True)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [c[0] for c in hist.columns]

            if not hist.empty:
                hist.ta.ema(length=20, append=True)
                hist.ta.ema(length=50, append=True)
                hist.ta.rsi(length=14, append=True)
                hist.ta.macd(fast=12, slow=26, signal=9, append=True)
                hist.ta.atr(length=14, append=True)

                live_price = float(hist['Close'].iloc[-1])
                damage, verdict, new_stop, reasoning = engine.calculate_exit_damage(
                    sym, entry, entry_date, hist, None
                )
                pnl_pct = (live_price - entry) / entry * 100

                if live_price <= entry * 0.90:
                    alerts.append(f"🚨 {sym}: CATASTROPHIC GAP DOWN! CMP ₹{live_price:.1f} (Entry ₹{entry:.1f}). EXIT NOW!")
                elif damage >= 70:
                    alerts.append(f"⚠️ {sym}: DAMAGE {damage}/100. {verdict}. CMP ₹{live_price:.1f}. {reasoning}")
                elif live_price <= new_stop and pnl_pct < -2:
                    alerts.append(f"🔴 {sym}: STOP HIT! CMP ₹{live_price:.1f} below ₹{new_stop:.1f}. {verdict}")
                else:
                    print(f"✅ {sym}: OK (Damage: {damage}, P&L: {pnl_pct:+.1f}%)")
        except Exception as e:
            print(f"Error checking {sym}: {e}")

    for alert in alerts:
        print(alert)

if __name__ == "__main__":
    update_live_prices()

    ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    is_market_open = (ist_now.hour == 9 and ist_now.minute >= 15) or (10 <= ist_now.hour <= 14) or (ist_now.hour == 15 and ist_now.minute <= 30)

    if is_market_open:
        print(f"Market OPEN ({ist_now.strftime('%H:%M')} IST). Running intraday updates...")
        intraday_score_update()
        check_portfolio_emergency()
    else:
        print(f"Market CLOSED ({ist_now.strftime('%H:%M')} IST). Price sync only.")
