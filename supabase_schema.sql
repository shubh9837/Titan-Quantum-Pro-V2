-- Market scan results (updated by GitHub Actions)
CREATE TABLE IF NOT EXISTS market_scans (
    SYMBOL TEXT PRIMARY KEY,
    PRICE NUMERIC,
    SCORE NUMERIC,
    PROBABILITY NUMERIC DEFAULT 0,
    REGIME TEXT DEFAULT 'Unknown',
    RSI NUMERIC,
    RVOL NUMERIC,
    TARGET NUMERIC,
    OPTIMISTIC_TARGET NUMERIC DEFAULT 0,
    STOP_LOSS NUMERIC,
    RR_RATIO NUMERIC,
    SUPPORT NUMERIC,
    RESISTANCE NUMERIC,
    PATTERN TEXT,
    EARNINGS_RISK TEXT,
    SECTOR TEXT,
    INSTITUTIONAL_TREND TEXT,
    CAP_CATEGORY TEXT,
    MC_DESCRIPTION TEXT DEFAULT 'N/A',
    UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Portfolio holdings (manual entry via app - SAME TABLE AS V1)
CREATE TABLE IF NOT EXISTS portfolio (
    id SERIAL PRIMARY KEY,
    symbol TEXT,
    entry_price NUMERIC,
    qty INTEGER,
    date DATE,
    owner TEXT DEFAULT 'My Portfolio',
    entry_target NUMERIC
);

-- Trade history (auto-populated on sale - SAME TABLE AS V1)
CREATE TABLE IF NOT EXISTS trade_history (
    id SERIAL PRIMARY KEY,
    symbol TEXT,
    sell_price NUMERIC,
    qty_sold INTEGER,
    buy_price NUMERIC,
    realized_pl NUMERIC,
    pl_percentage NUMERIC,
    sell_date DATE,
    exit_reason TEXT,
    owner TEXT DEFAULT 'My Portfolio'
);

-- Sector breadth (updated by master scan)
CREATE TABLE IF NOT EXISTS sector_breadth (
    SECTOR TEXT PRIMARY KEY,
    BREADTH_PCT NUMERIC,
    AVG_SCORE NUMERIC,
    TOTAL_STOCKS INTEGER,
    BULLISH_STOCKS INTEGER,
    UPDATED_AT TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Enable RLS if needed (optional)
-- ALTER TABLE portfolio ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE trade_history ENABLE ROW LEVEL SECURITY;
