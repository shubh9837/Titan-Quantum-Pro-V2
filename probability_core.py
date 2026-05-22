"""
Titan Quantum Pro V2 - Probability Core Engine
Institutional-grade entry probability + exit damage scoring.
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
        self.base_rates = {
            (90, 100): 0.78, (80, 89): 0.65, (70, 79): 0.52,
            (60, 69): 0.41, (50, 59): 0.30, (0, 49): 0.15
        }

    def get_intraday_adjustment(self, ist_time=None):
        """
        Returns (confidence_multiplier, expected_volume_pct, session_label)
        for intraday scans to account for incomplete session data.
        """
        if ist_time is None:
            ist_time = pd.Timestamp.now() + pd.Timedelta(hours=5, minutes=30)
        hour, minute = ist_time.hour, ist_time.minute

        # Pre/post market
        if hour < 9 or (hour == 9 and minute < 15) or hour >= 16:
            return 1.0, 1.0, "EOD"

        # Elapsed minutes since 9:15
        market_open = ist_time.replace(hour=9, minute=15, second=0)
        elapsed = max(0, (ist_time - market_open).total_seconds() / 60)
        total_session = 375.0  # 6h 15m
        time_pct = elapsed / total_session

        # Volume expectation curve: heavier in first/last hour
        if hour < 11:
            expected_vol_pct = min(0.95, time_pct * 1.35)
        elif hour < 14:
            expected_vol_pct = min(0.95, time_pct * 0.88)
        else:
            expected_vol_pct = min(0.95, time_pct * 1.05)

        # Confidence discount early in day
        if hour < 10:
            conf_mult = 0.86
        elif hour < 11:
            conf_mult = 0.91
        elif hour < 13:
            conf_mult = 0.95
        else:
            conf_mult = 0.98

        return conf_mult, expected_vol_pct, f"Intraday ({hour:02d}:{minute:02d})"

    def detect_market_regime(self, nifty_df):
        """Detects market regime: Strong Bull, Bull, Bear, Volatile Bear, Sideways"""
        if nifty_df.empty or len(nifty_df) < 50:
            return "Unknown", 1.0

        close = nifty_df['Close']
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        curr = close.iloc[-1]

        atr = (nifty_df['High'] - nifty_df['Low']).rolling(14).mean().iloc[-1]
        vol_pct = safe_float(atr / curr * 100, 1.0)

        trend_score = 0
        if curr > ema20: trend_score += 1
        if ema20 > ema50: trend_score += 1
        if ema50 > ema200: trend_score += 1

        if trend_score >= 3 and vol_pct < 1.5:
            return "Strong Bull", 1.15
        elif trend_score >= 2 and vol_pct < 2.0:
            return "Bull", 1.08
        elif trend_score == 0 and vol_pct > 2.5:
            return "Volatile Bear", 0.65
        elif trend_score <= 1:
            return "Bear", 0.72
        else:
            return "Sideways", 0.90

def calculate_entry_probability(self, df, nifty_return_50d, sector_breadth,
                                market_sentiment, session_info=None, nifty_df_full=None):
        """
        Calculates Bayesian probability of trade success.
        session_info = (conf_mult, expected_vol_pct, session_label) for intraday.
        Returns: (confluence_score, probability_pct, regime_name, regime_mult, session_label)
        """
        curr_p = safe_float(df['Close'].iloc[-1])
        if curr_p == 0: return 0, 0, "Unknown", 1.0, "N/A"

        close_series = df['Close']
        ema20_d = close_series.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50_d = close_series.ewm(span=50, adjust=False).mean().iloc[-1]

        # Weekly trend
        df_w = df.resample('W-FRI').agg({'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}).dropna()
        weekly_ema20 = df_w['Close'].ewm(span=20, adjust=False).mean().iloc[-1] if len(df_w) >= 20 else 0

        # --- 1. TREND ALIGNMENT (0-25) ---
        trend_score = 0
        if curr_p > ema20_d: trend_score += 10
        if ema20_d > ema50_d: trend_score += 10
        if curr_p > weekly_ema20 and weekly_ema20 > 0: trend_score += 5

        # --- 2. MOMENTUM HEALTH (0-20) ---
        rsi = safe_float(df['RSI_14'].iloc[-1]) if 'RSI_14' in df else 50
        momentum_score = 0
        if 45 <= rsi <= 65: momentum_score += 12
        elif 35 <= rsi < 45: momentum_score += 8
        elif rsi > 65: momentum_score += 16

        if 'MACDh_12_26_9' in df:
            macd_hist = df['MACDh_12_26_9']
            if len(macd_hist) >= 3:
                slope = macd_hist.iloc[-1] - macd_hist.iloc[-3]
                if slope > 0: momentum_score += 4

        # --- 3. PRICE STRUCTURE (0-20) ---
        structure_score = 0
        res_20 = safe_float(df['High'].rolling(20).max().iloc[-1])
        sup_20 = safe_float(df['Low'].rolling(20).min().iloc[-1])
        dist_to_res = ((res_20 - curr_p) / curr_p * 100) if res_20 > 0 else 100

        if dist_to_res < 3: structure_score += 10
        elif dist_to_res < 8: structure_score += 6

        dist_above_sup = ((curr_p - sup_20) / curr_p * 100) if sup_20 > 0 else 0
        if dist_above_sup > 5: structure_score += 5

        if 'BBU_20_2.0' in df and 'BBL_20_2.0' in df:
            bb_width = (df['BBU_20_2.0'].iloc[-1] - df['BBL_20_2.0'].iloc[-1]) / curr_p * 100
            if bb_width < 5: structure_score += 5

        # --- 4. VOLUME SIGNATURE (0-15) ---
        vol_score = 0
        avg_vol = safe_float(df['Volume'].rolling(20).mean().iloc[-1])
        curr_vol = safe_float(df['Volume'].iloc[-1])
        rvol = curr_vol / avg_vol if avg_vol > 0 else 0

        # Intraday volume adjustment
        if session_info and session_info[1] > 0 and session_info[1] < 1.0:
            true_rvol = rvol / session_info[1]
        else:
            true_rvol = rvol

        if len(df) >= 10:
            recent_vol = df['Volume'].iloc[-5:].mean()
            prev_vol = df['Volume'].iloc[-10:-5].mean()
            if recent_vol > prev_vol * 1.3: vol_score += 5

        if true_rvol > 2.0: vol_score += 10
        elif true_rvol > 1.5: vol_score += 7
        elif true_rvol > 1.0: vol_score += 4

        # --- 5. RELATIVE STRENGTH (0-10) ---
        rs_score = 0
        stock_ret_50d = (curr_p - safe_float(df['Close'].iloc[-50])) / safe_float(df['Close'].iloc[-50])
        rs_vs_nifty = stock_ret_50d - nifty_return_50d

        if rs_vs_nifty > 0.15: rs_score += 10
        elif rs_vs_nifty > 0.08: rs_score += 7
        elif rs_vs_nifty > 0.03: rs_score += 4
        elif rs_vs_nifty > 0: rs_score += 2

        # --- 6. MACRO SAFETY (0-10) ---
        safety_score = 0
        if market_sentiment > 0.3: safety_score += 5
        elif market_sentiment > 0: safety_score += 3
        safety_score += 5  # Base earnings safety

        # --- TOTAL ---
        confluence = min(100, trend_score + momentum_score + structure_score + 
                        vol_score + rs_score + safety_score)

        # --- BAYESIAN PROBABILITY ---
        base_rate = 0.15
        for (low, high), rate in self.base_rates.items():
            if low <= confluence <= high:
                base_rate = rate
                break

# Use passed NIFTY data, fallback to download only if not provided
if nifty_df_full is None or nifty_df_full.empty:
    nifty_df_full = yf.download("^NSEI", period="6mo", progress=False, ignore_tz=True)
    if isinstance(nifty_df_full.columns, pd.MultiIndex):
        nifty_df_full.columns = [c[0] for c in nifty_df_full.columns]
regime_name, regime_mult = self.detect_market_regime(nifty_df_full)

        # Sector
        sector_mult = 0.85 + (sector_breadth * 0.003) if sector_breadth else 1.0
        sector_mult = min(1.12, max(0.70, sector_mult))

        # RS filter
        rs_mult = 1.0 + (rs_vs_nifty * 0.5) if rs_vs_nifty > 0 else max(0.85, 1.0 + (rs_vs_nifty * 0.3))
        rs_mult = min(1.10, max(0.80, rs_mult))

        probability = base_rate * regime_mult * sector_mult * rs_mult

        # Intraday confidence discount
        session_label = "EOD"
        if session_info:
            probability *= session_info[0]
            session_label = session_info[2]

        probability = min(0.98, max(0.05, probability))

        return confluence, round(probability * 100, 1), regime_name, regime_mult, session_label

    def calculate_exit_damage(self, sym, entry_price, entry_date, current_df, live_data_row=None):
        """
        Calculates damage score for a FALLING or at-risk holding.
        Returns: (damage_score, verdict, new_stop, reasoning)
        """
        if current_df.empty or len(current_df) < 20:
            return 0, "HOLD", entry_price * 0.92, "Insufficient data"

        curr_p = safe_float(current_df['Close'].iloc[-1])
        if curr_p == 0: return 0, "HOLD", entry_price * 0.92, "No price data"

        damage = 0
        reasons = []
        close_s = current_df['Close']

        # --- STRUCTURAL DAMAGE (0-40) ---
        ema20 = close_s.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close_s.ewm(span=50, adjust=False).mean().iloc[-1]
        sup_20 = safe_float(current_df['Low'].rolling(20).min().iloc[-1])

        if curr_p < ema20: 
            damage += 15
            reasons.append("Broke 20 EMA")
        if close_s.iloc[-1] < ema50 and close_s.iloc[-5] > ema50:
            damage += 20
            reasons.append("Fresh 50 EMA break")
        elif curr_p < ema50:
            damage += 10
            reasons.append("Below 50 EMA")
        if curr_p < sup_20 * 1.02:
            damage += 10
            reasons.append("Support violated")

        # --- MOMENTUM REVERSAL (0-30) ---
        rsi = safe_float(current_df['RSI_14'].iloc[-1]) if 'RSI_14' in current_df else 50
        if rsi < 30: 
            damage += 20
            reasons.append("RSI oversold (<30)")
        elif rsi < 40:
            damage += 12
            reasons.append("RSI weakening (<40)")

        if 'MACD_12_26_9' in current_df and 'MACDs_12_26_9' in current_df:
            macd_line = current_df['MACD_12_26_9']
            signal_line = current_df['MACDs_12_26_9']
            if len(macd_line) >= 2:
                if macd_line.iloc[-2] > signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
                    damage += 15
                    reasons.append("MACD bearish cross")
                elif macd_line.iloc[-1] < signal_line.iloc[-1]:
                    damage += 8
                    reasons.append("MACD below signal")

        # --- VOLUME SIGNATURE (0-20) ---
        avg_vol = safe_float(current_df['Volume'].rolling(20).mean().iloc[-1])
        curr_vol = safe_float(current_df['Volume'].iloc[-1])
        if avg_vol > 0 and curr_vol > avg_vol * 1.8:
            if current_df['Close'].iloc[-1] < current_df['Open'].iloc[-1]:
                damage += 15
                reasons.append("Heavy selling volume")
            else:
                damage += 5
                reasons.append("High volume (watch)")

        # --- TIME DECAY (0-10) ---
        try:
            entry_dt = pd.to_datetime(entry_date).date()
            days_held = (pd.Timestamp.now().date() - entry_dt).days
            pnl_pct = (curr_p - entry_price) / entry_price * 100

            if days_held > 21 and pnl_pct < -3:
                damage += 10
                reasons.append(f"Dead money ({days_held}d, {pnl_pct:.1f}%)")
            elif days_held > 14 and pnl_pct < -5:
                damage += 7
                reasons.append(f"Time decay ({days_held}d)")
            elif days_held > 30:
                damage += 5
                reasons.append(f"Held too long ({days_held}d)")
        except:
            pass

        damage = min(100, damage)

        # --- VERDICT & ADAPTIVE STOP ---
        if damage <= 30:
            verdict = "HOLD"
            new_stop = entry_price * 0.92
        elif damage <= 55:
            verdict = "TIGHTEN STOP"
            new_stop = max(entry_price * 0.98, curr_p * 0.95)
        elif damage <= 80:
            verdict = "SCALE OUT 50%"
            new_stop = curr_p * 0.97
        else:
            verdict = "EXIT IMMEDIATE"
            new_stop = curr_p * 0.96

        reasoning = " | ".join(reasons) if reasons else "Structure intact"
        return damage, verdict, new_stop, reasoning

    def monte_carlo_target(self, df, current_price, atr, holding_period_days=7, simulations=500):
        """
        Monte Carlo simulation for target price range.
        Returns: (conservative_target, optimistic_target, probability_range_str)
        """
        if df.empty or len(df) < 20:
            return current_price * 1.05, current_price * 1.15, "N/A"

        returns = df['Close'].pct_change().dropna().iloc[-60:]
        if len(returns) < 20:
            return current_price * 1.05, current_price * 1.15, "N/A"

        mu = returns.mean()
        sigma = returns.std()

        vol_regime = "normal"
        if sigma > 0.025: vol_regime = "high"
        elif sigma < 0.008: vol_regime = "low"

        final_prices = []
        for _ in range(simulations):
            price = current_price
            for _ in range(holding_period_days):
                daily_return = np.random.normal(mu, sigma)
                price *= (1 + daily_return)
            final_prices.append(price)

        final_prices = sorted(final_prices)
        conservative = final_prices[int(simulations * 0.60)]
        optimistic = final_prices[int(simulations * 0.85)]
        prob_above = sum(1 for p in final_prices if p > current_price) / simulations * 100

        return conservative, optimistic, f"{prob_above:.0f}% profit chance in {holding_period_days}D ({vol_regime} vol)"
