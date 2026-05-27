"""
Titan Quantum Pro V2.1 - Intraday Pulse
Updates live prices safely and checks for Portfolio Emergencies.
"""
import os, time, datetime
import pandas as pd
import numpy as np
import yfinance as yf
from supabase import create_client
from probability_core import ProbabilityEngine

if not hasattr(pd.Series, "append"): pd.Series.append = pd.Series._append

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))
engine = ProbabilityEngine()

def update_live_prices_and_emergencies():
    print("🔄 Intraday Pulse: Starting Sync...")
    
    try:
        port_res = supabase.table('portfolio').select('*').execute()
        portfolio = pd.DataFrame(port_res.data) if port_res.data else pd.DataFrame()
        port_symbols = [f"{s}.NS" for s in portfolio['symbol'].unique()] if not portfolio.empty else []
    except: portfolio, port_symbols = pd.DataFrame(), []

    master = pd.read_csv("Tickers.csv")
    symbols = [f"{str(s).strip()}.NS" for s in master['SYMBOL'].dropna().unique()]
    
    alerts = []
    
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i+50]
        try:
            data = yf.download(chunk, period="5d", group_by="ticker", threads=False, progress=False, ignore_tz=True)
            time.sleep(1.5)
        except: continue

        for sym in chunk:
            try:
                if len(chunk) > 1 and isinstance(data.columns, pd.MultiIndex):
                    if sym not in data.columns.get_level_values(0).unique(): continue
                    df = data[sym].copy()
                else: df = data.copy()
                
                df.dropna(inplace=True)
                if df.empty: continue
                
                curr_p = float(df['Close'].iloc[-1])
                if curr_p == 0: continue
                clean_sym = sym.replace(".NS", "")
                
                # Surgical Update: Only update the price, preserving Master Scan metrics
                supabase.table('market_scans').update({"PRICE": round(curr_p, 2), "UPDATED_AT": time.strftime('%Y-%m-%d %H:%M:%S')}).eq('SYMBOL', clean_sym).execute()

                # Portfolio Emergency Check
                if sym in port_symbols:
                    holding = portfolio[portfolio['symbol'] == clean_sym].iloc[0]
                    entry = float(holding['entry_price'])
                    
                    hist = yf.download(sym, period="3mo", progress=False, ignore_tz=True)
                    if not hist.empty:
                        damage, verdict, new_stop, reasoning = engine.calculate_exit_damage(clean_sym, entry, holding.get('date', datetime.date.today()), hist, {'PRICE': curr_p})
                        pnl_pct = ((curr_p - entry) / entry) * 100
                        
                        if curr_p <= entry * 0.90: alerts.append(f"🚨 {clean_sym}: GAP DOWN! CMP ₹{curr_p:.1f}. EXIT NOW!")
                        elif damage >= 70: alerts.append(f"⚠️ {clean_sym}: DAMAGE {damage}/100. CMP ₹{curr_p:.1f}. {reasoning}")
                        elif curr_p <= new_stop and pnl_pct < -2: alerts.append(f"🔴 {clean_sym}: STOP HIT! CMP ₹{curr_p:.1f} below ₹{new_stop:.1f}.")

            except: continue

    print("\n================ PORTFOLIO ALERTS ================")
    if alerts:
        for alert in alerts: print(alert)
    else: print("✅ All active holdings secure.")
    print("==================================================")

if __name__ == "__main__":
    ist_now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    is_market_open = (ist_now.hour == 9 and ist_now.minute >= 15) or (10 <= ist_now.hour <= 14) or (ist_now.hour == 15 and ist_now.minute <= 30)

    if is_market_open or True:
        print(f"Market Check ({ist_now.strftime('%H:%M')} IST). Running pulse...")
        update_live_prices_and_emergencies()
    else: print(f"Market CLOSED ({ist_now.strftime('%H:%M')} IST).")
