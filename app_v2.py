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

if not hasattr(pd.Series, "append"):
    pd.Series.append = pd.Series._append

def safe_rerun():
    try: st.rerun()
    except:
        try: st.experimental_rerun()
        except: pass

# Set timezone explicitly to IST to fix Cloud Server UTC bugs
IST = pytz.timezone('Asia/Kolkata')
def get_ist_now(): return datetime.datetime.now(IST)

st.set_page_config(page_title="Titan Quantum Pro V2.1", layout="wide", page_icon="💎")

# ===================== CSS STYLING =====================
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
        background-color: #141824; border: 1px solid #2A3143; border-radius: 12px; 
        padding: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    .gradient-text {
        background: -webkit-linear-gradient(45deg, #00B8FF, #00FF88);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 800; margin-bottom: 0;
    }
</style>
""", unsafe_allow_html=True)

# ===================== INIT =====================
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()
engine = ProbabilityEngine()

# ===================== DATA LOADERS (SUPERFAST) =====================
@st.cache_data(ttl=120)
def load_market_data():
    """Reads the pre-calculated V2.1 data from Supabase."""
    all_data, limit, offset = [], 1000, 0
    while True:
        res = supabase.table('market_scans').select("*").range(offset, offset + limit - 1).execute()
        if not res.data: break
        all_data.extend(res.data)
        if len(res.data) < limit: break
        offset += limit
    df = pd.DataFrame(all_data)
    if df.empty: return df
    num_cols = ['PRICE', 'SCORE', 'PROBABILITY', 'TARGET', 'STOP_LOSS', 'RR_RATIO', 'UPSIDE_PCT', 'TURNOVER_CR', 'RVOL']
    for col in num_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=300)
def load_table(table_name):
    try: return pd.DataFrame(supabase.table(table_name).select("*").execute().data)
    except: return pd.DataFrame()

# ===================== HELPERS & ICONS =====================
def get_index_data(ticker_symbol):
    try:
        idx = yfinance.Ticker(ticker_symbol)
        hist = idx.history(period="5d")
        if len(hist) >= 2: return hist['Close'].iloc[-1], ((hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
    except: return None, None
    return None, None

@st.cache_data(ttl=300)
def fetch_chart_data(symbol):
    try: return yf.download(f"{symbol}.NS", period="3mo", progress=False)
    except: return pd.DataFrame()

def render_interactive_chart(symbol, unique_key_suffix=""):
    try:
        data = fetch_chart_data(symbol).copy() 
        if data.empty: return st.error(f"Chart data unavailable for {symbol}.")
        if isinstance(data.columns, pd.MultiIndex): data.columns = [col[0] for col in data.columns]
        data.index = pd.to_datetime(data.index).tz_localize(None)

        data['EMA20'] = data['Close'].ewm(span=20, adjust=False).mean()
        data['EMA50'] = data['Close'].ewm(span=50, adjust=False).mean()

        fig = go.Figure(data=[go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name='Price')])
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA20'], line=dict(color='#00B8FF', width=1.5), name='20 EMA'))
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA50'], line=dict(color='#FFC107', width=1.5), name='50 EMA'))
        fig.update_layout(title=dict(text=f"{symbol} - Live Technicals", font=dict(color='#E0E6ED')),
                          template='plotly_dark', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                          height=400, margin=dict(l=0, r=0, t=40, b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{symbol}_{unique_key_suffix}")
    except: pass

@st.cache_data(ttl=300)
def get_macro_weather():
    now_ist = get_ist_now()
    try:
        if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
            gift, gift_pct = get_index_data("GIFNIF.NS")
            sp500, sp_pct = get_index_data("^GSPC")
            direction = gift_pct if gift_pct is not None else sp_pct if sp_pct is not None else 0
            if direction > 0.4: return "🟢 GLOBAL CUES: POSITIVE", "Expect a Gap-Up opening.", "green"
            elif direction < -0.4: return "🔴 GLOBAL CUES: NEGATIVE", "Expect a weak opening. Caution.", "red"
            else: return "🟡 GLOBAL CUES: FLAT/MIXED", "Expect a flat opening.", "yellow"
        else:
            nifty_val, nifty_pct = get_index_data("^NSEI")
            nifty_hist = yf.download("^NSEI", period="3mo", progress=False, ignore_tz=True)
            if nifty_hist.empty: return "🟡 UNKNOWN", "Data delayed", "yellow"
            close_series = nifty_hist['Close']["^NSEI"] if isinstance(nifty_hist.columns, pd.MultiIndex) else nifty_hist['Close']
            close = float(close_series.iloc[-1])
            ema20 = close_series.ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = close_series.ewm(span=50, adjust=False).mean().iloc[-1]
            idx_str = f"NIFTY: {nifty_val:.2f} ({nifty_pct:+.2f}%)"
            if close > ema20: return "🟢 RISK ON (BULLISH)", f"{idx_str} | Uptrend above 20 EMA.", "green"
            elif close > ema50: return "🟡 CAUTION (SIDEWAYS)", f"{idx_str} | Below 20 EMA but holding 50 EMA.", "yellow"
            else: return "🔴 RISK OFF (BEARISH)", f"{idx_str} | Active downtrend. CASH IS KING.", "red"
    except: return "🟡 UNKNOWN", "Macro weather unavailable.", "yellow"

def format_score_icon(val):
    if val >= 75: return f"🟢 {val:.0f}"
    elif val >= 60: return f"🟡 {val:.0f}"
    else: return f"🔴 {val:.0f}"

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

# ===================== LOAD DATA =====================
df = load_market_data()
sector_breadth_df = load_table('sector_breadth')
port_df = load_table('portfolio')
hist_df = load_table('trade_history')

# Standardize Owners Safely
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

# ===================== SIDEBAR =====================
with st.sidebar:
    st.markdown("<h3 class='gradient-text'>💎 Titan Quantum Pro</h3>", unsafe_allow_html=True)
    st.caption(f"IST Sync: {get_ist_now().strftime('%d %b %H:%M')}")
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        safe_rerun()

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
            st.markdown(f"<div style='background:#141824; padding:15px; border-radius:10px;'>{response}</div>", unsafe_allow_html=True)
            if res and res.get('action') == 'BUY': st.session_state['agent_result'] = res

    if 'agent_result' in st.session_state and st.session_state['agent_result'].get('action') == 'BUY':
        res = st.session_state['agent_result']
        st.success(f"Detected: BUY {res['qty']} {res['symbol']} @ ₹{res['price']}")
        sel_owner = st.selectbox("Assign Owner", db_owners + ["+ Add New"])
        final_owner = st.text_input("New Name:") if sel_owner == "+ Add New" else sel_owner
        
        if st.button("✅ Confirm & Log", use_container_width=True):
            if final_owner:
                supabase.table('portfolio').insert({
                    "symbol": res['symbol'], "entry_price": res['price'], "qty": res['qty'],
                    "date": str(datetime.date.today()), "owner": final_owner
                }).execute()
                st.success("Logged!")
                del st.session_state['agent_result']
                st.cache_data.clear()
                safe_rerun()

# ===================== HEADER =====================
st.markdown("<div style='text-align:center;'><h1 class='gradient-text' style='font-size: 3rem;'>Titan Quantum Pro V2.1</h1></div>", unsafe_allow_html=True)

# MACRO WEATHER
status, msg, css_class = get_macro_weather()
border_color = "#00FF88" if "green" in css_class else "#FF4B4B" if "red" in css_class else "#FFC107"
bg_color = "rgba(0, 255, 136, 0.05)" if "green" in css_class else "rgba(255, 75, 75, 0.05)" if "red" in css_class else "rgba(255, 193, 7, 0.05)"
st.markdown(f"""
<div style='border-left: 5px solid {border_color}; padding: 20px; background-color: {bg_color}; border-radius: 10px; margin-bottom: 25px;'>
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

# --- TAB 0: TOP PICKS ---
with tabs[0]:
    if not df.empty:
        inst_df = df[df['TURNOVER_CR'] >= 5.0].copy() # Ensure liquidity
        actionable = inst_df[(inst_df['PROBABILITY'] >= 60) & (inst_df['SCORE'] >= 60) & (~inst_df['VERDICT'].str.contains('AVOID', na=False))].copy()
        
        if not actionable.empty:
            actionable['Est_Qty'] = (10000 / actionable['PRICE']).astype(int)
            actionable = actionable.sort_values(['PROBABILITY', 'SCORE', 'UPSIDE_PCT'], ascending=[False, False, False]).head(10)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📊 Avg Probability", f"{actionable['PROBABILITY'].mean():.0f}%")
            c2.metric("⭐ Avg Score", f"{actionable['SCORE'].mean():.0f}")
            c3.metric("⚖️ Avg R:R", f"1:{actionable['RR_RATIO'].mean():.1f}")
            c4.metric("🔥 Top Picks (Liquid)", f"{len(actionable)}")

            # Display Dataframe with clean icons
            display_df = actionable[['SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'PROBABILITY', 'SCORE', 'RR_RATIO', 'STOP_LOSS', 'RELATIVE_STRENGTH', 'EARNINGS_RISK']].copy()
            display_df['PROBABILITY'] = display_df['PROBABILITY'].apply(format_prob_icon)
            display_df['SCORE'] = display_df['SCORE'].apply(format_score_icon)
            display_df['RELATIVE_STRENGTH'] = display_df['RELATIVE_STRENGTH'].apply(lambda x: "🔥 Outperforming" if "Outperform" in x else "Neutral")
            display_df['EARNINGS_RISK'] = display_df['EARNINGS_RISK'].apply(lambda x: "⚠️ YES" if x == "YES" else "No")
            
            st.dataframe(
                display_df.style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%', 'RR_RATIO': '1:{:.1f}', 'STOP_LOSS': 'Rs.{:.2f}'}),
                use_container_width=True, hide_index=True
            )

            st.markdown("---")
            st.subheader("💎 Detailed Analysis (Top Picks)")
            
            for idx, (_, g) in enumerate(actionable.head(5).iterrows()):
                rs_badge = "<span style='background:#00FF88; color:#000; padding:2px 8px; border-radius:4px; font-size:12px;'>Market Leader</span>" if "Outperform" in g['RELATIVE_STRENGTH'] else ""
                prob_color = "#00FF88" if g['PROBABILITY'] >= 75 else "#FFC107" if g['PROBABILITY'] >= 60 else "#FF4B4B"

                st.markdown(f"""
                <div style='background:#141824; padding:20px; border-radius:12px; margin-bottom:10px; border-left:5px solid {prob_color};'>
                    <h3 style='margin:0; color:#E0E6ED;'>{g['SYMBOL']} {rs_badge}</h3>
                    <div style='display:flex; flex-wrap:wrap; gap:25px; margin-top:10px;'>
                        <div><div style='font-size:12px; color:#A0ABBA;'>Prob</div><div style='font-size:18px; color:{prob_color};'>{g['PROBABILITY']:.0f}%</div></div>
                        <div><div style='font-size:12px; color:#A0ABBA;'>CMP</div><div style='font-size:18px; color:#E0E6ED;'>Rs.{g['PRICE']:.2f}</div></div>
                        <div><div style='font-size:12px; color:#A0ABBA;'>Target (Vol Profile)</div><div style='font-size:18px; color:#00FF88;'>Rs.{g['TARGET']:.2f} (+{g['UPSIDE_PCT']:.0f}%)</div></div>
                        <div><div style='font-size:12px; color:#A0ABBA;'>Stop Loss</div><div style='font-size:18px; color:#FF4B4B;'>Rs.{g['STOP_LOSS']:.2f}</div></div>
                        <div><div style='font-size:12px; color:#A0ABBA;'>Hold</div><div style='font-size:18px; color:#E0E6ED;'>{g['EST_PERIOD']}</div></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                with st.expander(f"📊 Chart & Action ({g['SYMBOL']})"):
                    render_interactive_chart(g['SYMBOL'], f"top_{idx}")
                    col1, col2 = st.columns([1, 2])
                    with col1:
                        st.info(f"💡 Suggestion: **{g['Est_Qty']}** shares (₹10k)")
                    with col2:
                        sel = st.selectbox("Assign Owner", db_owners + ["+ Add New"], key=f"sel_{idx}")
                        f_own = st.text_input("New Name:", key=f"fown_{idx}") if sel == "+ Add New" else sel
                        if st.button(f"➕ Quick Add", key=f"add_{idx}"):
                            if f_own:
                                supabase.table('portfolio').insert({"symbol": g['SYMBOL'], "entry_price": g['PRICE'], "qty": int(g['Est_Qty']), "date": str(datetime.date.today()), "owner": f_own}).execute()
                                st.success("Added!")
                                st.cache_data.clear()
        else: st.info("🟡 No safe setups matching your strategy criteria. Cash is a position.")
    else: st.error("No data available.")

# --- TAB 1: PORTFOLIO INTELLIGENCE ---
with tabs[1]:
    view_owner = st.selectbox("👤 Select Portfolio", db_owners)
    active_port = port_df[port_df['owner'] == view_owner] if not port_df.empty else pd.DataFrame()

    if not active_port.empty:
        # Optimized Bulk History Fetch
        @st.cache_data(ttl=300)
        def fetch_bulk_history(symbols):
            try: return yf.download([f"{s}.NS" for s in symbols], period="3mo", group_by="ticker", progress=False, ignore_tz=True)
            except: return pd.DataFrame()

        bulk_hist = fetch_bulk_history(active_port['symbol'].unique().tolist())
        port_calc, total_dmg = [], 0

        for _, row in active_port.iterrows():
            sym = row['symbol']
            live = df[df['SYMBOL'] == sym].iloc[0] if not df.empty and sym in df['SYMBOL'].values else None
            cmp = float(live['PRICE']) if live is not None else float(row['entry_price'])
            entry, qty = float(row['entry_price']), int(row['qty'])
            
            try:
                hist_data = bulk_hist[f"{sym}.NS"].copy() if len(active_port['symbol'].unique()) > 1 else bulk_hist.copy()
                hist_data.dropna(inplace=True)
            except: hist_data = pd.DataFrame()

            dmg, verdict, stop, reason = engine.calculate_exit_damage(sym, entry, row.get('date', datetime.date.today()), hist_data, live)
            total_dmg += dmg
            
            pnl_pct = ((cmp - entry) / entry) * 100
            val = cmp * qty
            
            # Stop Loss Proximity Warning
            sl_proximity = ""
            if cmp <= stop: sl_proximity = "🔴 HIT"
            elif cmp <= stop * 1.02: sl_proximity = "⚠️ NEAR"

            port_calc.append({
                "symbol": sym, "qty": qty, "entry": entry, "cmp": cmp, "pnl_pct": pnl_pct, "profit": qty * (cmp - entry),
                "invested": entry * qty, "val": val, "stop": stop, "proximity": sl_proximity, "damage": dmg, "verdict": get_exit_badge(verdict)
            })

        pdf = pd.DataFrame(port_calc)
        t_inv, t_cur = pdf['invested'].sum(), pdf['val'].sum()
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Invested", f"Rs.{t_inv:,.2f}")
        c2.metric("📈 Current Value", f"Rs.{t_cur:,.2f}", f"Rs.{t_cur - t_inv:,.2f}")
        c3.metric("🎯 Net P&L %", f"{(t_cur - t_inv) / t_inv * 100:.2f}%" if t_inv > 0 else "0%")
        c4.metric("⚠️ Avg Damage", f"{total_dmg / len(pdf):.0f}/100", delta_color="inverse")

        st.markdown("##### 📊 Active Holdings")
        
        def color_pnl(val): return f"color: {'#00FF88' if val > 0 else '#FF4B4B' if val < 0 else 'white'};"
        
        st.dataframe(
            pdf[['verdict', 'damage', 'symbol', 'qty', 'entry', 'cmp', 'pnl_pct', 'profit', 'stop', 'proximity']].style
            .format({"entry": "Rs.{:.2f}", "cmp": "Rs.{:.2f}", "pnl_pct": "{:.2f}%", "profit": "Rs.{:.2f}", "stop": "Rs.{:.2f}", "damage": "{:.0f}"})
            .map(color_pnl, subset=['pnl_pct', 'profit']),
            use_container_width=True, hide_index=True
        )
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
                a_own = c2.selectbox("Owner", db_owners + ["+ Add New"])
                a_new = st.text_input("New Name (if applicable):")
                
                if st.form_submit_button("Add to Database"):
                    f_own = a_new if a_own == "+ Add New" else a_own
                    if f_own and a_sym:
                        supabase.table('portfolio').insert({"symbol": a_sym, "entry_price": a_price, "qty": a_qty, "date": str(datetime.date.today()), "owner": f_own}).execute()
                        st.success("Holding Added!")
                        st.cache_data.clear()
                        safe_rerun()

        elif action == "➖ Exit Holding":
            with st.form("exit_form"):
                if not active_port.empty:
                    s_sym = st.selectbox("Stock to Exit", active_port['symbol'].unique())
                    holding = active_port[active_port['symbol'] == s_sym].iloc[0] if s_sym else None
                    c1, c2 = st.columns(2)
                    s_qty = c1.number_input(f"Qty (Max: {holding['qty'] if holding is not None else 0})", min_value=1, step=1)
                    s_price = c2.number_input("Exit Price (Rs.)", min_value=0.0, format="%.2f")
                    s_rsn = st.selectbox("Reason", ["Target Hit 🎯", "Stop Loss Hit 🛑", "Manual Exit ✋", "Data Error/Delete 🗑️"])
                    
                    if st.form_submit_button("Execute Sale") and holding is not None:
                        if s_qty <= holding['qty']:
                            if "Delete" not in s_rsn:
                                supabase.table('trade_history').insert({
                                    "symbol": s_sym, "sell_price": float(s_price), "qty_sold": int(s_qty),
                                    "buy_price": float(holding['entry_price']), "realized_pl": float((s_price - float(holding['entry_price'])) * s_qty),
                                    "pl_percentage": float(((s_price - float(holding['entry_price']))/float(holding['entry_price']))*100),
                                    "sell_date": str(datetime.date.today()), "exit_reason": s_rsn, "owner": holding['owner']
                                }).execute()
                            n_qty = holding['qty'] - s_qty
                            if n_qty <= 0: supabase.table('portfolio').delete().eq('id', holding['id']).execute()
                            else: supabase.table('portfolio').update({"qty": n_qty}).eq('id', holding['id']).execute()
                            st.success("Sale Executed!")
                            st.cache_data.clear()
                            safe_rerun()
                        else: st.error("Cannot sell more than held.")
                else: st.info("No stocks to sell.")

# --- TAB 2: MARKET SCREENER ---
with tabs[2]:
    if not df.empty and not sector_breadth_df.empty:
        st.subheader("🌍 Sector Heatmap (Live)")
        fig = px.treemap(sector_breadth_df, path=[px.Constant("Indian Market"), 'SECTOR'], values='TOTAL_STOCKS', color='BREADTH_PCT',
                         color_continuous_scale=['#FF4B4B', '#0B0E14', '#00FF88'], color_continuous_midpoint=50)
        fig.update_layout(margin=dict(t=10,l=0,r=0,b=0), height=400, template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 Advanced Screener")
        c1, c2, c3, c4 = st.columns(4)
        min_s = c1.slider("Min Score", 0, 100, 50)
        min_p = c2.slider("Min Prob %", 0, 100, 50)
        req_rs = c3.checkbox("🔥 Only Nifty Outperformers")
        req_wt = c4.checkbox("🛡️ No Weekly Downtrends", value=True)

        scr_df = df[(df['SCORE'] >= min_s) & (df['PROBABILITY'] >= min_p)].copy()
        if req_rs: scr_df = scr_df[scr_df['RELATIVE_STRENGTH'] == 'Outperforming']
        if req_wt: scr_df = scr_df[scr_df['WEEKLY_TREND'] != 'Bearish']

        scr_df['PROBABILITY'] = scr_df['PROBABILITY'].apply(format_prob_icon)
        scr_df['SCORE'] = scr_df['SCORE'].apply(format_score_icon)

        st.dataframe(
            scr_df[['VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'SECTOR', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'RELATIVE_STRENGTH', 'TURNOVER_CR']]
            .sort_values('UPSIDE_PCT', ascending=False)
            .style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%', 'TURNOVER_CR': '{:.1f} Cr'}),
            use_container_width=True, hide_index=True
        )

# --- TAB 3: BREAKOUT RADAR ---
with tabs[3]:
    st.subheader("⚡ Volume Profile Breakouts")
    st.caption("Stocks hovering just beneath their heaviest Volume Resistance Node.")
    if not df.empty:
        brk = df[(df['SCORE'] >= 50) & (df['PRICE'] < df['RESISTANCE']) & (df['TURNOVER_CR'] > 5.0)].copy()
        brk['DIST'] = ((brk['RESISTANCE'] - brk['PRICE']) / brk['PRICE']) * 100
        brk = brk[(brk['DIST'] >= 0.5) & (brk['DIST'] <= 3.5)].sort_values('DIST')
        
        for _, b in brk.head(5).iterrows():
            st.markdown(f"""
            <div style='background:#141824; padding:15px; border-radius:10px; border-left:4px solid #00B8FF; margin-bottom:10px;'>
                <h4 style='margin:0;'>{b['SYMBOL']} (Proximity: {b['DIST']:.1f}%)</h4>
                <p style='margin:5px 0 0 0; font-size:14px; color:#A0ABBA;'>CMP: Rs.{b['PRICE']:.2f} | Heavy Resistance Node: Rs.{b['RESISTANCE']:.2f}</p>
            </div>
            """, unsafe_allow_html=True)
            with st.expander("Chart"): render_interactive_chart(b['SYMBOL'], f"brk_{b['SYMBOL']}")

# --- TAB 4: PENNY SANDBOX ---
with tabs[4]:
    st.subheader("🎰 High-Risk Sandbox (< ₹100)")
    if not df.empty:
        penny = df[df['PRICE'] < 100].copy()
        st.warning("⚠️ High Volatility. Strict Stop Losses Mandatory. Pay attention to the Turnover (Liquidity) column.")
        
        penny['PROBABILITY'] = penny['PROBABILITY'].apply(format_prob_icon)
        penny['SCORE'] = penny['SCORE'].apply(format_score_icon)
        st.dataframe(
            penny[['VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_PCT', 'TURNOVER_CR']]
            .sort_values('UPSIDE_PCT', ascending=False)
            .style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_PCT': '{:.0f}%', 'TURNOVER_CR': '{:.2f} Cr'}),
            use_container_width=True, hide_index=True
        )

# --- TAB 5: HISTORY ---
with tabs[5]:
    h_owner = st.selectbox("👤 Select Ledger", db_owners, key='hist_owner')
    h_data = hist_df[hist_df['owner'] == h_owner] if not hist_df.empty else pd.DataFrame()
    
    if not h_data.empty:
        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Total Realized P&L", f"Rs.{h_data['realized_pl'].sum():,.2f}")
        c2.metric("🏆 Win Rate", f"{(len(h_data[h_data['realized_pl'] > 0]) / len(h_data) * 100):.1f}%")
        c3.metric("🎯 Best Trade", f"{h_data.loc[h_data['realized_pl'].idxmax()]['symbol']} ({h_data['realized_pl'].max():.0f})")

        def style_pl(val): return f"color: {'#00FF88' if val > 0 else '#FF4B4B'}; font-weight: bold;"
        
        st.dataframe(
            h_data[['symbol', 'buy_price', 'sell_price', 'pl_percentage', 'realized_pl', 'exit_reason', 'sell_date']].sort_values('sell_date', ascending=False)
            .style.format({"sell_price": "Rs.{:.2f}", "buy_price": "Rs.{:.2f}", "realized_pl": "Rs.{:.2f}", "pl_percentage": "{:.1f}%"})
            .map(style_pl, subset=['realized_pl', 'pl_percentage']),
            use_container_width=True, hide_index=True
        )
    else: st.info("No trade history logged.")

# --- TAB 6: KNOWLEDGE HUB ---
with tabs[6]:
    st.subheader("📚 V2.1 Strategy & Mechanics")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        **1. Volume Profile S&R:** We no longer use wicks. Resistance is the price level where the most volume was traded historically.
        **2. Relative Strength (RS):** Compares the stock's performance to the NIFTY 50. 'Outperforming' means the stock is rising faster or falling slower than the index.
        **3. Weekly Veto:** Even if a daily chart looks amazing, if the stock is below its 50 EMA on the Weekly timeframe, the system applies a massive penalty.
        **4. Liquidity Filter:** We ignore stocks trading under 5 Crores daily turnover to prevent slippage.
        """)
    with c2:
        st.markdown("""
        **🟢 BUY Rules:**
        1. Prob >= 60%, R:R >= 1.5, Market = Bullish
        2. No earnings within 7 days.
        **🔴 SELL Rules:**
        1. Damage >= 80 -> EXIT IMMEDIATE
        2. Damage 50-79 -> SCALE OUT 50%
        3. If CMP drops within 2% of SL, prepare to exit.
        """)
