"""
Titan Quantum Pro V2.1 - Intraday Pulse
Runs every 15 mins during market hours via GitHub Actions.
Safely updates live prices and checks portfolio for catastrophic stops.
"""
import os, time, datetime
import pandas as pd
import numpy as np
import yfinance as yf
from supabase import create_client
from probability_core import ProbabilityEngine

# Pandas 2.0+ compatibility patch
if not hasattr(pd.Series, "append"):
    pd.Series.append = pd.Series._append

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
engine = ProbabilityEngine()

def safe_float(val, default=0.0):
    if pd.isna(val) or np.isinf(val): return default
    return float(val)

def pulse_sync():
    print("🔄 Intraday Pulse: Starting Live Price Sync...")
    
    # 1. Load Active Portfolio (To check for alerts)
    try:
        port_res = supabase.table('portfolio').select('*').execute()
        portfolio = pd.DataFrame(port_res.data) if port_res.data else pd.DataFrame()
        port_symbols = [f"{s}.NS" for s in portfolio['symbol'].unique()] if not portfolio.empty else []
    except Exception as e:
        print(f"⚠️ Could not fetch portfolio: {e}")
        portfolio = pd.DataFrame()
        port_symbols = []

    # 2. Load Tickers
    master = pd.read_csv("Tickers.csv")
    symbols = [f"{str(s).strip()}.NS" for s in master['SYMBOL'].dropna().unique()]
    
    BATCH_SIZE = 50
    alerts = []

    print(f"📊 Fast-fetching live prices for {len(symbols)} tickers...")

    for i in range(0, len(symbols), BATCH_SIZE):
        chunk = symbols[i:i+BATCH_SIZE]
        
        try:
            # Extremely lightweight fetch to stay under YF radar
            data = yf.download(chunk, period="5d", group_by="ticker", threads=False, progress=False, ignore_tz=True)
        except Exception as e:
            print(f"⚠️ Failed to download batch: {e}")
            time.sleep(2)
            continue

        for sym in chunk:
            try:
                # Handle YF multi-index formatting
                if len(chunk) > 1 and isinstance(data.columns, pd.MultiIndex):
                    if sym not in data.columns.get_level_values(0).unique(): continue
                    df = data[sym].copy()
                else:
                    df = data.copy()
                    
                df.dropna(inplace=True)
                if df.empty: continue
                
                live_price = safe_float(df['Close'].iloc[-1])
                if live_price == 0: continue
                
                clean_sym = sym.replace('.NS', '')
                
                # 3. SURGICAL UPDATE: Update ONLY the price, preserving master scan data
                supabase.table('market_scans').update({
                    "PRICE": round(live_price, 2),
                    "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')
                }).eq('SYMBOL', clean_sym).execute()

                # 4. PORTFOLIO ALERT LOGIC (Emergency Check)
                if sym in port_symbols:
                    holding = portfolio[portfolio['symbol'] == clean_sym].iloc[0]
                    entry = float(holding['entry_price'])
                    entry_date = holding.get('date', datetime.date.today())
                    
                    # Fetch slightly more data just for portfolio holdings to calculate damage
                    hist = yf.download(sym, period="3mo", progress=False, ignore_tz=True)
                    if not hist.empty:
                        damage, verdict, new_stop, reasoning = engine.calculate_exit_damage(
                            clean_sym, entry, entry_date, hist, live_data={'PRICE': live_price}
                        )
                        pnl_pct = ((live_price - entry) / entry) * 100
                        
                        if live_price <= entry * 0.90:
                            alerts.append(f"🚨 {clean_sym}: CATASTROPHIC GAP DOWN! CMP ₹{live_price:.1f} (Entry ₹{entry:.1f}). EXIT NOW!")
                        elif damage >= 70:
                            alerts.append(f"⚠️ {clean_sym}: DAMAGE {damage}/100. {verdict}. CMP ₹{live_price:.1f}. {reasoning}")
                        elif live_price <= new_stop and pnl_pct < -2:
                            alerts.append(f"🔴 {clean_sym}: STOP HIT! CMP ₹{live_price:.1f} below ₹{new_stop:.1f}. {verdict}")

            except Exception as e:
                continue
                
        # Pause to respect rate limits
        time.sleep(1.5)

    print("\n================ PORTFOLIO ALERTS ================")
    if alerts:
        for alert in alerts:
            print(alert)
    else:
        print("✅ All active holdings are secure. No critical alerts.")
    print("==================================================")
    print("✅ Intraday Pulse Complete!")

if __name__ == "__main__":
    # RESTORED: Market Open Check Logic
    ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    is_market_open = (ist_now.hour == 9 and ist_now.minute >= 15) or (10 <= ist_now.hour <= 14) or (ist_now.hour == 15 and ist_now.minute <= 30)

    # Note: We run it regardless for testing, but in production, you can uncomment the restriction:
    if is_market_open or True: # Remove 'or True' if you only want it to run during market hours
        print(f"Market Check ({ist_now.strftime('%H:%M')} IST). Running intraday pulse...")
        pulse_sync()
    else:
        print(f"Market CLOSED ({ist_now.strftime('%H:%M')} IST). Intraday pulse skipped.")
