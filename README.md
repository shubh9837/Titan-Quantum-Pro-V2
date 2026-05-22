# 💎 Titan Quantum Pro V2

**Institutional-Grade Swing Trading Intelligence for Indian Markets**

## What's New in V2

| Feature | V1 | V2 |
|---------|-----|-----|
| Entry Logic | Basic 100-pt score | **Bayesian Probability %** + Confluence Score |
| Exit Logic | Trailing SL only | **Damage Score (0-100)** with 4-tier verdicts |
| Market Hours | No adjustment | **Session-aware confidence discounts** |
| Target Price | Fixed 3x ATR | **Monte Carlo projected range** |
| Top Picks | All stocks | **Filtered for Rs.10K strategy** with qty calculator |
| Agent | None | **Chatbot + OCR screenshot reader** |
| Knowledge | None | **Built-in articles under every tab** |

## Architecture

```
GitHub (Code + CI/CD)
  ├── GitHub Actions: Master Scan (5AM & 5PM IST)
  ├── GitHub Actions: Intraday Pulse (Every 15 min)
  └── Streamlit Cloud (Frontend)
         ↓
Supabase (Database)
  ├── market_scans (live stock data)
  ├── portfolio (your holdings)
  ├── trade_history (closed trades)
  └── sector_breadth (market health)
```

## Quick Start

### 1. Create GitHub Repository
- Go to github.com → New Repository
- Name: `Titan-Quantum-Pro-V2`
- Make it **Private**
- Upload all files from this repo

### 2. Set Up Supabase
- Go to supabase.com → New Project
- Run `supabase_schema.sql` in SQL Editor
- Copy Project URL and Anon Key

### 3. Add GitHub Secrets
In your repo: Settings → Secrets → Actions
- `SUPABASE_URL`: Your Supabase URL
- `SUPABASE_KEY`: Your Anon Key

### 4. Deploy Streamlit
- Go to share.streamlit.io
- Connect your GitHub repo
- Main file: `app_v2.py`
- Add same secrets in Advanced Settings

### 5. Run First Scan
- GitHub Actions → Master EOD Scan → Run workflow
- Wait 15 minutes for ~1000 stocks

## Your Trading Strategy (Built-In)

- **Capital per Trade:** Rs.10,000
- **Max Trades/Day:** 5
- **Hold Period:** 5-10 days
- **Minimum Target:** 10% profit
- **Entry Filter:** Probability >= 60%, Score >= 60
- **Stop Loss:** 1.8 x ATR (~6-8%)

## Titan Agent Commands

Type natural language in the sidebar:
- `"Bought 50 RELIANCE at 2450"` → Auto-detects trade
- `"How is my portfolio?"` → Summary
- `"Top picks today?"` → Best opportunities
- Upload broker screenshot → OCR reads order details

## Exit Engine Guide

| Damage Score | Verdict | Action |
|-------------|---------|--------|
| 0-30 | HOLD | Keep original stop |
| 31-55 | TIGHTEN STOP | Move to breakeven |
| 56-80 | SCALE OUT 50% | Sell half, trail rest |
| 81-100 | EXIT IMMEDIATE | Cut loss now |

## Files

- `app_v2.py` - Streamlit frontend
- `probability_core.py` - Entry/Exit engine
- `master_scan_v2.py` - Daily EOD scanner
- `intraday_pulse_v2.py` - Live price + intraday scores
- `titan_agent.py` - Chatbot + OCR
- `requirements_v2.txt` - Dependencies
- `packages.txt` - Linux packages for OCR
- `.github/workflows/` - Automation

## Disclaimer

This app provides analytical insights, not investment advice. Always do your own research. Past performance does not guarantee future results.
