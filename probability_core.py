"""
Titan Quantum Pro V2.1 - Probability Core Engine
Institutional-grade entry probability, composite strength scoring, and exit damage scoring.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

def safe_float(val, default=0.0):
    if pd.isna(val) or np.isinf(val): return default
    return float(val)

class ProbabilityEngine:
    def __init__(self):
        # Default Bayesian Base Rates
        self.base_rates = {
            (90, 100): 0.78, (80, 89): 0.65, (70, 79): 0.52,
            (60, 69): 0.41, (50, 59): 0.30, (0, 49): 0.15
        }

    # ==========================================================
    # NEW V2.1 FEATURES
    # ==========================================================
    
    def calibrate_base_rates(self, supabase_client):
        """AI Feedback Loop: Adjusts base rates based on actual trade history."""
        try:
            res = supabase_client.table('trade_history').select('buy_price, sell_price').execute()
            df = pd.DataFrame(res.data)
            if len(df) > 10:
                wins = len(df[df['sell_price'] > df['buy_price']])
                actual_win_rate = wins / len(df)
                for k in self.base_rates:
                    self.base_rates[k] = (self.base_rates[k] * 0.7) + (actual_win_rate * 0.3)
                print(f"🧠 Base Rates Calibrated. User Win Rate: {actual_win_rate:.1%}")
        except: pass

    def calculate_volume_profile_sr(self, df, bins=20):
        """Calculates true Support/Resistance based on Volume Nodes & ATR."""
        if len(df) < 60: return df['Close'].iloc[-1] * 0.9, df['Close'].iloc[-1] * 1.1
        
        recent_df = df.iloc[-60:].copy()
        hist, bins_edges = np.histogram(recent_df['Close'], bins=bins, weights=recent_df['Volume'])
        cmp = recent_df['Close'].iloc[-1]
        
        # Dynamic Volatility (ATR) for Blue-Sky breakouts
        try:
            recent_df['ATR'] = recent_df['High'] - recent_df['Low']
            atr = recent_df['ATR'].rolling(14).mean().iloc[-1]
            if pd.isna(atr): atr = cmp * 0.02
        except: 
            atr = cmp * 0.02
        
        support_nodes = [(hist[i], (bins_edges[i] + bins_edges[i+1])/2) for i in range(len(hist)) if (bins_edges[i] + bins_edges[i+1])/2 < cmp]
        resistance_nodes = [(hist[i], (bins_edges[i] + bins_edges[i+1])/2) for i in range(len(hist)) if (bins_edges[i] + bins_edges[i+1])/2 > cmp]
            
        support = sorted(support_nodes, reverse=True)[0][1] if support_nodes else cmp - (2 * atr)
        # Replaces the flat 15% with a mathematical 3x ATR projection for all-time highs
        resistance = sorted(resistance_nodes, reverse=True)[0][1] if resistance_nodes else cmp + (3 * atr)
        
        return support, resistance
    
    def calculate_dynamic_stop(self, df, atr):
        """Context-Aware Stop Loss: max(1.8*ATR, Recent 10-day Swing Low)"""
        cmp = df['Close'].iloc[-1]
        atr_stop = cmp - (1.8 * atr)
        swing_low = df['Low'].iloc[-10:].min()
        structure_stop = swing_low * 0.99
        return max(atr_stop, structure_stop)

    def calculate_composite_score(self, daily_df, weekly_df, rs_status, earnings_risk=False):
        """Calculates composite strength summing all factors, applying VETO for critical risks."""
        score = 30 
        cmp = daily_df['Close'].iloc[-1]
        ema20 = daily_df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = daily_df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
        rsi = daily_df['RSI_14'].iloc[-1] if 'RSI_14' in daily_df else 50
        
        if cmp > ema20: score += 15
        if ema20 > ema50: score += 15
        if 55 <= rsi <= 75: score += 15 
        
        volume_ma = daily_df['Volume'].rolling(20).mean().iloc[-1]
        rvol = daily_df['Volume'].iloc[-1] / volume_ma if volume_ma > 0 else 1
        if rvol > 1.5: score += 10
        if rs_status == "Outperforming": score += 15

        verdict_override = None
        weekly_trend = "Neutral"
        
        if not weekly_df.empty:
            w_cmp = weekly_df['Close'].iloc[-1]
            w_ema50 = weekly_df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
            if w_cmp < w_ema50:
                weekly_trend = "Bearish"
                score -= 30 
                verdict_override = "🔴 AVOID (Weekly Bearish)"
            else:
                weekly_trend = "Bullish"
                score += 10

        if earnings_risk:
            score -= 20
            if verdict_override is None:
                verdict_override = "🟡 WATCH (Earnings Pending)"

        return max(0, min(100, score)), weekly_trend, verdict_override

    # ==========================================================
    # ORIGINAL FEATURES (RESTORED)
    # ==========================================================

    def get_intraday_adjustment(self, ist_time=None):
        if ist_time is None: ist_time = pd.Timestamp.now() + pd.Timedelta(hours=5, minutes=30)
        hour, minute = ist_time.hour, ist_time.minute
        if hour < 9 or (hour == 9 and minute < 15) or hour >= 16: return 1.0, 1.0, "EOD"
        if hour == 9 and minute >= 15: return 0.85, 0.1, "Morning Volatility"
        if hour == 10: return 0.90, 0.25, "Morning Trend"
        if 11 <= hour <= 13: return 0.95, 0.5, "Midday Lull"
        return 0.98, 0.8, "Afternoon Confirmation"

    def calculate_exit_damage(self, symbol, entry_price, entry_date, df, live_data=None):
        if df is None or df.empty: return 0, "HOLD", entry_price * 0.9, "No data"
        damage = 0
        reasons = []
        try: cmp = live_data['PRICE'] if live_data is not None else df['Close'].iloc[-1]
        except: cmp = df['Close'].iloc[-1]
        
        ema20 = df['EMA_20'].iloc[-1] if 'EMA_20' in df else df['Close'].ewm(span=20).mean().iloc[-1]
        ema50 = df['EMA_50'].iloc[-1] if 'EMA_50' in df else df['Close'].ewm(span=50).mean().iloc[-1]

        if cmp < ema20: damage += 25; reasons.append("Lost 20 EMA")
        if cmp < ema50: damage += 40; reasons.append("Lost 50 EMA")
        if 'RSI_14' in df and df['RSI_14'].iloc[-1] < 45: damage += 20; reasons.append("RSI < 45")
            
        new_stop = max(entry_price, ema50 * 0.98) if cmp > entry_price else entry_price * 0.92
        if damage >= 80: verdict = "🔴 EXIT IMMEDIATE"
        elif damage >= 50: verdict = "⚠️ SCALE OUT 50%"
        elif damage >= 30: verdict = "🟡 TIGHTEN STOP"
        else: verdict = "🟢 HOLD"
        return min(damage, 100), verdict, new_stop, ", ".join(reasons) if reasons else "Structure intact"

    def monte_carlo_target(self, df, current_price, atr, holding_period_days=7, simulations=500):
        if df.empty or len(df) < 20: return current_price * 1.05, current_price * 1.15, "N/A"
        returns = df['Close'].pct_change().dropna().iloc[-60:]
        if len(returns) < 20: return current_price * 1.05, current_price * 1.15, "N/A"
        mu, sigma = returns.mean(), returns.std()
        final_prices = [current_price * np.prod(1 + np.random.normal(mu, sigma, holding_period_days)) for _ in range(simulations)]
        final_prices = sorted(final_prices)
        return final_prices[int(simulations * 0.25)], final_prices[int(simulations * 0.80)], "Calculated"
