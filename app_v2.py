import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import pytz
import datetime  
import plotly.graph_objects as go
import plotly.express as px
from supabase import create_client
from probability_core import ProbabilityEngine
from titan_agent import parse_trade_text, parse_order_image, get_response
import pandas_ta_classic as ta

if not hasattr(pd.Series, "append"): pd.Series.append = pd.Series._append

def safe_rerun():
    try: st.rerun()
    except:
        try: st.experimental_rerun()
        except: pass

IST = pytz.timezone('Asia/Kolkata')
def get_ist_now(): return datetime.datetime.now(IST)

st.set_page_config(page_title="Titan Quantum Pro V2.1", layout="wide", page_icon="💎")

# ===================== CSS STYLING & MOBILE FIX =====================
st.markdown("""
<style>
    .main { background-color: #0B0E14; color: #E0E6ED; font-family: 'Inter', sans-serif; }
    .stButton>button { 
        background: linear-gradient(135deg, #00B8FF 0%, #0073FF 100%);
        color: white; font-weight: 600; border-radius: 8px; border: none;
        transition: all 0.3s ease; box-shadow: 0 4px 6px rgba(0, 184, 255, 0.2);
    }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0, 184, 255, 0.4); }
    div[data-testid="metric-container"] {
        background-color: #141824; border: 1px solid #2A3143; border-radius: 12px; padding: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }
    .streamlit-expanderHeader { background-color: #141824; border-radius: 8px; }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    .gradient-text {
        background: -webkit-linear-gradient(45deg, #00B8FF, #00FF88);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 800; margin-bottom: 0;
    }
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetricValue"]) {
            flex-wrap: nowrap !important; overflow-x: auto !important; -webkit-overflow-scrolling: touch; padding-bottom: 10px;
        }
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetricValue"]) > [data-testid="column"] { min-width: 180px !important; }
        [data-testid="stMetricValue"] { font-size: 1.8rem !important; }
    }
    .emergency-marquee { background-color: #FF4B4B; color: white; padding: 15px; border-radius: 10px; font-weight: bold; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(255, 75, 75, 0.4); }
</style>
""", unsafe_allow_html=True)

# ===================== INIT & DATABASE =====================
@st.cache_resource
def init_connection(): return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
supabase = init_connection()
engine = ProbabilityEngine()

def get_base_verdict(score):
    if score >= 90: return "💎 ALPHA"
    if score >= 75: return "🟢 STRONG BUY"
    if score >= 60: return "🟢 BUY"
    if score >= 45: return "🟡 WATCH"
    return "🔴 AVOID"

@st.cache_data(ttl=120)
def load_market_data():
    all_data, limit, offset = [], 1000, 0
    while True:
        res = supabase.table('market_scans').select("*").range(offset, offset + limit - 1).execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < limit: break
        offset += limit
    df = pd.DataFrame(all_data)
    if df.empty: return df
    
    num_cols = ['PRICE', 'SCORE', 'PROBABILITY', 'TARGET', 'STOP_LOSS', 'RR_RATIO', 'UPSIDE_PCT', 'TURNOVER_CR', 'RVOL', 'SUPPORT', 'RESISTANCE']
    for col in num_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
    if 'SCORE' in df.columns: df['CLEAN_VERDICT'] = df['SCORE'].apply(get_base_verdict)
    return df

@st.cache_data(ttl=300)
def load_table(table_name):
    try: return pd.DataFrame(supabase.table(table_name).select("*").execute().data)
    except: return pd.DataFrame()

# ===================== KNOWLEDGE BASE =====================
KNOWLEDGE = {
    "score": "#### 📊 Confluence Score (0-100)\nCombines technical factors. **Trend (Max +30):** Price > 20 EMA > 50 EMA. **Momentum (Max +15):** RSI between 55-75. **Volume (Max +10):** RVOL > 1.5x. **RS (Max +15):** Outperforming NIFTY 50.\n*Veto Penalty:* Weekly Trend breakdown removes 30 pts.",
    "probability": "#### 🎯 Win Probability %\nBayesian probability calculated from historical base rates calibrated with your personal win rate. 75% means historically 3 out of 4 setups with this score hit their target.",
    "damage": "#### 💀 Damage Score (0-100)\nMeasures deterioration: **0-30:** Normal pullback. **31-55:** TIGHTEN STOP. **56-80:** SCALE OUT 50%. **81-100:** EXIT IMMEDIATE.",
    "rvol": "#### 📈 RVOL & Turnover\n**RVOL:** Current volume / 20-day average. **Turnover:** Daily traded value in Crores. Avoid stocks under 5 Cr.",
    "rr": "#### ⚖️ Risk:Reward Ratio\nPotential reward / risk. 1:2 means risking Rs.1 to make Rs.2. Target minimum 1:1.5.",
    "pattern": "#### 🕯️ Volume Profile S&R\nV2.1 calculates resistance based on the Point of Control (where max volume traded), not just random wicks.",
    "regime": "#### 🌍 Market Regime\n**Strong Bull:** Nifty > 20 EMA. **Caution:** Below 20 EMA but > 50 EMA. **Bearish:** Below 50 EMA. Cash is a position."
}

# ===================== HELPERS & CHARTING =====================
def get_index_data(ticker_symbol):
    try:
        idx = yf.Ticker(ticker_symbol)
        hist = idx.history(period="5d")
        if len(hist) >= 2: return hist['Close'].iloc[-1], ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
    except: return None, None
    return None, None

@st.cache_data(ttl=300)
def fetch_chart_data(symbol):
    try:
        df = yf.download(f"{symbol}.NS", period="3mo", progress=False, ignore_tz=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = [c[0] for c in df.columns]
        return df
    except: return pd.DataFrame()

def render_interactive_chart(symbol, unique_key_suffix=""):
    try:
        data = fetch_chart_data(symbol).copy() 
        if data.empty: return st.error(f"Chart data unavailable for {symbol}.")
        
        data['EMA20'] = data['Close'].ewm(span=20, adjust=False).mean()
        data['EMA50'] = data['Close'].ewm(span=50, adjust=False).mean()

        fig = go.Figure(data=[go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name='Price', increasing_line_color='#00FF88', decreasing_line_color='#FF4B4B')])
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA20'], line=dict(color='#00B8FF', width=1.5), name='20 EMA'))
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA50'], line=dict(color='#FFC107', width=1.5), name='50 EMA'))
        fig.update_layout(title=dict(text=f"{symbol} - Live Technicals", font=dict(color='#E0E6ED')), template='plotly_dark', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', height=400, margin=dict(l=0, r=0, t=40, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{symbol}_{unique_key_suffix}")
    except: pass

@st.cache_data(ttl=60)
def get_macro_weather():
    now_ist = get_ist_now()
    try:
        if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
            gift, gift_pct = get_index_data("GIFNIF.NS")
            sp500, sp_pct = get_index_data("^GSPC")
            direction = gift_pct if gift_pct is not None else sp_pct if sp_pct is not None else 0
            if direction > 0.4: return "🐂 GLOBAL CUES: POSITIVE", "Expect a Gap-Up opening.", "green"
            elif direction < -0.4: return "🐻 GLOBAL CUES: NEGATIVE", "Expect a weak opening. Caution.", "red"
            else: return "⚖️ GLOBAL CUES: FLAT", "Expect a flat opening.", "yellow"
        else:
            nifty_daily = yf.download("^NSEI", period="3mo", progress=False, ignore_tz=True)
            if isinstance(nifty_daily.columns, pd.MultiIndex): nifty_daily.columns = [c[0] for c in nifty_daily.columns]
            if nifty_daily.empty: return "📡 DATA DELAYED", "NIFTY data temporarily unavailable.", "gray"
            
            nifty_live = yf.download("^NSEI", period="1d", interval="5m", progress=False, ignore_tz=True)
            if isinstance(nifty_live.columns, pd.MultiIndex): nifty_live.columns = [c[0] for c in nifty_live.columns]

            if not nifty_live.empty:
                close = float(nifty_live['Close'].iloc[-1])
                prev_close = float(nifty_daily['Close'].iloc[-2]) if len(nifty_daily) > 1 else close
                nifty_pct = ((close - prev_close) / prev_close) * 100
            else:
                close = float(nifty_daily['Close'].iloc[-1])
                prev_close = float(nifty_daily['Close'].iloc[-2]) if len(nifty_daily) > 1 else close
                nifty_pct = ((close - prev_close) / prev_close) * 100
            
            ema20 = nifty_daily['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = nifty_daily['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
            idx_str = f"NIFTY: {close:.2f} ({nifty_pct:+.2f}%)"
            
            if close > ema20: return "🐂 RISK ON (BULLISH)", f"{idx_str} | Uptrend above 20 EMA.", "green"
            elif close > ema50: return "⚖️ CAUTION (SIDEWAYS)", f"{idx_str} | Below 20 EMA but holding 50 EMA.", "yellow"
            else: return "🐻 RISK OFF (BEARISH)", f"{idx_str} | Active downtrend. CASH IS KING.", "red"
    except: return "📡 UNKNOWN", "Macro weather currently unavailable.", "gray"

def format_score_icon(val):
    if val >= 80: return f"🌟 {val:.0f}"
    elif val >= 60: return f"⭐ {val:.0f}"
    else: return f"🔸 {val:.0f}"

def format_prob_icon(val):
    if val >= 70: return f"🟢 {val:.0f}%"
    elif val >= 50: return f"🟡 {val:.0f}%"
    else: return f"🔴 {val:.0f}%"

def get_exit_badge(verdict):
    v = str(verdict).upper()
    if 'EXIT IMMEDIATE' in v: return '🔴 EXIT IMMEDIATE'
    if 'SCALE OUT' in v: return '⚠️ SCALE OUT 50%'
    if 'TIGHTEN' in v: return '🟡 TIGHTEN STOP'
    return '🟢 HOLD'

# ===================== LOAD DATA & OWNERS =====================
df = load_market_data()
sector_breadth_df = load_table('sector_breadth')
port_df = load_table('portfolio')
hist_df = load_table('trade_history')

p_owners = []
if not port_df.empty:
    if 'owner' not in port_df.columns: port_df['owner'] = "Main"
    port_df['owner'] = port_df['owner'].fillna("Main")
    p_owners = port_df['owner'].tolist()

h_owners = []
if not hist_df.empty:
    if 'owner' not in hist_df.columns: hist_df['owner'] = "Main"
    hist_df['owner'] = hist_df['owner'].fillna("Main")
    h_owners = hist_df['owner'].tolist()

db_owners = list(set(p_owners + h_owners))
db_owners = sorted([o for o in db_owners if pd.notna(o)]) if db_owners else ["Main"]

default_owner_idx = 0
if not port_df.empty:
    active_owners = port_df['owner'].unique().tolist()
    for i, owner in enumerate(db_owners):
        if owner in active_owners:
            default_owner_idx = i; break

# ===================== PORTFOLIO CALCULATIONS (For Marquee) =====================
critical_alerts, port_calc, total_risk = [], [], 0

if not port_df.empty:
    @st.cache_data(ttl=300)
    def fetch_safe_portfolio_history(symbols):
        h_dict = {}
        for sym in symbols:
            try: h_dict[sym] = fetch_chart_data(sym)
            except: h_dict[sym] = pd.DataFrame()
        return h_dict

    bulk_hist = fetch_safe_portfolio_history(port_df['symbol'].unique().tolist())
    
    for _, row in port_df.iterrows():
        sym = row['symbol']
        live = df[df['SYMBOL'] == sym].iloc[0] if not df.empty and sym in df['SYMBOL'].values else None
        cmp = float(live['PRICE']) if live is not None else float(row['entry_price'])
        entry, qty = float(row['entry_price']), int(row['qty'])
        
        hist_data = bulk_hist.get(sym, pd.DataFrame()).copy()
        hist_data.dropna(inplace=True)

        dmg, verdict, stop, reason = engine.calculate_exit_damage(sym, entry, row.get('date', datetime.date.today()), hist_data, live)
        total_risk += max(0, cmp - stop) * qty
        
        if cmp <= stop: critical_alerts.append(f"🚨 {sym} HIT STOP LOSS! (CMP: ₹{cmp:.2f} vs SL: ₹{stop:.2f})")
        elif dmg >= 70: critical_alerts.append(f"⚠️ {sym} HIGH DAMAGE ({dmg}/100). Suggestion: SCALE OUT OR EXIT.")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.markdown("<h3 class='gradient-text'>💎 Titan Quantum Pro</h3>", unsafe_allow_html=True)
    st.caption(f"IST Sync: {get_ist_now().strftime('%d %b %H:%M')}")
    if st.button("🔄 Refresh Data", use_container_width=True):
        load_market_data.clear(); load_table.clear(); safe_rerun()

    st.markdown("---")
    st.markdown("### 🛡️ Account Safety Limits")
    acc_size = st.number_input("Total Account Capital (Rs.)", value=100000, step=10000)

    st.markdown("---")
    st.markdown("### 🤖 Titan Agent")
    agent_input = st.text_input("💬 Trade command:", placeholder="e.g. Bought 50 INFY at 1400")
    uploaded_image = st.file_uploader("📷 Order Screenshot", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 Process Intelligence", use_container_width=True):
        if uploaded_image:
            res = parse_order_image(uploaded_image)
            if 'error' not in res: st.session_state['agent_result'] = res
            else: st.error("Image OCR failed.")
        elif agent_input:
            res = parse_trade_text(agent_input)
            response = get_response(res, portfolio_df=port_df, market_df=df)
            st.markdown(f"<div style='background:#141824; border:1px solid #2A3143; padding:15px; border-radius:10px;'>{response}</div>", unsafe_allow_html=True)
            if res and res.get('action') == 'BUY': st.session_state['agent_result'] = res

    if 'agent_result' in st.session_state and st.session_state['agent_result'].get('action') == 'BUY':
        res = st.session_state['agent_result']
        st.success(f"Detected: BUY {res['qty']} {res['symbol']} @ ₹{res['price']}")
        
        a_own = st.selectbox("Assign Owner", db_owners + ["+ Add New Portfolio"])
        f_own = st.text_input("New Name:") if a_own == "+ Add New Portfolio" else a_own
            
        if st.button("✅ Confirm & Log", use_container_width=True):
            if f_own:
                supabase.table('portfolio').insert({"symbol": res['symbol'], "entry_price": res['price'], "qty": res['qty'], "date": str(datetime.date.today()), "owner": f_own}).execute()
                st.success("Logged!"); del st.session_state['agent_result']; load_table.clear(); safe_rerun()

# ===================== HEADER & ALERTS =====================
st.markdown("<div style='text-align:center;'><h1 class='gradient-text' style='font-size: 3rem;'>Titan Quantum Pro V2.1</h1></div>", unsafe_allow_html=True)

now_ist = get_ist_now()
if now_ist.hour == 9 and now_ist.minute < 15: pass
elif now_ist.hour == 9 and now_ist.minute <= 59:
    st.warning("⏳ **10:15 AM RULE ACTIVE:** The market is currently in the high-volatility opening hour. Pros wait until 10:15 AM for institutional trends to settle before executing new buys.", icon="⏳")

if critical_alerts:
    for alert in critical_alerts: st.markdown(f"<div class='emergency-marquee'>{alert}</div>", unsafe_allow_html=True)

status, msg, css_class = get_macro_weather()
border_color = "#00FF88" if "green" in css_class else "#FF4B4B" if "red" in css_class else "#A0ABBA" if "gray" in css_class else "#FFC107"
bg_color = f"rgba({0 if 'green' in css_class else 255 if 'red' in css_class else 160 if 'gray' in css_class else 255}, {255 if 'green' in css_class else 75 if 'red' in css_class else 171 if 'gray' in css_class else 193}, {136 if 'green' in css_class else 75 if 'red' in css_class else 186 if 'gray' in css_class else 7}, 0.05)"

st.markdown(f"""
<div style='border-left: 5px solid {border_color}; padding: 20px; background-color: {bg_color}; border-radius: 10px; margin-bottom: 25px; box-shadow: 0 4px 10px rgba(0,0,0,0.2);'>
    <h4 style='margin:0; color: {border_color};'>{status}</h4>
    <p style='margin:8px 0 0 0; color:#E0E6ED; font-weight: 500;'>{msg}</p>
</div>
""", unsafe_allow_html=True)

if not df.empty and 'UPDATED_AT' in df.columns:
    try:
        latest_update = pd.to_datetime(df['UPDATED_AT'].max()).tz_localize('UTC').tz_convert(IST)
        delta_hours = (get_ist_now() - latest_update).total_seconds() / 3600
        if delta_hours > 24 and get_ist_now().weekday() < 5:
            st.error(f"🔴 DATA DELAY: Backend data is {int(delta_hours)} hours old. Please trigger Master Scan.", icon="🚨")
    except: pass

# ===================== TABS =====================
tabs = st.tabs(["📋 Today's Top Picks", "💼 Portfolio Intelligence", "🔍 Market Screener", "⚡ Breakout Radar", "🎰 Penny Sandbox", "🏆 History", "📚 Knowledge Hub"])

with tabs[0]:
    st.subheader("🎯 Today's Top Buy Opportunities")
    st.caption("Filtered for liquidity (Turnover > 5Cr) and high probability setups.")

    if not df.empty:
        inst_df = df[df['TURNOVER_CR'] >= 5.0].copy() 
        actionable = inst_df[(inst_df['PROBABILITY'] >= 60) & (inst_df['SCORE'] >= 60) & (~inst_df['CLEAN_VERDICT'].str.contains('AVOID', na=False))].copy()
        
        if not actionable.empty:
            actionable['Est_Qty'] = (10000 / actionable['PRICE']).astype(int)
            actionable = actionable.sort_values(['SCORE', 'PROBABILITY', 'UPSIDE_PCT'], ascending=[False, False, False]).head(10)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📊 Avg Probability", f"{actionable['PROBABILITY'].mean():.0f}%")
            c2.metric("⭐ Avg Score", f"{actionable['SCORE'].mean():.0f}")
            c3.metric("⚖️ Avg R:R", f"1:{actionable['RR_RATIO'].mean():.1f}")
            c4.metric("🔥 Top Picks (Liquid)", f"{len(actionable)}")

            display_df = actionable[['CLEAN_VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'EST_PERIOD', 'RELATIVE_STRENGTH', 'EARNINGS_RISK']].copy()
            display_df['PROBABILITY'] = display_df['PROBABILITY'].apply(format_prob_icon)
            display_df['SCORE'] = display_df['SCORE'].apply(format_score_icon)
            display_df['RELATIVE_STRENGTH'] = display_df['RELATIVE_STRENGTH'].apply(lambda x: "🔥 Outperforming" if "Outperform" in x else "Neutral")
            display_df['EARNINGS_RISK'] = display_df['EARNINGS_RISK'].apply(lambda x: "⚠️ YES" if x == "YES" else "No")
            
            st.dataframe(display_df.rename(columns={'CLEAN_VERDICT': 'Verdict'}).style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%'}), use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("💎 Detailed Analysis (Top Picks)")
            
            for idx, (_, g) in enumerate(actionable.head(5).iterrows()):
                rs_badge = "<span style='background:#00FF88; color:#000; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;'>Market Leader</span>" if "Outperform" in g['RELATIVE_STRENGTH'] else ""
                prob_color = "#00FF88" if g['PROBABILITY'] >= 75 else "#FFC107" if g['PROBABILITY'] >= 60 else "#FF4B4B"

                st.markdown(f"""
                <div style='background:#141824; padding:20px; border-radius:12px; margin-bottom:10px; border-left:5px solid {prob_color}; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'>
                    <h3 style='margin:0; color:#E0E6ED;'>{g['SYMBOL']} {rs_badge}</h3>
                    <div style='display:flex; flex-wrap:wrap; gap:25px; margin-top:15px;'>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Win Prob</div><div style='font-size:22px; font-weight:bold; color:{prob_color};'>{g['PROBABILITY']:.0f}%</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>CMP</div><div style='font-size:20px; color:#E0E6ED;'>Rs.{g['PRICE']:.2f}</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Target (Vol Profile)</div><div style='font-size:20px; color:#00FF88;'>Rs.{g['TARGET']:.2f} <span style='font-size:14px;'>(+{g['UPSIDE_PCT']:.0f}%)</span></div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Trailing SL</div><div style='font-size:20px; color:#FF4B4B;'>Rs.{g['STOP_LOSS']:.2f}</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>R:R</div><div style='font-size:20px; color:#E0E6ED;'>1:{g['RR_RATIO']:.1f}</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Expected Time</div><div style='font-size:20px; color:#E0E6ED;'>{g['EST_PERIOD']}</div></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                with st.expander(f"📊 Chart & Action ({g['SYMBOL']})"):
                    render_interactive_chart(g['SYMBOL'], f"top_{idx}")
                    col1, col2 = st.columns([1, 2])
                    with col1: st.info(f"💡 Suggestion: **{g['Est_Qty']}** shares (₹10k)")
                    with col2:
                        sel = st.selectbox("Select Existing Owner", db_owners, key=f"sel_{idx}", index=default_owner_idx)
                        f_own_input = st.text_input("OR Create New Owner:", key=f"fown_{idx}") 
                        final_own = f_own_input.strip() if f_own_input.strip() else sel
                        
                        if st.button(f"➕ Quick Add to Portfolio", key=f"add_{idx}"):
                            if total_risk > (acc_size * 0.03): st.error("🚨 **PORTFOLIO STRESS LIMIT REACHED.** Your total portfolio stop-loss risk currently exceeds 3% of your account size. Do not add new positions.")
                            elif final_own:
                                supabase.table('portfolio').insert({"symbol": g['SYMBOL'], "entry_price": g['PRICE'], "qty": int(g['Est_Qty']), "date": str(datetime.date.today()), "owner": final_own}).execute()
                                st.success(f"Added to {final_own}'s ledger!"); load_table.clear(); safe_rerun()
        else: st.info("🟡 No safe setups matching your strategy criteria. Cash is a position.")
    else: st.error("No data available.")

with tabs[1]:
    view_owner = st.selectbox("👤 Select Portfolio to View", db_owners, index=default_owner_idx)
    active_port = port_df[port_df['owner'] == view_owner] if not port_df.empty else pd.DataFrame()

    if not active_port.empty:
        @st.cache_data(ttl=300)
        def fetch_safe_portfolio_history(symbols):
            h_dict = {}
            for sym in symbols:
                try: h_dict[sym] = fetch_chart_data(sym)
                except: h_dict[sym] = pd.DataFrame()
            return h_dict

        bulk_hist = fetch_safe_portfolio_history(active_port['symbol'].unique().tolist())
        port_calc_view, view_dmg, view_risk = [], 0, 0

        for _, row in active_port.iterrows():
            sym = row['symbol']
            live = df[df['SYMBOL'] == sym].iloc[0] if not df.empty and sym in df['SYMBOL'].values else None
            cmp = float(live['PRICE']) if live is not None else float(row['entry_price'])
            entry, qty = float(row['entry_price']), int(row['qty'])
            sector = str(live['SECTOR']) if live is not None else "Unknown"
            
            try: days_held = (datetime.date.today() - pd.to_datetime(row.get('date', datetime.date.today())).date()).days
            except: days_held = 0

            hist_data = bulk_hist.get(sym, pd.DataFrame()).copy()
            hist_data.dropna(inplace=True)

            dmg, verdict, stop, reason = engine.calculate_exit_damage(sym, entry, row.get('date', datetime.date.today()), hist_data, live)
            view_dmg += dmg
            
            locked_target = float(live['TARGET']) if live is not None else entry * 1.15
            pnl_pct = ((cmp - entry) / entry) * 100
            val = cmp * qty
            view_risk += max(0, cmp - stop) * qty
            
            sl_proximity = ""
            if cmp <= stop: sl_proximity = "🔴 HIT"
            elif cmp <= stop * 1.02: sl_proximity = "⚠️ NEAR"

            port_calc_view.append({
                "symbol": sym, "sector": sector, "qty": qty, "entry": entry, "cmp": cmp, "pnl_pct": pnl_pct, "profit": qty * (cmp - entry),
                "invested": entry * qty, "val": val, "stop": stop, "locked_target": locked_target, "days_held": days_held, "proximity": sl_proximity, "damage": dmg, "verdict": get_exit_badge(verdict)
            })

        pdf = pd.DataFrame(port_calc_view)
        t_inv, t_cur = pdf['invested'].sum(), pdf['val'].sum()
        
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("💰 Total Invested", f"Rs.{t_inv:,.2f}")
        c2.metric("📈 Current Value", f"Rs.{t_cur:,.2f}", f"Rs.{t_cur - t_inv:,.2f}")
        c3.metric("🎯 Net P&L %", f"{(t_cur - t_inv) / t_inv * 100:.2f}%" if t_inv > 0 else "0%")
        c4.metric("⚠️ Avg Damage", f"{view_dmg / len(pdf):.0f}/100", delta_color="inverse")
        
        risk_pct = (view_risk / acc_size * 100) if acc_size > 0 else 0
        c5.metric("🔥 Total Risk (SL Heat)", f"Rs.{view_risk:,.2f}", f"{risk_pct:.1f}% of Account", delta_color="inverse")

        st.markdown("##### 🥧 Allocation Breakdown")
        pc1, pc2 = st.columns(2)
        colors = px.colors.qualitative.Pastel
        with pc1:
            fig_sym = px.pie(pdf, values='val', names='symbol', title="Holding Allocation", hole=0.4, color_discrete_sequence=colors)
            fig_sym.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=350, margin=dict(t=30, b=0, l=0, r=0))
            st.plotly_chart(fig_sym, use_container_width=True)
        with pc2:
            fig_sec = px.pie(pdf, values='val', names='sector', title="Sector Allocation", hole=0.4, color_discrete_sequence=colors)
            fig_sec.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=350, margin=dict(t=30, b=0, l=0, r=0))
            st.plotly_chart(fig_sec, use_container_width=True)

        st.markdown("##### 📊 Active Holdings")
        def color_pnl(val): return f"color: {'#00FF88' if val > 0 else '#FF4B4B' if val < 0 else 'white'}; font-weight: bold;"
        
        display_pdf = pdf[['verdict', 'damage', 'symbol', 'qty', 'entry', 'cmp', 'pnl_pct', 'profit', 'locked_target', 'stop', 'proximity', 'days_held']].rename(
            columns={'verdict': 'Action', 'damage': 'Damage', 'symbol': 'Stock', 'qty': 'Qty', 'entry': 'Entry (₹)', 'cmp': 'CMP (₹)', 'pnl_pct': 'P&L (%)', 'profit': 'P&L (₹)', 'locked_target': 'Target (₹)', 'stop': 'Trail SL (₹)', 'proximity': 'SL Alert', 'days_held': 'Days Held'}
        )
        st.dataframe(display_pdf.style.format({"Entry (₹)": "{:.2f}", "CMP (₹)": "{:.2f}", "P&L (%)": "{:.2f}%", "P&L (₹)": "{:.2f}", "Target (₹)": "{:.2f}", "Trail SL (₹)": "{:.2f}", "Damage": "{:.0f}"}).map(color_pnl, subset=['P&L (%)', 'P&L (₹)']), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🔍 Detailed Chart View")
        selected_stock = st.selectbox("Select holding to analyze:", ["-- Select --"] + sorted(pdf['symbol'].tolist()))
        if selected_stock != "-- Select --":
            g = pdf[pdf['symbol'] == selected_stock].iloc[0]
            prob_color = "#00FF88" if g['pnl_pct'] > 0 else "#FF4B4B"
            
            with st.expander(f"View Deep Dive for {selected_stock}", expanded=True):
                st.markdown(f"""
                <div style='background:#141824; padding:20px; border-radius:12px; margin-bottom:10px; border-left:5px solid {prob_color};'>
                    <h3 style='margin:0; color:#E0E6ED;'>{g['symbol']}</h3>
                    <div style='display:flex; flex-wrap:wrap; gap:25px; margin-top:15px;'>
                        <div><div style='font-size:13px; color:#A0ABBA;'>P&L %</div><div style='font-size:22px; font-weight:bold; color:{prob_color};'>{g['pnl_pct']:+.2f}%</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Damage Score</div><div style='font-size:20px; color:#FFC107;'>{g['damage']:.0f}/100</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Target</div><div style='font-size:20px; color:#00FF88;'>Rs.{g['locked_target']:.2f}</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Trailing SL</div><div style='font-size:20px; color:#FF4B4B;'>Rs.{g['stop']:.2f}</div></div>
                        <div><div style='font-size:13px; color:#A0ABBA;'>Days Held</div><div style='font-size:20px; color:#E0E6ED;'>{g['days_held']}</div></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                render_interactive_chart(selected_stock, f"portfolio_{selected_stock}")

    else: st.info(f"No active holdings for {view_owner}.")

    st.markdown("---")
    st.subheader("⚙️ Portfolio Management")
    with st.container(border=True):
        action = st.radio("Select Action", ["➕ Add Holding", "➖ Exit Holding"], horizontal=True)
        
        if action == "➕ Add Holding":
            with st.form("add_form"):
                c1, c2 = st.columns(2)
                a_sym = c1.selectbox("Stock", sorted(df['SYMBOL'].dropna().unique()) if not df.empty else [])
                a_qty = c2.number_input("Quantity", min_value=1, step=1)
                a_price = c1.number_input("Buy Price (Rs.)", min_value=0.0, format="%.2f")
                
                a_own = c2.selectbox("Select Existing Owner", db_owners, index=default_owner_idx)
                a_new = st.text_input("OR Create New Owner (Overrides dropdown):")
                
                if st.form_submit_button("Add to Database"):
                    f_own = a_new.strip() if a_new.strip() else a_own
                    if total_risk > (acc_size * 0.03): st.error("🚨 **PORTFOLIO STRESS LIMIT REACHED.** Your total portfolio stop-loss risk currently exceeds 3% of your account size. Do not add new positions.")
                    elif f_own and a_sym:
                        supabase.table('portfolio').insert({"symbol": a_sym, "entry_price": a_price, "qty": a_qty, "date": str(datetime.date.today()), "owner": f_own}).execute()
                        st.success(f"Holding Added to {f_own}!"); load_table.clear(); safe_rerun()

        elif action == "➖ Exit Holding":
            with st.form("exit_form"):
                st.info(f"💡 You are clearing stocks from **{view_owner}'s** portfolio.")
                if not active_port.empty:
                    s_sym = st.selectbox("Stock to Exit", active_port['symbol'].unique())
                    holding = active_port[active_port['symbol'] == s_sym].iloc[0] if s_sym else None
                    c1, c2, c3 = st.columns([1, 1, 1.5])
                    
                    s_qty = c1.number_input(f"Qty (Max: {holding['qty'] if holding is not None else 0})", min_value=1, step=1)
                    s_price = c2.number_input("Exit Price (Rs.)", min_value=0.0, format="%.2f")
                    s_rsn = c3.selectbox("Reason", ["Target Hit 🎯", "Stop Loss Hit 🛑", "Manual Exit ✋", "Data Error/Delete 🗑️"])
                    s_tag = st.selectbox("Setup Category (For Journaling)", ["Trend Continuation", "VCP Breakout", "Mean Reversion", "News/Earnings Event", "Mistake / FOMO", "Other"])
                    
                    if st.form_submit_button("Execute Sale") and holding is not None:
                        if s_qty <= holding['qty']:
                            holding_id = int(holding.get('id', 0))
                            
                            if "Delete" not in s_rsn:
                                full_reason = f"{s_rsn} | Setup: {s_tag}"
                                supabase.table('trade_history').insert({
                                    "symbol": s_sym, "sell_price": float(s_price), "qty_sold": int(s_qty),
                                    "buy_price": float(holding['entry_price']), "realized_pl": float((s_price - float(holding['entry_price'])) * s_qty),
                                    "pl_percentage": float(((s_price - float(holding['entry_price']))/float(holding['entry_price']))*100),
                                    "sell_date": str(datetime.date.today()), "exit_reason": full_reason, "owner": holding['owner']
                                }).execute()
                                
                            n_qty = int(holding['qty']) - int(s_qty)
                            if n_qty <= 0: supabase.table('portfolio').delete().eq('id', holding_id).execute()
                            else: supabase.table('portfolio').update({"qty": n_qty}).eq('id', holding_id).execute()
                            
                            st.success("Sale Executed & Journaled!"); load_table.clear(); safe_rerun()
                        else: st.error("Cannot sell more than held.")
                else: st.info("No stocks to sell.")

with tabs[2]:
    st.subheader("📋 Advanced Screener")
    with st.expander("📚 Knowledge Bytes: How to Screen"):
        st.markdown("* **Strict Score & Prob:** Use the 'High Conviction' toggle to enforce Score >= 90, Prob >= 60%, and Upside > 8%.\n* **Relative Strength:** Prioritize stocks showing 'Outperforming'. They move up even when Nifty drops.\n* **Avoid Weakness:** Never buy a stock if the Weekly Trend is 'Bearish', even if the daily chart looks good.")
        
    c1, c2, c3 = st.columns([2, 1, 1])
    search_sym = c1.multiselect("🔍 Search Stocks (Leave blank for all)", sorted(df['SYMBOL'].dropna().unique()) if not df.empty else [])
    show_top = c2.toggle("🔥 High Conviction Only") 
    req_rs = c3.checkbox("👑 Only Nifty Outperformers")
    
    if not df.empty:
        scr_df = df.copy()
        if search_sym: scr_df = scr_df[scr_df['SYMBOL'].isin(search_sym)]
        if show_top: scr_df = scr_df[(scr_df['SCORE'] >= 90) & (scr_df['PROBABILITY'] >= 60) & (scr_df['UPSIDE_PCT'] > 8.0)]
        if req_rs: scr_df = scr_df[scr_df['RELATIVE_STRENGTH'] == 'Outperforming']

        scr_df['PROBABILITY'] = scr_df['PROBABILITY'].apply(format_prob_icon)
        scr_df['SCORE'] = scr_df['SCORE'].apply(format_score_icon)

        st.dataframe(scr_df[['CLEAN_VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'SECTOR', 'EST_PERIOD', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'RELATIVE_STRENGTH', 'TURNOVER_CR']].sort_values(['SCORE', 'PROBABILITY', 'UPSIDE_PCT'], ascending=[False, False, False]).rename(columns={'CLEAN_VERDICT': 'Verdict', 'EST_PERIOD': 'Expected Time'}).style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%', 'TURNOVER_CR': '{:.1f} Cr'}), use_container_width=True, hide_index=True)

        st.markdown("---")
        if not sector_breadth_df.empty:
            st.subheader("🌍 Sector Heatmap (Live)")
            fig = px.treemap(sector_breadth_df, path=[px.Constant("Indian Market"), 'SECTOR'], values='TOTAL_STOCKS', color='BREADTH_PCT', color_continuous_scale=['#FF4B4B', '#0B0E14', '#00FF88'], color_continuous_midpoint=50, custom_data=['BREADTH_PCT', 'AVG_SCORE', 'BULLISH_STOCKS', 'TOTAL_STOCKS'])
            fig.update_traces(hovertemplate="<b>%{label}</b><br>Breadth: %{customdata[0]:.0f}%<br>Bullish: %{customdata[2]}/%{customdata[3]}<br>Avg Score: %{customdata[1]:.0f}")
            fig.update_layout(margin=dict(t=10,l=0,r=0,b=0), height=400, template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)
    else: st.error("No data available. Run master scan.")

with tabs[3]:
    st.subheader("⚡ Volume Profile Breakouts")
    st.caption("Stocks hovering just beneath their heaviest Volume Resistance Node. High probability of explosive moves.")
    if not df.empty:
        brk = df[(df['SCORE'] >= 50) & (df['PRICE'] < df['RESISTANCE']) & (df['TURNOVER_CR'] > 5.0)].copy()
        brk['DIST'] = ((brk['RESISTANCE'] - brk['PRICE']) / brk['PRICE']) * 100
        brk = brk[(brk['DIST'] >= 0.5) & (brk['DIST'] <= 3.5)].sort_values(['SCORE', 'PROBABILITY'], ascending=[False, False])
        
        for _, b in brk.head(5).iterrows():
            col_info, col_chart = st.columns([1, 1.5])
            with col_info:
                prob_color = "#00FF88" if b['PROBABILITY'] >= 75 else "#FFC107" if b['PROBABILITY'] >= 60 else "#FF4B4B"
                st.markdown(f"""
                <div style='background:#141824; padding:20px; border-radius:12px; border-left:5px solid #00B8FF; margin-bottom:10px;'>
                    <h3 style='margin:0; color:#E0E6ED;'>{b['SYMBOL']}</h3>
                    <div style='color:#00B8FF; font-weight:800; margin-top:5px; font-size:18px;'>Proximity: {b['DIST']:.1f}%</div>
                    <div style='margin-top:12px; color:#A0ABBA;'><b>Score:</b> {b['SCORE']:.0f}/100</div>
                    <div style='color:#A0ABBA;'><b>Win Prob:</b> <span style='color:{prob_color}'>{b['PROBABILITY']:.0f}%</span></div>
                    <div style='color:#A0ABBA;'><b>Target:</b> Rs.{b['TARGET']:.2f} (+{b['UPSIDE_PCT']:.0f}%)</div>
                    <div style='color:#A0ABBA;'><b>Est. Time:</b> {b['EST_PERIOD']}</div>
                </div>
                """, unsafe_allow_html=True)
            with col_chart:
                with st.expander(f"View Chart: {b['SYMBOL']}"): render_interactive_chart(b['SYMBOL'], f"brk_{b['SYMBOL']}")
    else: st.error("No data available.")

with tabs[4]:
    st.subheader("🎰 High-Risk Sandbox (< ₹100)")
    if not df.empty:
        st.warning("⚠️ High Volatility. Strict Stop Losses Mandatory. Pay attention to the Turnover (Liquidity) column to avoid slippage.")
        
        c1, c2 = st.columns([2, 1])
        penny_search = c1.multiselect("🔍 Search Penny Stocks", sorted(df[df['PRICE'] < 100]['SYMBOL'].dropna().unique()))
        penny_top = c2.toggle("🔥 High Conviction Only (Penny)")

        penny = df[df['PRICE'] < 100].copy()
        if penny_search: penny = penny[penny['SYMBOL'].isin(penny_search)]
        if penny_top: penny = penny[(penny['SCORE'] >= 85) & (penny['PROBABILITY'] >= 70) & (penny['UPSIDE_PCT'] > 8.0)]

        penny['PROBABILITY'] = penny['PROBABILITY'].apply(format_prob_icon)
        penny['SCORE'] = penny['SCORE'].apply(format_score_icon)
        
        st.dataframe(penny[['CLEAN_VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'EST_PERIOD', 'TURNOVER_CR']].sort_values(['SCORE', 'PROBABILITY', 'UPSIDE_PCT'], ascending=[False, False, False]).rename(columns={'CLEAN_VERDICT': 'Verdict', 'EST_PERIOD': 'Expected Time'}).style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%', 'TURNOVER_CR': '{:.2f} Cr'}), use_container_width=True, hide_index=True)
    else: st.error("No data available.")

with tabs[5]:
    st.subheader("🏆 Trade History & Analytics")
    col_h1, col_h2 = st.columns([1, 1])
    h_owner = col_h1.selectbox("Select Account History", db_owners, key='hist_owner', index=default_owner_idx)
    time_filter = col_h2.selectbox("Period", ["All Time", "This Month", "Financial Year"])

    h_data = hist_df[hist_df['owner'] == h_owner] if not hist_df.empty else pd.DataFrame()
    
    if not h_data.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Realized P&L", f"Rs.{h_data['realized_pl'].sum():,.2f}")
        c2.metric("🏆 Win Rate", f"{(len(h_data[h_data['realized_pl'] > 0]) / len(h_data) * 100):.1f}%")
        c3.metric("🎯 Best Trade", f"{h_data.loc[h_data['realized_pl'].idxmax()]['symbol']} (Rs.{h_data['realized_pl'].max():.0f})")

        def style_pl(val): return f"color: {'#00FF88' if val > 0 else '#FF4B4B'}; font-weight: bold;"
        
        st.dataframe(h_data[['symbol', 'buy_price', 'sell_price', 'pl_percentage', 'realized_pl', 'exit_reason', 'sell_date']].sort_values('sell_date', ascending=False).style.format({"sell_price": "Rs.{:.2f}", "buy_price": "Rs.{:.2f}", "realized_pl": "Rs.{:.2f}", "pl_percentage": "{:.1f}%"}).map(style_pl, subset=['realized_pl', 'pl_percentage']), use_container_width=True, hide_index=True)
    else: st.info("No trade history logged.")

with tabs[6]:
    st.subheader("📚 Trading Knowledge Hub")
    st.caption("Understand every metric and signal in the V2.1 app")

    topic = st.selectbox("Select Topic:", ["Confluence Score", "Win Probability", "Exit Damage Score", "RVOL (Volume)", "Risk:Reward Ratio", "Chart Patterns", "Market Regime"])
    topic_map = {"Confluence Score": "score", "Win Probability": "probability", "Exit Damage Score": "damage", "RVOL (Volume)": "rvol", "Risk:Reward Ratio": "rr", "Chart Patterns": "pattern", "Market Regime": "regime"}

    if topic in topic_map:
        st.markdown(f"<div style='background:#141824; padding:20px; border-radius:12px; border:1px solid #2A3143;'>", unsafe_allow_html=True)
        st.markdown(KNOWLEDGE[topic_map[topic]], unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    col_rule1, col_rule2 = st.columns(2)
    with col_rule1:
        st.subheader("🎓 Trading Rules for Your Strategy")
        st.markdown("#### 📋 Your Strategy Parameters\n**Capital per Trade:** Rs.10,000\n**Max Trades/Day:** 5\n**Target Hold:** 5-10 days\n**Minimum Target:** 10% profit\n**Stop Loss:** 1.8 x ATR (typically 6-8%)\n**Entry Filter:** Probability >= 60%, Score >= 80\n\n**🟢 BUY Rules:**\n1. Only enter if Win Probability >= 60% and Score >= 80\n2. Ensure Upside > 8%\n3. Check market regime is Bull or Strong Bull\n4. Verify no earnings in next 7 days\n5. Max 5 positions per day\n\n**🔴 SELL Rules:**\n1. If Damage Score >= 80 -> EXIT IMMEDIATE\n2. If Damage Score 56-80 -> SCALE OUT 50%\n3. If target hit -> Sell 50%, trail rest with breakeven stop\n4. If held >14 days with <2% profit -> Consider exit\n5. If gap down >10% -> Emergency exit", unsafe_allow_html=True)

    with col_rule2:
        st.subheader("🤖 How to Use Titan Agent")
        st.markdown("#### 💬 Chat Commands\n**Type natural language:**\n• \"Bought 50 RELIANCE at 2450\" -> Auto-detects and suggests adding to portfolio\n• \"How is my portfolio?\" -> Shows summary\n• \"Top picks today?\" -> Shows best opportunities\n• \"How is the market?\" -> Shows regime status\n\n#### 📷 Upload Screenshots\n• Take screenshot of your broker order (Zerodha/Groww/Upstox)\n• Upload to the sidebar agent\n• Titan Agent reads it via OCR\n• Confirm to auto-add to portfolio", unsafe_allow_html=True)
