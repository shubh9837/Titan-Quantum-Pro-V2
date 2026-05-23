import streamlit as st
import pandas as pd
import pandas_ta_classic as ta
import numpy as np
import yfinance as yf
import pytz
import datetime  
import plotly.graph_objects as go
import plotly.express as px
from supabase import create_client
from probability_core import ProbabilityEngine
from titan_agent import parse_trade_text, parse_order_image, get_response

# Pandas 2.0+ compatibility patch for pandas_ta
if not hasattr(pd.Series, "append"):
    pd.Series.append = pd.Series._append

# Streamlit version compatibility
def safe_rerun():
    try:
        st.rerun()
    except:
        try:
            st.experimental_rerun()
        except:
            pass

st.set_page_config(page_title="Titan Quantum Pro V2", layout="wide", page_icon="💎")

# ===================== CSS STYLING (UPGRADED) =====================
st.markdown("""
<style>
    /* Main Background & Text */
    .main { background-color: #0B0E14; color: #E0E6ED; font-family: 'Inter', sans-serif; }
    
    /* Buttons */
    .stButton>button { 
        background: linear-gradient(135deg, #00B8FF 0%, #0073FF 100%);
        color: white; 
        font-weight: 600; 
        border-radius: 8px; 
        border: none;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 184, 255, 0.2);
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 184, 255, 0.4);
    }

    /* Metric Cards */
    div[data-testid="metric-container"] {
        background-color: #141824; 
        border: 1px solid #2A3143;
        border-radius: 12px; 
        padding: 15px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        background-color: #141824;
        border-radius: 8px;
    }

    /* DataFrame styling */
    .stDataFrame { border-radius: 10px; overflow: hidden; }
    
    /* Text Adjustments */
    div[data-testid="stMarkdownContainer"] p { font-size: 15px; line-height: 1.6; }
    
    /* Gradient Header Text */
    .gradient-text {
        background: -webkit-linear-gradient(45deg, #00B8FF, #00FF88);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        margin-bottom: 0;
    }
</style>
""", unsafe_allow_html=True)

# ===================== DATABASE =====================
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()
engine = ProbabilityEngine()

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

    expected_cols = ['SECTOR', 'EARNINGS_RISK', 'CAP_CATEGORY', 'SUPPORT', 'RESISTANCE',
                     'PATTERN', 'RR_RATIO', 'RVOL', 'PROBABILITY', 'REGIME', 'MC_DESCRIPTION',
                     'OPTIMISTIC_TARGET', 'INSTITUTIONAL_TREND']
    for col in expected_cols:
        if col not in df.columns:
            if col in ['RVOL', 'RR_RATIO', 'PROBABILITY']: df[col] = 0.0
            elif col in ['SUPPORT', 'RESISTANCE', 'OPTIMISTIC_TARGET']: df[col] = 0.0
            else: df[col] = "N/A"

    df['PRICE'] = pd.to_numeric(df['PRICE'], errors='coerce').fillna(0)
    df['TARGET'] = pd.to_numeric(df['TARGET'], errors='coerce').fillna(0)
    df['STOP_LOSS'] = pd.to_numeric(df['STOP_LOSS'], errors='coerce').fillna(0)
    df['PROBABILITY'] = pd.to_numeric(df['PROBABILITY'], errors='coerce').fillna(0)
    df['SCORE'] = pd.to_numeric(df['SCORE'], errors='coerce').fillna(0)

    df['UPSIDE_%'] = np.where(df['PRICE'] > 0, ((df['TARGET'] - df['PRICE']) / df['PRICE'] * 100), 0)

    risk = df['PRICE'] - df['STOP_LOSS']
    reward = df['TARGET'] - df['PRICE']
    df['RR_RATIO'] = np.where(risk > 0, reward / risk, 0)
    df['RR_RATIO'] = df['RR_RATIO'].clip(lower=0, upper=10.0)

    df['VERDICT'] = df.apply(lambda x:
        "💎 ALPHA" if x['SCORE'] >= 90 and x['PROBABILITY'] >= 80
        else "🟢 STRONG BUY" if x['SCORE'] >= 75 and x['PROBABILITY'] >= 65
        else "🟢 BUY" if x['SCORE'] >= 65
        else "🟡 WATCH" if x['SCORE'] >= 45
        else "🔴 AVOID", axis=1)

    df['EST_PERIOD'] = df['SCORE'].apply(
        lambda x: "5-7 Days" if x >= 85 else "7-10 Days" if x >= 70 else "10-14 Days" if x >= 55 else "14+ Days")

    return df

@st.cache_data(ttl=300)
def load_sector_breadth():
    try:
        res = supabase.table('sector_breadth').select("*").execute()
        return pd.DataFrame(res.data)
    except:
        return pd.DataFrame()

def load_table(table_name):
    res = supabase.table(table_name).select("*").execute()
    return pd.DataFrame(res.data)

# ===================== HELPERS =====================
def get_index_data(ticker_symbol):
    try:
        idx = yfinance.Ticker(ticker_symbol)
        hist = idx.history(period="5d")
        if len(hist) >= 2:
            close_tdy = hist['Close'].iloc[-1]
            close_yst = hist['Close'].iloc[-2]
            pct_change = ((close_tdy - close_yst) / close_yst) * 100
            return close_tdy, pct_change
        return None, None
    except:
        return None, None

@st.cache_data(ttl=300)
def fetch_chart_data(symbol):
    try:
        return yf.download(f"{symbol}.NS", period="3mo", progress=False)
    except:
        return pd.DataFrame()
# --------------------------------------------------------

def render_interactive_chart(symbol, unique_key_suffix=""):
    try:
        data = fetch_chart_data(symbol).copy() 
        
        if data.empty:
            return st.error(f"Chart data unavailable for {symbol}.")

        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        if data.index.tzinfo is not None:
            data.index = data.index.tz_localize(None)

        data['EMA20'] = data['Close'].ewm(span=20, adjust=False).mean()
        data['EMA50'] = data['Close'].ewm(span=50, adjust=False).mean()
        data['Volume_MA'] = data['Volume'].rolling(20).mean()

        fig = go.Figure(data=[go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'], name='Price',
            increasing_line_color='#00FF88', decreasing_line_color='#FF4B4B'
        )])
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA20'], line=dict(color='#00B8FF', width=1.5), name='20 EMA'))
        fig.add_trace(go.Scatter(x=data.index, y=data['EMA50'], line=dict(color='#FFC107', width=1.5), name='50 EMA'))

        fig.update_layout(
            title=dict(text=f"{symbol} - Live Technicals", font=dict(color='#E0E6ED')),
            template='plotly_dark',
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            height=400,
            margin=dict(l=0, r=0, t=40, b=0),
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True, key=f"chart_{symbol}_{unique_key_suffix}")
    except Exception as e:
        st.error(f"Chart error: {str(e)}")

@st.cache_data(ttl=300)
def get_macro_weather():
    try:
        ist = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.datetime.now(ist)

        # Midnight to 8:59 AM IST: International / Global Cues
        if now_ist.hour < 9:
            gift, gift_pct = get_index_data("GIFNIF.NS")
            sp500, sp_pct = get_index_data("^GSPC")
            nasdaq, nas_pct = get_index_data("^IXIC")

            # Determine dominant global direction
            direction = gift_pct if gift_pct is not None else sp_pct if sp_pct is not None else 0
            
            if direction > 0.4:
                status = "🟢 GLOBAL CUES: POSITIVE"
                css = "green"
                outlook = "Expect a Gap-Up or strong positive opening in Indian markets."
            elif direction < -0.4:
                status = "🔴 GLOBAL CUES: NEGATIVE"
                css = "red"
                outlook = "Expect a Gap-Down or weak opening in Indian markets. Caution advised."
            else:
                status = "🟡 GLOBAL CUES: FLAT/MIXED"
                css = "yellow"
                outlook = "Expect a flat opening. Market will look for domestic cues."

            msg = f"GIFT Nifty: {gift:.2f} ({gift_pct:+.2f}%) | S&P 500: {sp500:.2f} ({sp_pct:+.2f}%) | Nasdaq: {nasdaq:.2f} ({nas_pct:+.2f}%)<br><br><b>Conclusion:</b> {outlook}"
            return status, msg, css

        # 9:00 AM to Midnight IST: Indian Markets
        else:
            nifty_val, nifty_pct = get_index_data("^NSEI")
            sensex_val, sensex_pct = get_index_data("^BSESN")

            nifty_hist = yf.download("^NSEI", period="3mo", progress=False, ignore_tz=True)
            if nifty_hist.empty:
                return "🟡 UNKNOWN", "NIFTY data delayed", "yellow"

            close_series = nifty_hist['Close']["^NSEI"] if isinstance(nifty_hist.columns, pd.MultiIndex) else nifty_hist['Close']
            close = float(close_series.iloc[-1])
            ema20 = close_series.ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = close_series.ewm(span=50, adjust=False).mean().iloc[-1]

            idx_str = f"NIFTY: {nifty_val:.2f} ({nifty_pct:+.2f}%) | SENSEX: {sensex_val:.2f} ({sensex_pct:+.2f}%)"

            if close > ema20:
                return "🟢 RISK OFF (BULLISH)", f"{idx_str}<br><br><b>Conclusion:</b> NIFTY is in an uptrend above the 20 EMA. Safe to deploy capital into high-probability setups.", "green"
            elif close > ema50:
                return "🟡 CAUTION (SIDEWAYS)", f"{idx_str}<br><br><b>Conclusion:</b> NIFTY slipped below the 20 EMA but is holding the 50 EMA. Cut new position sizes by 50%.", "yellow"
            else:
                return "🔴 RISK ON (BEARISH)", f"{idx_str}<br><br><b>Conclusion:</b> NIFTY is below the 50 EMA indicating active downtrend. CASH IS KING. Avoid taking new long positions.", "red"
    except Exception as e:
        return "🟡 UNKNOWN", "Macro weather currently unavailable.", "yellow"
        
def style_pnl(val):
    if pd.isna(val) or isinstance(val, str): return ''
    return f"color: {'#00FF88' if val > 0 else '#FF4B4B' if val < 0 else 'white'}; font-weight: bold;"

def get_exit_badge(verdict):
    v = str(verdict).upper()
    if 'EXIT IMMEDIATE' in v: return 'EXIT IMMEDIATE'
    if 'SCALE OUT' in v: return 'SCALE OUT 50%'
    if 'TIGHTEN' in v: return 'TIGHTEN STOP'
    return 'HOLD'

# ===================== KNOWLEDGE ARTICLES =====================
KNOWLEDGE = {
    "score": """
    #### 📊 What is Confluence Score (0-100)?
    The score combines 6 factors: Trend Alignment (25 pts), Momentum Health (20 pts),
    Price Structure (20 pts), Volume Signature (15 pts), Relative Strength (10 pts),
    and Macro Safety (10 pts). Higher = stronger setup.
    """,
    "probability": """
    #### 🎯 What is Win Probability %?
    Bayesian probability calculated from: Base Rate (historical accuracy of similar scores)
    x Market Regime Multiplier x Sector Breadth x Relative Strength Filter.
    A 75% probability means 3 out of 4 similar setups historically succeeded.
    """,
    "damage": """
    #### 💀 What is Damage Score (0-100)?
    Measures how badly a holding is deteriorating: Structural Break (40 pts max),
    Momentum Reversal (30 pts), Volume Signature (20 pts), Time Decay (10 pts).
    **0-30:** Normal pullback, HOLD
    **31-55:** Risk rising, TIGHTEN STOP
    **56-80:** Structure damaged, SCALE OUT 50%
    **81-100:** Trend broken, EXIT IMMEDIATE
    """,
    "rvol": """
    #### 📈 What is RVOL (Relative Volume)?
    Current volume / 20-day average volume. RVOL > 1.5x means unusual activity.
    RVOL > 2.0x often signals institutional accumulation or distribution.
    """,
    "rr": """
    #### ⚖️ What is Risk:Reward Ratio?
    Potential reward / Potential risk. A 1:2 ratio means you risk Rs.1 to make Rs.2.
    We target minimum 1:1.5 for swing trades. Higher is better.
    """,
    "pattern": """
    #### 🕯️ Chart Patterns Explained
    **⚡ VCP Squeeze:** Volatility contracting with volume drying up. Explosive move imminent.
    **🟢 Bullish Engulfing:** Today's candle completely covers yesterday's red candle. Reversal signal.
    **Consolidating:** Price moving sideways. Wait for breakout above resistance.
    **Uptrending:** Higher highs and higher lows. Buy dips to EMA.
    """,
    "regime": """
    #### 🌍 Market Regime Guide
    **Strong Bull:** All EMAs aligned up. Deploy full capital.
    **Bull:** Price above 50 EMA. Normal trading.
    **Sideways:** No clear trend. Reduce position sizes.
    **Bear:** Below 50 EMA. Only short or cash.
    **Volatile Bear:** High volatility + downtrend. Avoid new trades.
    """,
    "session": """
    #### ⏰ Intraday Session Adjustments
    Early morning (9:15-10:00): Volume is building. Scores discounted by 14%.
    Mid session (11:00-13:00): Volume normalizes. Scores discounted by 5%.
    Late session (14:00-15:30): Most reliable data. Scores at 98% confidence.
    Always verify with EOD scan for final decisions.
    """
}

# ===================== LOAD DATA =====================
df = load_market_data()
sector_breadth_df = load_sector_breadth()
port_df = load_table('portfolio')
hist_df = load_table('trade_history')

if not port_df.empty and 'owner' not in port_df.columns:
    port_df['owner'] = "My Portfolio"
if not port_df.empty:
    port_df['owner'] = port_df['owner'].fillna("My Portfolio")
if not hist_df.empty and 'owner' not in hist_df.columns:
    hist_df['owner'] = "My Portfolio"
if not hist_df.empty:
    hist_df['owner'] = hist_df['owner'].fillna("My Portfolio")

# ===================== SIDEBAR =====================
with st.sidebar:
    st.markdown("<h3 class='gradient-text'>💎 Titan Quantum Pro</h3>", unsafe_allow_html=True)
    st.markdown("---")

    if st.button("🔄 Refresh Market Data", use_container_width=True):
        st.cache_data.clear()
        safe_rerun()
    st.caption(f"Last Sync: {datetime.datetime.now().strftime('%H:%M:%S')}")

    st.markdown("---")
    st.markdown("### 🤖 Titan AI Agent")

    agent_input = st.text_area("Chat or type trade:", placeholder="e.g. Bought 50 RELIANCE at 2450", height=80)
    uploaded_image = st.file_uploader("📷 Upload order screenshot", type=['png', 'jpg', 'jpeg'])

    if st.button("🚀 Process Intelligence", use_container_width=True):
        if uploaded_image:
            ocr_result = parse_order_image(uploaded_image)
            if ocr_result and 'error' not in ocr_result:
                st.session_state['agent_result'] = ocr_result
                if ocr_result.get('needs_confirmation'):
                    st.warning(f"⚠️ Detected: {ocr_result['action']} {ocr_result['symbol']} Qty:{ocr_result['qty']:.0f} @ Rs.{ocr_result['price']:.2f}. Please confirm.")
                else:
                    st.success(f"✅ Detected: {ocr_result['action']} {ocr_result['qty']:.0f} {ocr_result['symbol']} @ Rs.{ocr_result['price']:.2f}")
            elif ocr_result and 'error' in ocr_result:
                st.error(f"OCR Error: {ocr_result['error']}")
            else:
                st.error("Could not read order from image. Try typing instead.")
        elif agent_input:
            response = get_response(agent_input, portfolio_df=port_df, market_df=df)
            st.session_state['agent_response'] = response
            st.markdown(f"<div style='background:#141824; border:1px solid #2A3143; padding:15px; border-radius:10px; box-shadow: 0 4px 6px rgba(0,0,0,0.3);'>{response}</div>", unsafe_allow_html=True)
        else:
            st.info("Type a command or upload an image.")

    # Quick action from agent
    if 'agent_result' in st.session_state:
        res = st.session_state['agent_result']
        if res.get('action') == 'BUY' and st.button("✅ Confirm & Add to Portfolio", use_container_width=True):
            live_stock = df[df['SYMBOL'] == res['symbol']] if not df.empty else pd.DataFrame()
            target = float(live_stock['TARGET'].iloc[0]) if not live_stock.empty else (res['price'] * 1.10)
            supabase.table('portfolio').insert({
                "symbol": res['symbol'], "entry_price": res['price'], "qty": res['qty'],
                "date": str(datetime.date.today()), "owner": "My Portfolio",
                "entry_target": target
            }).execute()
            st.success(f"Added {res['symbol']} to portfolio!")
            del st.session_state['agent_result']
            safe_rerun()

    st.markdown("---")
    st.markdown("### 📊 Market Regime")
    if not df.empty and 'REGIME' in df.columns:
        regimes = df['REGIME'].value_counts()
        for regime, count in regimes.items():
            color = "🟢" if "Bull" in regime else "🔴" if "Bear" in regime else "🟡"
            st.markdown(f"{color} {regime}: **{count:.0f}** stocks")

    st.markdown("---")
    st.markdown("### ⚙️ Quick Filters")
    quick_filter = st.radio("Show:", ["All Stocks", "Top 5 Picks", "Top 10 Picks", "Penny Stocks Only"], index=1)

    st.markdown("---")
    st.markdown("### 🛡️ Risk Settings")
    max_dd = st.slider("Max Portfolio DD %", 5, 30, 15)

# ===================== HEADER =====================
st.markdown("<div style='text-align:center;'><h1 class='gradient-text' style='font-size: 3rem;'>Titan Quantum Pro V2</h1></div>", unsafe_allow_html=True)
st.markdown("<div style='text-align:center; color:#A0ABBA; margin-bottom:30px; font-weight:500;'>Institutional-Grade Swing Trading Intelligence</div>", unsafe_allow_html=True)

status, msg, css_class = get_macro_weather()
border_color = "#00FF88" if "green" in css_class else "#FF4B4B" if "red" in css_class else "#FFC107"
bg_color = "rgba(0, 255, 136, 0.05)" if "green" in css_class else "rgba(255, 75, 75, 0.05)" if "red" in css_class else "rgba(255, 193, 7, 0.05)"

st.markdown(f"""
<div style='border-left: 5px solid {border_color}; padding: 20px; background-color: {bg_color}; border-radius: 10px; margin-bottom: 25px; box-shadow: 0 4px 10px rgba(0,0,0,0.2);'>
    <h4 style='margin:0; color: {border_color};'>{status}</h4>
    <p style='margin:8px 0 0 0; color:#E0E6ED; font-weight: 500;'>{msg}</p>
</div>
""", unsafe_allow_html=True)

if not df.empty and 'UPDATED_AT' in df.columns:
    try:
        latest_update = pd.to_datetime(df['UPDATED_AT'].max())
        now_utc = datetime.datetime.utcnow()
        delta_hours = (now_utc - latest_update).total_seconds() / 3600
        if delta_hours > 24 and now_utc.weekday() < 5:
            st.error(f"🔴 CRITICAL: Data is {int(delta_hours)} hours old! Run master scan.", icon="🚨")
    except: pass

# ===================== TABS =====================
tabs = st.tabs([
    "📋 Today's Top Picks",
    "💼 Portfolio Intelligence",
    "🔍 Market Screener",
    "⚡ Breakout Radar",
    "🎰 Penny Sandbox",
    "🏆 History",
    "📚 Knowledge Hub"
])

# ==========================================
# TAB 0: TODAY'S TOP PICKS (Your Main View)
# ==========================================
with tabs[0]:
    st.subheader("🎯 Today's Top Buy Opportunities")
    st.caption("Filtered for your strategy: Rs.10K per trade, 5-10 day hold, 10%+ target")

    if not df.empty:
        inst_df = df[df['CAP_CATEGORY'] != "Small/Penny Cap"]

        if quick_filter == "Top 5 Picks":
            top_n = 5
        elif quick_filter == "Top 10 Picks":
            top_n = 10
        elif quick_filter == "Penny Stocks Only":
            inst_df = df[df['CAP_CATEGORY'] == "Small/Penny Cap"]
            top_n = 10
        else:
            top_n = 20

        actionable_mask = (
            (inst_df['PROBABILITY'] >= 60) &
            (inst_df['SCORE'] >= 60) &
            (inst_df['UPSIDE_%'] >= 8) &
            (~inst_df['VERDICT'].str.contains('AVOID', na=False))
        )
        actionable = inst_df[actionable_mask].copy()
        
        # Calculate expected profit first so we can sort by it
        actionable['Est_Qty'] = (10000 / actionable['PRICE']).astype(int)
        actionable['Est_Profit'] = (actionable['Est_Qty'] * (actionable['TARGET'] - actionable['PRICE'])).round(0)

        # Apply the new 3-tier sorting: Highly recommended -> Score -> Expected Profit
        actionable = actionable.sort_values(
            ['PROBABILITY', 'SCORE', 'Est_Profit'], 
            ascending=[False, False, False]
        ).head(top_n)

        if not actionable.empty:
            avg_prob = actionable['PROBABILITY'].mean()
            avg_score = actionable['SCORE'].mean()
            avg_rr = actionable['RR_RATIO'].mean()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("📊 Avg Probability", f"{avg_prob:.0f}%")
            c2.metric("⭐ Avg Score", f"{avg_score:.0f}")
            c3.metric("⚖️ Avg R:R", f"1:{avg_rr:.0f}")
            c4.metric("🔥 Top Picks", f"{len(actionable):.0f}")

            st.markdown("---")

            display_df = actionable[['SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_%', 'PROBABILITY',
                                     'SCORE', 'RR_RATIO', 'STOP_LOSS', 'PATTERN', 'EST_PERIOD']].copy()
            display_df['Investment'] = "Rs.10K"
            display_df['Est_Qty'] = (10000 / display_df['PRICE']).astype(int)
            display_df['Est_Profit'] = (display_df['Est_Qty'] * (display_df['TARGET'] - display_df['PRICE'])).round(0)

            st.dataframe(
                display_df[['SYMBOL', 'PRICE', 'TARGET', 'UPSIDE_%', 'PROBABILITY', 'SCORE',
                            'RR_RATIO', 'STOP_LOSS', 'Est_Qty', 'Est_Profit', 'PATTERN', 'EST_PERIOD']]
                .rename(columns={'Est_Qty': 'Qty (Rs.10K)', 'Est_Profit': 'Est Profit (Rs.)'})
                .style.format({
                    'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_%': '{:.0f}%',
                    'PROBABILITY': '{:.0f}%', 'SCORE': '{:.0f}', 'RR_RATIO': '1:{:.0f}',
                    'STOP_LOSS': 'Rs.{:.2f}', 'Qty (Rs.10K)': '{:d}', 'Est Profit (Rs.)': 'Rs.{:.0f}'
                }),
                column_config={
                    "PROBABILITY": st.column_config.ProgressColumn("Win Prob", format="%.0f%%", min_value=0, max_value=100),
                    "SCORE": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=100),
                    "UPSIDE_%": st.column_config.NumberColumn("Upside", format="%.0f%%"),
                },
                use_container_width=True, hide_index=True
            )

            st.markdown(KNOWLEDGE["probability"], unsafe_allow_html=True)

            st.markdown("---")
            st.subheader("💎 Detailed Analysis (Top 5)")

            for idx, (_, g) in enumerate(actionable.head(5).iterrows()):
                rr = g['RR_RATIO']
                prob_color = "#00FF88" if g['PROBABILITY'] >= 75 else "#FFC107" if g['PROBABILITY'] >= 60 else "#FF4B4B"

                with st.container():
                    st.markdown(f"""
                    <div style='background:#141824; padding:20px; border-radius:12px; margin-bottom:20px; border-left:5px solid {prob_color}; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'>
                        <h3 style='margin:0; color: #E0E6ED;'>{g['SYMBOL']} <span style='font-size:14px; color:#A0ABBA; font-weight:normal;'>{g['SECTOR']}</span></h3>
                        <div style='display:flex; flex-wrap:wrap; gap:25px; margin-top:15px;'>
                            <div><div style='font-size:13px; color:#A0ABBA;'>Win Prob</div><div style='font-size:22px; font-weight:bold; color:{prob_color};'>{g['PROBABILITY']:.0f}%</div></div>
                            <div><div style='font-size:13px; color:#A0ABBA;'>CMP</div><div style='font-size:20px; color:#E0E6ED;'>Rs.{g['PRICE']:.2f}</div></div>
                            <div><div style='font-size:13px; color:#A0ABBA;'>Target</div><div style='font-size:20px; color:#00FF88;'>Rs.{g['TARGET']:.2f} <span style='font-size:14px;'>(+{g['UPSIDE_%']:.0f}%)</span></div></div>
                            <div><div style='font-size:13px; color:#A0ABBA;'>Stop Loss</div><div style='font-size:20px; color:#FF4B4B;'>Rs.{g['STOP_LOSS']:.2f}</div></div>
                            <div><div style='font-size:13px; color:#A0ABBA;'>R:R</div><div style='font-size:20px; color:#E0E6ED;'>1:{rr:.0f}</div></div>
                            <div><div style='font-size:13px; color:#A0ABBA;'>Hold</div><div style='font-size:20px; color:#E0E6ED;'>{g['EST_PERIOD']}</div></div>
                        </div>
                        <div style='margin-top:15px;'>
                            <span style='background:#2A3143; color:#E0E6ED; padding:6px 12px; border-radius:6px; font-size:13px; font-weight:600;'>Pattern: {g['PATTERN']}</span>
                        </div>
                        <div style='margin-top:10px; font-size:13px; color:#888;'>Monte Carlo: {g.get('MC_DESCRIPTION', 'N/A')}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    with st.expander(f"📊 View {g['SYMBOL']} Chart & Action"):
                        render_interactive_chart(g['SYMBOL'], f"top_pick_{idx}")

                        col1, col2 = st.columns(2)
                        with col1:
                            buy_qty = int(10000 / g['PRICE'])
                            st.info(f"💡 Suggested: **{buy_qty:.0f}** shares for Rs.10K investment")
                        with col2:
                            if st.button(f"➕ Quick Add {g['SYMBOL']}", key=f"quick_add_{g['SYMBOL']}"):
                                supabase.table('portfolio').insert({
                                    "symbol": g['SYMBOL'], "entry_price": g['PRICE'], "qty": buy_qty,
                                    "date": str(datetime.date.today()), "owner": "My Portfolio",
                                    "entry_target": g['TARGET']
                                }).execute()
                                st.success(f"Added {g['SYMBOL']} to portfolio!")
                                safe_rerun()
        else:
            st.info("🟡 No high-probability setups right now. Market may be in risk-off mode.")
            st.markdown(KNOWLEDGE["regime"], unsafe_allow_html=True)
    else:
        st.error("No market data available. Run master scan first.")

# ==========================================
# TAB 1: PORTFOLIO INTELLIGENCE
# ==========================================
with tabs[1]:
    all_owners = port_df['owner'].unique().tolist() if not port_df.empty else ["My Portfolio"]
    selected_owner = st.selectbox("Select Portfolio", sorted(all_owners))
    active_port = port_df[port_df['owner'] == selected_owner] if not port_df.empty else pd.DataFrame()

    if not active_port.empty:
        port_calc = []
        total_damage = 0

        @st.cache_data(ttl=300)
        def fetch_portfolio_history(symbols):
            tickers = [f"{sym}.NS" for sym in symbols]
            try:
                data = yf.download(tickers, period="3mo", group_by="ticker", progress=False, ignore_tz=True)
                return data
            except:
                return pd.DataFrame()

        port_symbols = active_port['symbol'].unique().tolist()
        bulk_hist_data = fetch_portfolio_history(port_symbols)

        for _, row in active_port.iterrows():
            sym = row['symbol']
            live_data = df[df['SYMBOL'] == sym] if not df.empty and 'SYMBOL' in df.columns else pd.DataFrame()

            cmp = float(live_data.iloc[0]['PRICE']) if not live_data.empty else float(row['entry_price'])
            entry = float(row['entry_price'])
            qty = int(row['qty'])

            try:
                if len(port_symbols) > 1 and isinstance(bulk_hist_data.columns, pd.MultiIndex):
                    hist_data = bulk_hist_data[f"{sym}.NS"].copy()
                else:
                    hist_data = bulk_hist_data.copy()
                
                hist_data.dropna(inplace=True)
                hist_data.ta.ema(length=20, append=True)
                hist_data.ta.ema(length=50, append=True)
                hist_data.ta.rsi(length=14, append=True)
                hist_data.ta.macd(fast=12, slow=26, signal=9, append=True)
                hist_data.ta.atr(length=14, append=True)
            except:
                hist_data = pd.DataFrame()

            entry_date = row.get('date', datetime.date.today())
            damage, verdict, new_stop, reasoning = engine.calculate_exit_damage(
                sym, entry, entry_date, hist_data, live_data.iloc[0] if not live_data.empty else None
            )
            total_damage += damage

            live_target = float(live_data.iloc[0]['TARGET']) if not live_data.empty else 0.0
            raw_target = row.get('entry_target')
            try:
                locked_target = float(raw_target) if raw_target and str(raw_target).strip() else live_target
            except:
                locked_target = live_target
            if locked_target == 0: locked_target = live_target

            pnl_pct = ((cmp - entry) / entry) * 100
            cur_profit = qty * (cmp - entry)
            invested = entry * qty
            cur_val = cmp * qty

            if locked_target > entry:
                t_prog = ((cmp - entry) / (locked_target - entry)) * 100
            else:
                t_prog = 0
            t_prog = max(0, min(100, t_prog))

            try:
                days_held = (datetime.date.today() - pd.to_datetime(entry_date).date()).days
            except:
                days_held = 0

            sector = live_data.iloc[0]['SECTOR'] if not live_data.empty else "Unknown"

            port_calc.append({
                "symbol": sym, "sector": sector, "qty": qty, "entry": entry, "cmp": cmp,
                "pnl_pct": pnl_pct, "profit": cur_profit, "target_prog": t_prog,
                "locked_target": locked_target, "new_stop": new_stop, "days_held": days_held,
                "invested": invested, "cur_val": cur_val, "damage": damage,
                "verdict": verdict, "reasoning": reasoning
            })

        pdf = pd.DataFrame(port_calc)
        t_inv, t_cur = pdf['invested'].sum(), pdf['cur_val'].sum()
        net_pnl = t_cur - t_inv
        port_pnl_pct = (net_pnl / t_inv * 100) if t_inv > 0 else 0
        avg_damage = total_damage / len(pdf) if len(pdf) > 0 else 0

        if port_pnl_pct < -max_dd:
            st.error(f"🚨 PORTFOLIO EMERGENCY: Drawdown {port_pnl_pct:.0f}%! Reduce exposure.", icon="⚠️")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("💰 Invested", f"Rs.{t_inv:,.0f}")
        c2.metric("📈 Current Value", f"Rs.{t_cur:,.0f}", f"Rs.{net_pnl:,.0f}")
        c3.metric("🎯 Net P&L", f"{port_pnl_pct:.0f}%")
        c4.metric("⚠️ Avg Damage", f"{avg_damage:.0f}/100",
                  "Healthy" if avg_damage < 30 else "Caution" if avg_damage < 60 else "DANGER")

        col_pie1, col_pie2 = st.columns(2)
        fig_stock = px.pie(pdf, values='cur_val', names='symbol', hole=0.5,
                           title="Allocation by Stock", template="plotly_dark",
                           color_discrete_sequence=px.colors.sequential.Teal)
        fig_stock.update_layout(margin=dict(t=40,b=10,l=10,r=10), height=280, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        col_pie1.plotly_chart(fig_stock, use_container_width=True)

        damage_colors = {'HOLD': '#00FF88', 'TIGHTEN STOP': '#FFC107',
                         'SCALE OUT 50%': '#FF9500', 'EXIT IMMEDIATE': '#FF4B4B'}
        fig_damage = px.bar(pdf, x='symbol', y='damage', color='verdict',
                              color_discrete_map=damage_colors, template="plotly_dark",
                              title="Exit Damage by Holding")
        fig_damage.update_layout(height=280, margin=dict(t=40,b=10,l=10,r=10), plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
        col_pie2.plotly_chart(fig_damage, use_container_width=True)

        st.markdown("##### 📊 Active Holdings")
        display_pdf = pdf[['verdict', 'damage', 'symbol', 'sector', 'qty', 'entry', 'cmp',
                           'pnl_pct', 'target_prog', 'profit', 'locked_target', 'new_stop',
                           'days_held', 'reasoning']].copy()

        st.dataframe(
            display_pdf.style.format({
                "entry": "Rs.{:.2f}", "cmp": "Rs.{:.2f}", "pnl_pct": "{:.0f}%",
                "locked_target": "Rs.{:.2f}", "new_stop": "Rs.{:.2f}", "profit": "Rs.{:.0f}", "damage": "{:.0f}"
            }).map(style_pnl, subset=['pnl_pct']),
            column_config={
                "target_prog": st.column_config.ProgressColumn("To Target", format="%.0f%%", min_value=0, max_value=100),
                "damage": st.column_config.ProgressColumn("Damage", format="%.0f", min_value=0, max_value=100),
            },
            use_container_width=True, hide_index=True
        )

        st.markdown("---")
        st.subheader("🔍 Click a Stock for Detailed Analysis")

        selected_stock = st.selectbox("Select holding to analyze:", ["-- Select --"] + sorted(pdf['symbol'].tolist()))

        if selected_stock != "-- Select --":
            row = pdf[pdf['symbol'] == selected_stock].iloc[0]
            live_data = df[df['SYMBOL'] == selected_stock]

            col_info, col_chart = st.columns([1, 2])
            with col_info:
                badge = get_exit_badge(row['verdict'])
                pnl_color = "#00FF88" if row['pnl_pct'] > 0 else "#FF4B4B"

                st.markdown(f"""
                <div style='background:#141824; padding:20px; border-radius:12px; border: 1px solid #2A3143; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'>
                    <h2 style='margin:0; color:#E0E6ED;'>{selected_stock}</h2>
                    <div style='font-size:28px; font-weight:bold; color:{pnl_color}; margin-bottom:10px;'>{row['pnl_pct']:+.0f}%</div>
                    <div><b>Exit Verdict:</b> <span style='color:{"#FF4B4B" if "EXIT" in badge else "#FFC107" if "SCALE" in badge else "#00FF88"}; font-weight:bold;'>{badge}</span></div>
                    <div style='margin-top:8px;'><b>Damage Score:</b> {row['damage']:.0f}/100</div>
                    <div style='margin-top:8px;'><b>New Stop Loss:</b> Rs.{row['new_stop']:.2f}</div>
                    <div style='margin-top:8px; font-size:13px; color:#A0ABBA; background:#0B0E14; padding:8px; border-radius:6px;'><b>Reasoning:</b><br/>{row['reasoning']}</div>
                    <hr style='border-color:#2A3143; margin: 15px 0;'/>
                    <div style='font-size:13px; color:#E0E6ED; line-height: 1.8;'>
                        <b>Entry:</b> Rs.{row['entry']:.2f} &nbsp;|&nbsp; <b>Qty:</b> {row['qty']:.0f}<br/>
                        <b>CMP:</b> Rs.{row['cmp']:.2f} &nbsp;|&nbsp; <b>Target:</b> Rs.{row['locked_target']:.2f}<br/>
                        <b>Days Held:</b> {row['days_held']:.0f} &nbsp;|&nbsp; <b>Invested:</b> Rs.{row['invested']:,.0f}<br/>
                        <b>Current Value:</b> Rs.{row['cur_val']:,.0f} &nbsp;|&nbsp; <b>P&L:</b> Rs.{row['profit']:,.0f}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                st.markdown("<br/>", unsafe_allow_html=True)
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("🛡️ Update Stop Loss", key=f"update_stop_{selected_stock}"):
                        st.info(f"Recommended new stop: Rs.{row['new_stop']:.2f}. Go to Register Sale if exiting.")
                with col_b2:
                    if st.button("🔴 Register Sale", key=f"sell_{selected_stock}"):
                        st.session_state['sell_stock'] = selected_stock
                        st.session_state['sell_qty'] = row['qty']
                        st.session_state['sell_entry'] = row['entry']

            with col_chart:
                render_interactive_chart(selected_stock, f"portfolio_{selected_stock}")

            if not live_data.empty:
                g = live_data.iloc[0]
                st.markdown(f"""
                <div style='background:#141824; border:1px solid #2A3143; padding:12px; border-radius:8px; margin-top:10px; font-size:13px;'>
                    <b>Live Scan Data:</b> Score {g['SCORE']:.0f} | Prob {g['PROBABILITY']:.0f}% |
                    Pattern: {g['PATTERN']} | Regime: {g['REGIME']}
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")
        st.subheader("⚡ Quick Actions")

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.markdown("#### ➕ Add New Trade")
            with st.form("add_trade"):
                a_sym = st.selectbox("Symbol", sorted(df['SYMBOL'].unique().tolist()) if not df.empty else [])
                a_price = st.number_input("Buy Price", min_value=0.0, format="%.2f")
                a_qty = st.number_input("Quantity", min_value=1, step=1)
                combo_col1, combo_col2 = st.columns(2)
                existing_owner = combo_col1.selectbox("Portfolio", ["➕ Create New"] + sorted(all_owners))
                new_owner = combo_col2.text_input("New Name", placeholder="e.g. Swing Fund")

                if st.form_submit_button("Add to Portfolio"):
                    final_owner = new_owner.strip() if existing_owner == "➕ Create New" else existing_owner
                    if final_owner and a_sym:
                        live_stock = df[df['SYMBOL'] == a_sym]
                        target = float(live_stock['TARGET'].iloc[0]) if not live_stock.empty else (a_price * 1.10)
                        supabase.table('portfolio').insert({
                            "symbol": a_sym, "entry_price": a_price, "qty": int(a_qty),
                            "date": str(datetime.date.today()), "owner": final_owner,
                            "entry_target": target
                        }).execute()
                        st.success(f"Added {a_sym}!")
                        safe_rerun()

        with col_a2:
            st.markdown("#### ➖ Register Sale")
            sell_owner = st.selectbox("Sell From", sorted(all_owners), key="sell_owner")
            sell_holdings = port_df[port_df['owner'] == sell_owner]['symbol'].unique().tolist() if not port_df.empty else []

            with st.form("sell_trade"):
                s_sym = st.selectbox("Stock", sell_holdings if sell_holdings else ["No Holdings"])
                s_price = st.number_input("Sell Price", min_value=0.0, format="%.2f")
                s_qty = st.number_input("Qty", min_value=1, step=1)
                s_reason = st.selectbox("Reason", [
                    "Target Hit 🎯", "Trailing SL Hit 🛡️", "Exit Engine: Scale Out ⚠️",
                    "Exit Engine: Exit Immediate 🚨", "Momentum Exhaustion 📉",
                    "Time Decay ⏳", "Manual Exit ✋"
                ])

                if st.form_submit_button("Execute Sale") and s_sym != "No Holdings":
                    holding = port_df[(port_df['symbol'] == s_sym) & (port_df['owner'] == sell_owner)].iloc[0]
                    if s_qty <= int(holding['qty']):
                        supabase.table('trade_history').insert({
                            "symbol": s_sym, "sell_price": float(s_price), "qty_sold": int(s_qty),
                            "buy_price": float(holding['entry_price']),
                            "realized_pl": float((s_price - holding['entry_price']) * s_qty),
                            "pl_percentage": float(((s_price - holding['entry_price'])/holding['entry_price'])*100),
                            "sell_date": str(datetime.date.today()), "exit_reason": s_reason, "owner": sell_owner
                        }).execute()

                        new_qty = int(holding['qty']) - int(s_qty)
                        if new_qty == 0:
                            supabase.table('portfolio').delete().eq('id', holding['id']).execute()
                        else:
                            supabase.table('portfolio').update({"qty": new_qty}).eq('id', holding['id']).execute()
                        st.success(f"Sold {s_sym}!")
                        safe_rerun()

        with col_a3:
            st.markdown("#### 📤 Bulk Actions")
            if st.button("🚨 Exit All with Damage >70", use_container_width=True):
                high_damage = pdf[pdf['damage'] >= 70]
                if not high_damage.empty:
                    st.warning(f"{len(high_damage):.0f} stocks need immediate attention: {', '.join(high_damage['symbol'].tolist())}")
                else:
                    st.success("No stocks in danger zone.")

            if st.button("📊 Export Portfolio CSV", use_container_width=True):
                csv = pdf.to_csv(index=False)
                st.download_button("Download", csv, "portfolio_export.csv", "text/csv")
    else:
        st.info(f"No active holdings in {selected_owner}.")
        st.markdown(KNOWLEDGE["damage"], unsafe_allow_html=True)

# ==========================================
# TAB 2: MARKET SCREENER
# ==========================================
with tabs[2]:
    if not df.empty:
        inst_df = df[df['CAP_CATEGORY'] != "Small/Penny Cap"]

        st.subheader("🌍 Sector Breadth Heatmap")
        if not sector_breadth_df.empty:
            fig_treemap = px.treemap(
                sector_breadth_df,
                path=[px.Constant("Indian Market"), 'SECTOR'],
                values='TOTAL_STOCKS',
                color='BREADTH_PCT',
                color_continuous_scale=['#FF4B4B', '#0B0E14', '#00FF88'],
                color_continuous_midpoint=50,
                custom_data=['BREADTH_PCT', 'AVG_SCORE', 'BULLISH_STOCKS', 'TOTAL_STOCKS']
            )
            fig_treemap.update_traces(
                hovertemplate="<b>%{label}</b><br>Breadth: %{customdata[0]:.0f}%<<br>Bullish: %{customdata[2]}/%{customdata[3]}<<br>Avg Score: %{customdata[1]:.0f}"
            )
            fig_treemap.update_layout(margin=dict(t=10,l=0,r=0,b=0), height=400, template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig_treemap, use_container_width=True)

        st.markdown("---")
        c1, c2, c3, c4, c5 = st.columns([1.5, 1, 1, 1, 1])
        search_q = c1.selectbox("🔍 Symbol", ["ALL"] + sorted(inst_df['SYMBOL'].dropna().unique().tolist()))
        min_score = c2.slider("Min Score", 0, 100, 50)
        min_prob = c3.slider("Min Prob %", 0, 100, 50)
        min_upside = c4.number_input("Min Upside %", value=5.0)
        show_alpha = c5.checkbox("💎 High Conviction", value=False)

        filtered_df = inst_df[
            (inst_df['SCORE'] >= min_score) &
            (inst_df['PROBABILITY'] >= min_prob) &
            (inst_df['UPSIDE_%'] >= min_upside)
        ]
        if search_q != "ALL":
            filtered_df = filtered_df[filtered_df['SYMBOL'] == search_q]
        if show_alpha:
            filtered_df = filtered_df[filtered_df['VERDICT'].str.contains('ALPHA|STRONG', na=False)]

        if search_q != "ALL" and not filtered_df.empty:
            render_interactive_chart(search_q, "screener")

        st.markdown(f"### 📋 Screener ({len(filtered_df):.0f} stocks)")
        disp_cols = ['VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'SECTOR', 'PATTERN',
                     'EST_PERIOD', 'PRICE', 'TARGET', 'UPSIDE_%', 'RVOL', 'RR_RATIO',
                     'SUPPORT', 'RESISTANCE', 'REGIME']

        st.dataframe(
            filtered_df[disp_cols].sort_values(['PROBABILITY', 'SCORE', 'UPSIDE_%'], ascending=[False, False, False])
            .style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_%': '{:.0f}%',
                          'PROBABILITY': '{:.0f}%', 'SCORE': '{:.0f}', 'RR_RATIO': '1:{:.0f}',
                          'SUPPORT': 'Rs.{:.2f}', 'RESISTANCE': 'Rs.{:.2f}'}),
            column_config={
                "SCORE": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=100),
                "PROBABILITY": st.column_config.ProgressColumn("Win Prob", format="%.0f%%", min_value=0, max_value=100),
            },
            use_container_width=True, hide_index=True
        )

        st.markdown(KNOWLEDGE["score"], unsafe_allow_html=True)
        st.markdown(KNOWLEDGE["rr"], unsafe_allow_html=True)
    else:
        st.error("No data. Run master scan.")

# ==========================================
# TAB 3: BREAKOUT RADAR
# ==========================================
with tabs[3]:
    st.subheader("⚡ Imminent Breakout Radar")
    if not df.empty:
        breakouts = df[
            (df['PATTERN'].str.contains('Squeeze|Consolidating', na=False)) &
            (df['SCORE'] > 50) & (df['PROBABILITY'] > 50)
        ].copy()

        if not breakouts.empty:
            breakouts['DIST_TO_RES_%'] = ((breakouts['RESISTANCE'] - breakouts['PRICE']) / breakouts['PRICE']) * 100
            breakouts = breakouts[(breakouts['DIST_TO_RES_%'] >= -1.0) & (breakouts['DIST_TO_RES_%'] <= 5.0)]
            breakouts['RADAR_STATUS'] = breakouts['DIST_TO_RES_%'].apply(
                lambda x: "🔥 HOT (<1%)" if x <= 1.0 else "⚠️ WARM (1-3%)" if x <= 3.0 else "🧊 COOL (3-5%)"
            )
            breakouts = breakouts.sort_values("DIST_TO_RES_%", ascending=True)

            top_breakouts = breakouts.head(5)
            for _, b in top_breakouts.iterrows():
                status_color = "#FF4B4B" if "HOT" in b['RADAR_STATUS'] else "#FFC107" if "WARM" in b['RADAR_STATUS'] else "#00B8FF"
                col_info, col_chart = st.columns([1, 1.5])
                with col_info:
                    st.markdown(f"""
                    <div style='background:#141824; padding:20px; border-radius:12px; border-left:5px solid {status_color}; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'>
                        <h3 style='margin:0; color:#E0E6ED;'>{b['SYMBOL']}</h3>
                        <div style='color:{status_color}; font-weight:800; font-size:18px;'>{b['RADAR_STATUS']}</div>
                        <div style='margin-top:12px; font-size:16px;'>Rs.{b['PRICE']:.2f} → Resistance Rs.{b['RESISTANCE']:.2f}</div>
                        <div style='margin-top:8px; font-size:14px; color:#A0ABBA;'>Win Prob: {b['PROBABILITY']:.0f}% | Score: {b['SCORE']:.0f}</div>
                        <div style='margin-top:12px; font-size:13px; color:#E0E6ED; background:#2A3143; padding:8px; border-radius:6px;'>Action: Cross Rs.{b['RESISTANCE']:.2f} after 1:30 PM = BUY</div>
                    </div>
                    """, unsafe_allow_html=True)
                with col_chart:
                    with st.expander(f"Chart View"):
                        render_interactive_chart(b['SYMBOL'], f"breakout_{b['SYMBOL']}")

            st.markdown("---")
            st.subheader("📡 Full Radar")
            st.dataframe(
                breakouts[['RADAR_STATUS', 'DIST_TO_RES_%', 'SYMBOL', 'SCORE', 'PROBABILITY',
                           'PRICE', 'RESISTANCE', 'TARGET', 'RVOL']].sort_values('DIST_TO_RES_%')
                .style.format({'PRICE': 'Rs.{:.2f}', 'RESISTANCE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'SCORE': '{:.0f}', 'PROBABILITY': '{:.0f}%'}),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("No imminent breakouts. Cash is a position.")
    else:
        st.error("No data available.")

# ==========================================
# TAB 4: PENNY SANDBOX
# ==========================================
with tabs[4]:
    st.subheader("🎰 High-Risk Penny Sandbox")
    if not df.empty:
        penny_df = df[df['CAP_CATEGORY'] == "Small/Penny Cap"]
        if not penny_df.empty:
            p_search = st.selectbox("Search", ["ALL"] + sorted(penny_df['SYMBOL'].dropna().unique().tolist()))
            if p_search != "ALL":
                penny_df = penny_df[penny_df['SYMBOL'] == p_search]

            st.dataframe(
                penny_df[['VERDICT', 'SCORE', 'PROBABILITY', 'SYMBOL', 'PATTERN', 'EST_PERIOD',
                          'PRICE', 'TARGET', 'UPSIDE_%', 'RVOL']]
                .style.format({'PRICE': 'Rs.{:.2f}', 'TARGET': 'Rs.{:.2f}', 'UPSIDE_%': '{:.0f}%',
                               'PROBABILITY': '{:.0f}%', 'SCORE': '{:.0f}'}),
                column_config={
                    "SCORE": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=100),
                    "PROBABILITY": st.column_config.ProgressColumn("Win Prob", format="%.0f%%", min_value=0, max_value=100),
                },
                use_container_width=True, hide_index=True
            )

            st.markdown(KNOWLEDGE["rvol"], unsafe_allow_html=True)

            high_vol = penny_df[penny_df['RVOL'] >= 2.0].sort_values("SCORE", ascending=False).head(2)
            if not high_vol.empty:
                for _, p in high_vol.iterrows():
                    st.markdown(f"""
                    <div style='background:rgba(255, 75, 75, 0.1); border:1px solid #FF4B4B; padding:15px; border-radius:10px; margin-bottom:10px;'>
                        <b style='color:#FF4B4B;'>{p['SYMBOL']}</b> experiencing massive volume ({p['RVOL']:.0f}x normal).
                        Operator activity detected. High risk - use strict stop at Rs.{p['SUPPORT']:.2f}.
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("No penny stocks in scan.")
    else:
        st.error("No data.")

# ==========================================
# TAB 5: HISTORY & ANALYTICS
# ==========================================
with tabs[5]:
    hist_owners = hist_df['owner'].unique().tolist() if not hist_df.empty else ["My Portfolio"]
    col_h1, col_h2 = st.columns([1, 1])
    owner_choice = col_h1.selectbox("Account", sorted(hist_owners))
    time_filter = col_h2.selectbox("Period", ["All Time", "Today", "This Week", "This Month",
                                                "Financial Year", "Custom Range"])

    active_hist = hist_df[hist_df['owner'] == owner_choice] if not hist_df.empty else pd.DataFrame()

    if not active_hist.empty:
        active_hist['sell_date'] = pd.to_datetime(active_hist['sell_date']).dt.date
        today = datetime.date.today()

        start_date, end_date = None, None
        if time_filter == "Today":
            start_date, end_date = today, today
        elif time_filter == "This Week":
            start_date = today - datetime.timedelta(days=today.weekday())
            end_date = today
        elif time_filter == "This Month":
            start_date = today.replace(day=1)
            end_date = today
        elif time_filter == "Financial Year":
            fy_start = today.year if today.month >= 4 else today.year - 1
            start_date = datetime.date(fy_start, 4, 1)
            end_date = today
        elif time_filter == "Custom Range":
            dates = st.date_input("Range", [today - datetime.timedelta(days=30), today])
            if len(dates) == 2:
                start_date, end_date = dates

        filtered_hist = active_hist.copy()
        if start_date and end_date:
            filtered_hist = filtered_hist[(filtered_hist['sell_date'] >= start_date) &
                                          (filtered_hist['sell_date'] <= end_date)]

        if not filtered_hist.empty:
            total = len(filtered_hist)
            wins = filtered_hist[filtered_hist['realized_pl'] > 0]
            losses = filtered_hist[filtered_hist['realized_pl'] <= 0]
            net = filtered_hist['realized_pl'].sum()
            win_rate = (len(wins) / total) * 100 if total > 0 else 0
            avg_win = wins['pl_percentage'].mean() if not wins.empty else 0
            avg_loss = losses['pl_percentage'].mean() if not losses.empty else 0
            gross_wins = wins['realized_pl'].sum()
            gross_losses = abs(losses['realized_pl'].sum())
            pf = gross_wins / gross_losses if gross_losses > 0 else (10.0 if gross_wins > 0 else 0)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Net Profit", f"Rs.{net:,.0f}")
            c2.metric("Win Rate", f"{win_rate:.0f}%", f"{total:.0f} trades")
            c3.metric("Avg Win", f"{avg_win:+.0f}%")
            c4.metric("Avg Loss", f"{avg_loss:.0f}%")
            c5.metric("Profit Factor", f"{pf:.2f}")

            st.markdown("---")
            st.dataframe(
                filtered_hist[['symbol', 'buy_price', 'sell_price', 'pl_percentage',
                               'realized_pl', 'exit_reason', 'sell_date']].sort_values('sell_date', ascending=False)
                .style.format({"sell_price": "Rs.{:.2f}", "buy_price": "Rs.{:.2f}",
                              "realized_pl": "Rs.{:.0f}", "pl_percentage": "{:.0f}%"})
                .map(style_pnl, subset=['realized_pl']),
                use_container_width=True, hide_index=True
            )

            st.markdown("---")
            st.subheader("📊 Performance by Exit Reason")
            reason_perf = filtered_hist.groupby('exit_reason').agg(
                Trades=('symbol', 'count'),
                Win_Rate=('realized_pl', lambda x: (x > 0).sum() / len(x) * 100),
                Avg_PL=('realized_pl', 'mean')
            ).reset_index()
            st.dataframe(reason_perf.style.format({'Win_Rate': '{:.0f}%', 'Avg_PL': 'Rs.{:.0f}'}),
                         use_container_width=True)
        else:
            st.info(f"No trades in {time_filter}.")
    else:
        st.info("No trade history yet.")

# ==========================================
# TAB 6: KNOWLEDGE HUB
# ==========================================
with tabs[6]:
    st.subheader("📚 Trading Knowledge Hub")
    st.caption("Understand every metric and signal in the app")

    topic = st.selectbox("Select Topic:", [
        "Confluence Score", "Win Probability", "Exit Damage Score", "RVOL (Volume)",
        "Risk:Reward Ratio", "Chart Patterns", "Market Regime", "Intraday Sessions"
    ])

    topic_map = {
        "Confluence Score": "score", "Win Probability": "probability",
        "Exit Damage Score": "damage", "RVOL (Volume)": "rvol",
        "Risk:Reward Ratio": "rr", "Chart Patterns": "pattern",
        "Market Regime": "regime", "Intraday Sessions": "session"
    }

    if topic in topic_map:
        st.markdown(f"<div style='background:#141824; padding:20px; border-radius:12px; border:1px solid #2A3143;'>", unsafe_allow_html=True)
        st.markdown(KNOWLEDGE[topic_map[topic]], unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    col_rule1, col_rule2 = st.columns(2)
    
    with col_rule1:
        st.subheader("🎓 Trading Rules for Your Strategy")
        st.markdown("""
        #### 📋 Your Strategy Parameters
        **Capital per Trade:** Rs.10,000
        **Max Trades/Day:** 5
        **Target Hold:** 5-10 days
        **Minimum Target:** 10% profit
        **Stop Loss:** 1.8 x ATR (typically 6-8%)
        **Entry Filter:** Probability >= 60%, Score >= 60
        **🟢 BUY Rules:**
        1. Only enter if Win Probability >= 60%
        2. Ensure R:R ratio >= 1:1.5
        3. Check market regime is Bull or Strong Bull
        4. Verify no earnings in next 7 days
        5. Max 5 positions per day
        **🔴 SELL Rules:**
        1. If Damage Score >= 80 -> EXIT IMMEDIATE
        2. If Damage Score 56-80 -> SCALE OUT 50%
        3. If target hit -> Sell 50%, trail rest with breakeven stop
        4. If held >14 days with <2% profit -> Consider exit
        5. If gap down >10% -> Emergency exit
        """, unsafe_allow_html=True)

    with col_rule2:
        st.subheader("🤖 How to Use Titan Agent")
        st.markdown("""
        #### 💬 Chat Commands
        **Type natural language:**
        • "Bought 50 RELIANCE at 2450" -> Auto-detects and suggests adding to portfolio
        • "How is my portfolio?" -> Shows summary
        • "Top picks today?" -> Shows best opportunities
        • "How is the market?" -> Shows regime status
        
        #### 📷 Upload Screenshots
        • Take screenshot of your broker order (Zerodha/Groww/Upstox)
        • Upload to the sidebar agent
        • Titan Agent reads it via OCR
        • Confirm to auto-add to portfolio
        
        **Supported Brokers:** Zerodha, Groww, Upstox, Angel One (basic)
        """, unsafe_allow_html=True)
