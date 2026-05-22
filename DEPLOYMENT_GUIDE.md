
# 🚀 TITAN QUANTUM PRO V2 — COMPLETE DEPLOYMENT GUIDE
## For Non-Technical Users (Step-by-Step with Screenshots Mentality)

---

## PHASE 1: CREATE YOUR GITHUB REPOSITORY (5 minutes)

### Step 1.1: Go to GitHub
1. Open your browser and go to **github.com**
2. Sign in to your account (shubh9837)
3. Click the **"+"** button in the top-right corner
4. Select **"New repository"**

### Step 1.2: Configure Repository
- **Repository name:** `Titan-Quantum-Pro-V2`
- **Description:** `Institutional-grade swing trading intelligence`
- **Visibility:** Select **"Private"** (your trading data is sensitive!)
- **Initialize:** Check ✅ "Add a README file"
- Click **"Create repository"**

### Step 1.3: Upload All Files
You will upload these files ONE BY ONE:

**Core Application Files:**
1. `app_v2.py` — The main Streamlit app (frontend)
2. `probability_core.py` — The brain (entry probability + exit damage engine)
3. `master_scan_v2.py` — Daily EOD scanner (runs automatically)
4. `intraday_pulse_v2.py` — Live price updater + intraday scoring
5. `titan_agent.py` — Chatbot + OCR screenshot reader

**Configuration Files:**
6. `requirements_v2.txt` — Python dependencies
7. `packages.txt` — Linux packages (for OCR support)
8. `supabase_schema.sql` — Database setup script
9. `.gitignore` — Ignore unnecessary files

**Workflow Files (in .github/workflows/ folder):**
10. `master_scan.yml` — Runs scan at 5AM & 5PM IST
11. `intraday_pulse.yml` — Updates every 15 min during market hours

**Also copy from your old repo:**
12. `Tickers.csv` — Your existing stock list

**How to upload each file:**
1. In your new repo, click **"Add file"** → **"Create new file"**
2. Type the filename (e.g., `app_v2.py`)
3. Copy-paste the ENTIRE code content
4. Scroll down and click **"Commit new file"**
5. Repeat for each file

**For .github/workflows/ files:**
- When creating the file, type the FULL path: `.github/workflows/master_scan.yml`
- GitHub will automatically create the folders

---

## PHASE 2: SET UP SUPABASE DATABASE (10 minutes)

### Step 2.1: Create Supabase Account
1. Go to **supabase.com**
2. Click **"Start your project"**
3. Sign up using your **GitHub account**

### Step 2.2: Create New Project
- **Organization:** Your name or "Trading"
- **Project Name:** `titan-quantum-v2`
- **Database Password:** Create a strong password (save it!)
- **Region:** Choose closest to India (Singapore or Mumbai if available)
- Click **"Create new project"**
- Wait 2-3 minutes for provisioning

### Step 2.3: Run Database Schema
1. In your Supabase dashboard, click **"SQL Editor"** in left sidebar
2. Click **"New query"**
3. Copy the ENTIRE content from `supabase_schema.sql`
4. Paste into the SQL editor
5. Click **"Run"** (green play button)
6. You should see "Success" message

### Step 2.4: Get Your API Keys
1. Click **"Project Settings"** (gear icon at bottom left)
2. Click **"API"** in the left menu
3. You will see TWO important values:
   - **Project URL** (looks like: `https://xxxxxxxx.supabase.co`)
   - **anon public** key (long string starting with `eyJ...`)
4. **COPY BOTH** — paste them in a notepad temporarily

**IMPORTANT:** These tables are the SAME as your V1 app:
- `portfolio` — your holdings
- `trade_history` — your closed trades
- `market_scans` — stock scan results
- `sector_breadth` — market health

This means your existing portfolio data from V1 will work in V2!

---

## PHASE 3: ADD GITHUB SECRETS (5 minutes)

### Step 3.1: Navigate to Secrets
1. In your GitHub repo (`Titan-Quantum-Pro-V2`)
2. Click **"Settings"** tab (top of page)
3. In left sidebar, click **"Secrets and variables"** → **"Actions"**
4. Click **"New repository secret"**

### Step 3.2: Add First Secret
- **Name:** `SUPABASE_URL`
- **Secret:** Paste your Supabase Project URL from Step 2.4
- Click **"Add secret"**

### Step 3.3: Add Second Secret
- **Name:** `SUPABASE_KEY`
- **Secret:** Paste your Supabase `anon public` key from Step 2.4
- Click **"Add secret"**

**Done!** Your secrets are now securely stored.

---

## PHASE 4: DEPLOY STREAMLIT APP (10 minutes)

### Step 4.1: Go to Streamlit Cloud
1. Open **share.streamlit.io** in new tab
2. Sign in with your **GitHub account**
3. Click **"New app"** button

### Step 4.2: Connect Repository
- **Repository:** Select `shubh9837/Titan-Quantum-Pro-V2`
- **Branch:** `main`
- **Main file path:** `app_v2.py`
- Click **"Advanced settings..."**

### Step 4.3: Add Secrets in Streamlit
In the "Secrets" section, paste EXACTLY this format:
```
SUPABASE_URL = "https://your-project-url.supabase.co"
SUPABASE_KEY = "your-anon-key-here"
```
(Replace with your actual values from Step 2.4)

### Step 4.4: Deploy
- Click **"Deploy"**
- Wait 2-3 minutes for build
- Your app URL will appear: `https://titan-quantum-pro-v2-xxx.streamlit.app`
- **Bookmark this URL!**

---

## PHASE 5: RUN YOUR FIRST SCAN (15 minutes)

### Step 5.1: Trigger Master Scan
1. In your GitHub repo, click **"Actions"** tab
2. Click **"Master EOD Scan"** in left sidebar
3. Click **"Run workflow"** button (dropdown)
4. Select **"Run workflow"** from dropdown
5. The scan starts! You can watch the progress

### Step 5.2: Wait for Completion
- The scan takes 10-15 minutes (scans ~1000+ NSE stocks)
- Green checkmark = success
- Red X = check the logs for errors

### Step 5.3: Verify Data in Supabase
1. Go to Supabase dashboard
2. Click **"Table Editor"** in left sidebar
3. Click `market_scans` table
4. You should see rows of stock data!

### Step 5.4: Open Your App
1. Go to your Streamlit URL (from Step 4.4)
2. The app should load with data!
3. If empty, wait 5 minutes and refresh

---

## PHASE 6: UNDERSTAND YOUR NEW APP (10 minutes)

### Tab 1: Today's Top Picks (YOUR MAIN TAB)
This is where you find trades:
- **Top 5/10 Picks:** Pre-filtered for your Rs.10K strategy
- **Compact Table:** Shows CMP, Target, Upside %, Probability, Score, R:R, Stop Loss
- **Qty Calculator:** Auto-calculates shares for Rs.10K investment
- **Quick Add:** One-click add to portfolio

**How to use:**
1. Check "Avg Probability" — should be >65% for good day
2. Look at top 5 cards — each shows detailed analysis
3. Click "Quick Add" to add to your portfolio
4. Max 5 trades per day!

### Tab 2: Portfolio Intelligence
This monitors your holdings:
- **Damage Score:** 0-100 scale showing stock health
- **Exit Verdicts:** HOLD / TIGHTEN STOP / SCALE OUT / EXIT IMMEDIATE
- **Click any stock:** Opens detailed view with chart + reasoning
- **Bottom Actions:** Add trade / Register sale / Bulk exit

**How to read Damage Score:**
- 🟢 0-30: Normal — keep holding
- 🟡 31-55: Caution — move stop to breakeven
- 🟠 56-80: Danger — sell 50% immediately
- 🔴 81-100: Critical — exit everything NOW

### Tab 3: Market Screener
Full market view with filters:
- Search any symbol
- Filter by score, probability, upside
- Sector breadth heatmap
- Knowledge articles built-in

### Tab 4: Breakout Radar
Stocks about to break resistance:
- 🔥 HOT: Within 1% of resistance
- ⚠️ WARM: 1-3% away
- 🧊 COOL: 3-5% away

### Tab 5: Penny Sandbox
High-risk micro caps:
- Only for experienced traders
- RVOL > 2.0x = operator activity
- Max 5% of capital per penny stock

### Tab 6: History & Analytics
Track your performance:
- Win rate, profit factor, avg win/loss
- Filter by time period
- Performance by exit reason

### Tab 7: Knowledge Hub
Learn every metric:
- What is Confluence Score?
- What is Win Probability?
- What is Exit Damage?
- Your strategy rules
- How to use Titan Agent

---

## PHASE 7: USE TITAN AGENT (5 minutes)

### In the Sidebar:
1. **Type commands:**
   - "Bought 50 RELIANCE at 2450"
   - "How is my portfolio?"
   - "Top picks today?"
   - "How is the market?"

2. **Upload screenshots:**
   - Take screenshot of your broker order (Zerodha/Groww)
   - Upload to the file uploader
   - Agent reads it via OCR
   - Click "Confirm & Add" to auto-add to portfolio

### Supported Brokers for OCR:
- Zerodha Kite
- Groww
- Upstox Pro
- Angel One (basic)

---

## AUTOMATION SCHEDULE (Already Configured)

Your app automatically updates:

| Time (IST) | Action | GitHub Action |
|-----------|--------|--------------|
| 5:00 AM | Full EOD scan | `master_scan.yml` |
| 5:00 PM | Full EOD scan | `master_scan.yml` |
| 9:15 AM - 3:30 PM | Live prices every 15 min | `intraday_pulse.yml` |
| 9:15 AM - 3:30 PM | Intraday score updates | `intraday_pulse.yml` |
| 9:15 AM - 3:30 PM | Portfolio emergency checks | `intraday_pulse.yml` |

**Intraday Adjustments:**
- Early morning (9:15-10:00): Scores discounted 14% (low volume)
- Mid session (11:00-13:00): Scores discounted 5% (normalizing)
- Late session (14:00-15:30): Scores at 98% confidence (full data)

---

## TROUBLESHOOTING

### App shows "No data"
- Run Master Scan manually (Phase 5)
- Wait 15 minutes
- Refresh the app

### GitHub Actions failing
- Check Secrets are correct (Phase 3)
- Verify `Tickers.csv` is uploaded
- Check Action logs for specific errors

### Streamlit app not loading
- Check `app_v2.py` has no syntax errors
- Verify secrets in Streamlit Advanced Settings
- Try redeploying

### Portfolio not showing
- Ensure Supabase tables exist (Phase 2)
- Check table names: `portfolio` and `trade_history`
- Verify data was entered correctly

---

## COMPARISON: V1 vs V2

| Feature | V1 | V2 |
|---------|-----|-----|
| Entry Score | Basic 100-pt | Bayesian Probability % + Score |
| Exit Logic | Trailing SL only | 4-tier Damage Score system |
| Market Hours | No adjustment | Session-aware confidence |
| Top Picks | All stocks | Filtered for Rs.10K strategy |
| Charts | Basic candlestick | EMA + Volume overlay |
| Agent | None | Chatbot + OCR |
| Knowledge | None | Built-in articles |
| Portfolio Actions | Basic | Click-to-expand + quick actions |
| Data Tables | Simple | Progress bars + color coding |

---

## IMPORTANT REMINDERS

1. **No model is 100% accurate** — probability means likelihood, not guarantee
2. **Paper trade for 30 days** before using real money
3. **Max 5 trades/day** — stick to your discipline
4. **Rs.10K per trade** — don't oversize
5. **5-10 day hold** — don't marry stocks
6. **Exit when Damage >80** — capital preservation is key
7. **Check both apps** — run V1 and V2 in parallel for comparison

---

## SUPPORT

If stuck:
1. Check Knowledge Hub tab in the app
2. Review GitHub Action logs
3. Check Supabase Table Editor for data
4. Ensure all secrets are correct

**Happy Trading! 🚀**
