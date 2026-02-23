-- 1. Bảng lưu trữ thông tin cơ bản của các mã cổ phiếu
CREATE TABLE stocks (
    symbol VARCHAR(10) PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry TEXT,
    exchange VARCHAR(10), -- HOSE, HNX, UPCOM
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Danh mục theo dõi (Watchlist)
CREATE TABLE watchlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(10) REFERENCES stocks(symbol) ON DELETE CASCADE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'active', -- active, closed
    initial_notes TEXT
);

-- 3. Luận điểm đầu tư (Investment Thesis) - Lưu trữ chiến lược dài hạn
CREATE TABLE investment_theses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(10) REFERENCES stocks(symbol) ON DELETE CASCADE,
    
    -- Định giá và kế hoạch
    intrinsic_value DECIMAL(15, 2),
    target_price DECIMAL(15, 2),
    stop_loss_price DECIMAL(15, 2),
    entry_zone_min DECIMAL(15, 2),
    entry_zone_max DECIMAL(15, 2),
    
    -- Nội dung phân tích
    thesis_content TEXT, -- Nội dung chi tiết Markdown
    sentiment_score FLOAT, -- Điểm số tích cực/tiêu cực từ AI (0-1)
    
    -- RAG Support (Nếu bạn lưu embedding của báo cáo PDF)
    embedding VECTOR(1536), -- Giả định dùng OpenAI embedding
    
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. Nhật ký biến động hàng ngày (Daily Snapshots)
CREATE TABLE daily_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol VARCHAR(10) REFERENCES stocks(symbol) ON DELETE CASCADE,
    date DATE DEFAULT CURRENT_DATE,
    close_price DECIMAL(15, 2),
    volume BIGINT,
    change_percent DECIMAL(5, 2),
    
    -- AI Insight cho phiên hôm đó
    ai_commentary TEXT,
    action_signal VARCHAR(20), -- BUY_MORE, HOLD, SELL, WATCH
    
    UNIQUE(symbol, date)
);

-- Indexes để truy vấn nhanh
CREATE INDEX idx_watchlist_symbol ON watchlist(symbol);
CREATE INDEX idx_daily_snapshots_date ON daily_snapshots(date);