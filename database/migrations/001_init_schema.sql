-- ============================================================================
-- Stock Agent – Supabase Schema
-- Run this in Supabase Dashboard → SQL Editor → New Query → Run
-- ============================================================================

-- 1. Stocks (master list)
CREATE TABLE IF NOT EXISTS stocks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol      TEXT NOT NULL UNIQUE,
    company_name TEXT DEFAULT '',
    industry    TEXT DEFAULT '',
    exchange    TEXT DEFAULT 'HOSE',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 2. Watchlist
CREATE TABLE IF NOT EXISTS watchlist (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol        TEXT NOT NULL REFERENCES stocks(symbol),
    status        TEXT DEFAULT 'active' CHECK (status IN ('active', 'closed')),
    initial_notes TEXT DEFAULT '',
    added_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol);

-- 3. Investment Theses
CREATE TABLE IF NOT EXISTS investment_theses (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol          TEXT NOT NULL,
    thesis_content  TEXT NOT NULL,
    intrinsic_value DOUBLE PRECISION DEFAULT 0,
    target_price    DOUBLE PRECISION DEFAULT 0,
    stop_loss_price DOUBLE PRECISION DEFAULT 0,
    entry_zone_min  DOUBLE PRECISION DEFAULT 0,
    entry_zone_max  DOUBLE PRECISION DEFAULT 0,
    sentiment_score DOUBLE PRECISION DEFAULT 0.5,
    last_updated    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_theses_symbol ON investment_theses(symbol);
CREATE INDEX IF NOT EXISTS idx_theses_updated ON investment_theses(last_updated DESC);

-- 4. Daily Snapshots
CREATE TABLE IF NOT EXISTS daily_snapshots (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol          TEXT NOT NULL,
    date            DATE NOT NULL DEFAULT CURRENT_DATE,
    close_price     DOUBLE PRECISION DEFAULT 0,
    volume          BIGINT DEFAULT 0,
    change_percent  DOUBLE PRECISION DEFAULT 0,
    ai_commentary   TEXT DEFAULT '',
    action_signal   TEXT DEFAULT 'HOLD',
    created_at      TIMESTAMPTZ DEFAULT now(),

    UNIQUE (symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON daily_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(date DESC);

-- 5. Enable Row Level Security (recommended by Supabase)
ALTER TABLE stocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE investment_theses ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_snapshots ENABLE ROW LEVEL SECURITY;

-- Allow anon key full access (since this is a private backend app)
CREATE POLICY "Allow all on stocks" ON stocks FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on watchlist" ON watchlist FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on investment_theses" ON investment_theses FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all on daily_snapshots" ON daily_snapshots FOR ALL USING (true) WITH CHECK (true);
