# VN-Stock AI Copilot 🇻🇳📈

AI Agent hỗ trợ đầu tư chứng khoán Việt Nam — phân tích chuyên sâu (Fundamental & Technical) và theo dõi biến động danh mục hàng ngày để đưa ra khuyến nghị **Buy / Hold / Sell** dựa trên chiến lược dài hạn.

## Architecture

```mermaid
flowchart LR
    subgraph User
        TG["Telegram Bot 💬"]
    end

    subgraph API ["FastAPI Server"]
        EP["/analyze/{ticker}"]
        WL["/watchlist"]
        HP["/health"]
    end

    subgraph LangGraph ["LangGraph Pipeline"]
        R["🔍 Researcher"]
        A["📊 Analyst<br/>(ReAct Agent)"]
        S["🎯 Strategist"]
        R --> A --> S
    end

    subgraph Tools ["TA Tools (called by Analyst)"]
        T1["🔧 SMC<br/>Order Block · FVG · BOS/CHoCH"]
        T2["🔧 Elliott Wave<br/>ZigZag · Wave Count · Fib"]
        T3["🔧 Wyckoff<br/>Volume Profile · POC · Phase"]
    end

    subgraph Data ["Data Sources"]
        VN["vnstock 📉"]
        NW["News Search 📰"]
    end

    subgraph Storage ["Supabase (Postgres + pgvector)"]
        DB[("stocks\nwatchlist\ninvestment_theses\ndaily_snapshots")]
    end

    subgraph Worker ["Daily Worker ⏰"]
        CJ["APScheduler\n15:45 GMT+7"]
    end

    TG -->|"/analyze VNM"| EP
    TG -->|"/watch VNM"| WL
    EP --> R
    R --> VN
    R --> NW
    A -->|"tool calls"| T1
    A -->|"tool calls"| T2
    A -->|"tool calls"| T3
    T1 --> VN
    T2 --> VN
    T3 --> VN
    S --> DB
    S -->|"Report"| TG
    CJ --> DB
    CJ -->|"Alerts"| TG
    CJ --> VN
```

## Pipeline Flow

```mermaid
sequenceDiagram
    participant U as User / Telegram
    participant R as 🔍 Researcher
    participant A as 📊 Analyst (ReAct)
    participant SMC as 🔧 SMC Tool
    participant EW as 🔧 Elliott Tool
    participant WK as 🔧 Wyckoff Tool
    participant S as 🎯 Strategist
    participant DB as Supabase

    U->>R: /analyze FPT
    R->>R: Fetch financials, OHLCV, news
    R->>A: raw_financials, raw_ohlc, raw_news

    Note over A: ReAct Agent tự chọn tools
    A->>SMC: get_smc_structures("FPT")
    SMC-->>A: trend, OBs, FVGs, BOS/CHoCH
    A->>EW: analyze_elliott_waves("FPT")
    EW-->>A: wave label, Fib targets, invalidation
    A->>WK: analyze_wyckoff("FPT")
    WK-->>A: phase, POC, Value Area, range

    A->>A: Synthesise FA + TA + SMC + Elliott + Wyckoff → JSON
    A->>S: structured analysis (6 dimensions)

    S->>S: Generate final report + DCA plan
    S->>DB: Save thesis
    S->>U: 📋 Markdown report
```

## Project Structure

```
stock-agent/
├── agents/
│   ├── __init__.py
│   ├── nodes.py              # LangGraph nodes (researcher, analyst, strategist)
│   ├── tools.py              # LangChain tools (SMC, Elliott, Wyckoff)
│   └── graph.py              # StateGraph wiring & compilation
├── database/
│   ├── __init__.py
│   ├── migrations/
│   │   └── 001_init_schema.sql
│   ├── migrate.py
│   ├── schema.sql
│   ├── supabase_client.py
│   └── crud.py
├── models/
│   ├── __init__.py
│   └── state.py              # Pydantic schemas & LangGraph AgentState
├── prompts/
│   ├── __init__.py
│   └── system_prompts.py     # Analysis + Analyst (ReAct) + Daily prompts
├── services/
│   ├── __init__.py
│   ├── vnstock_service.py    # Financial data & basic technical indicators
│   ├── smc_calculator.py     # Smart Money Concepts engine
│   ├── elliott_engine.py     # Elliott Wave engine (ZigZag + Rules)
│   ├── wyckoff_engine.py     # Wyckoff engine (Volume Profile + Phases)
│   ├── news_service.py       # News headline search
│   └── telegram_service.py   # Telegram Bot message delivery
├── main.py                   # FastAPI application
├── worker.py                 # Daily cron job (APScheduler)
├── config.py                 # Centralized settings (pydantic-settings)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Analyst Node — ReAct Agent with 3 Tools

Analyst node sử dụng `create_react_agent` (LangGraph) thay vì gọi LLM trực tiếp. Agent tự động gọi 3 tools phân tích kỹ thuật nâng cao:

| Tool | Engine | Chức năng | Lookback |
|------|--------|-----------|----------|
| `get_smc_structures` | `SMCCalculator` | Swing Points, BOS/CHoCH, FVG, Order Blocks | 100 nến |
| `analyze_elliott_waves` | `ElliottWaveEngine` | ZigZag filter, wave count (1-5 / A-B-C), Fibonacci targets | 200 nến |
| `analyze_wyckoff` | `WyckoffEngine` | Volume Profile, POC, Value Area, Trading Range, phase detection | 200 nến |

### SMC (Smart Money Concepts)
- **Swing Points**: Thuật toán cửa sổ trượt (fractal) tìm đỉnh/đáy cục bộ
- **BOS/CHoCH**: Xác định Break of Structure (tiếp diễn) / Change of Character (đảo chiều)
- **FVG**: Khoảng trống giá — `low[i-1] > high[i+1]` = Bullish FVG
- **Order Block**: Nến giảm cuối cùng trước impulse tạo BOS

### Elliott Wave
- **ZigZag**: Lọc nhiễu biến động < 5%, chỉ giữ pivot points chính
- **Rules Engine**: 3 quy tắc bất biến (Wave 2 < 100% W1, Wave 3 không ngắn nhất, Wave 4 ≥ Wave 1 top)
- **Fibonacci**: Projection 100%, 161.8%, 261.8% cho mục tiêu sóng

### Wyckoff
- **Volume Profile**: Tổng volume tại từng mức giá (histogram bins) thay vì theo thời gian
- **POC**: Point of Control — mức giá có thanh khoản lớn nhất
- **Phase**: Accumulation / Distribution / Markup / Markdown

## Quick Start

### 1. Clone & configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 2. Run with Docker (recommended)

```bash
docker-compose up -d
```

This starts:
| Service | Description | Port |
|---------|-------------|------|
| `db` | PostgreSQL 16 + pgvector | 5432 |
| `app` | FastAPI server | 8000 |
| `worker` | Daily cron job (15:45 VN) | — |

### 3. Run locally (alternative)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Start API server
uvicorn main:app --reload --port 8000

# Start worker (separate terminal)
python worker.py
```

## Database Setup & Migration

### 1. Tạo Supabase project (miễn phí)

1. Vào [supabase.com](https://supabase.com) → **Start your project** → đăng nhập bằng GitHub
2. Tạo project mới, chọn region gần nhất (Singapore)
3. Vào **Settings → API** → copy **Project URL** và **anon public key**

### 2. Lấy Database Connection String

1. Vào **Settings → Database** trong Supabase Dashboard
2. Kéo xuống **Connection string** → chọn tab **URI**
3. Copy connection string (dạng `postgresql://postgres.[ref]:[password]@...`)

### 3. Cấu hình `.env`

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-key
SUPABASE_PASSWORD=your-db-password
DATABASE_URL=postgresql://postgres.your-ref:your-password@aws-0-region.pooler.supabase.com:6543/postgres
```

### 4. Chạy Migration

```bash
# Chạy tất cả migration chưa áp dụng
python -m database.migrate

# Kiểm tra trạng thái migration
python -m database.migrate --status
```

### 5. Tạo migration mới

Tạo file SQL mới trong `database/migrations/` với prefix số thứ tự:

```
database/migrations/
├── 001_init_schema.sql        # Tạo bảng stocks, watchlist, theses, snapshots
├── 002_add_new_feature.sql    # Migration tiếp theo...
```

> **Lưu ý**: Migration runner tự động track file đã chạy trong bảng `_migrations`, nên mỗi file chỉ chạy 1 lần. **Không sửa file migration đã chạy** — thay vào đó tạo file migration mới.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/analyze/{ticker}` | Run full AI analysis → returns report + sends to Telegram |
| `POST` | `/watchlist` | Add symbol to watchlist (`{"symbol": "VNM"}`) |
| `GET` | `/watchlist` | List active watchlist items |
| `DELETE` | `/watchlist/{symbol}` | Close a watchlist item |
| `GET` | `/snapshots/{symbol}` | Get daily snapshots history |

### Example

```bash
# Analyze a ticker
curl -X POST http://localhost:8000/analyze/VNM

# Add to watchlist
curl -X POST http://localhost:8000/watchlist \
  -H "Content-Type: application/json" \
  -d '{"symbol": "VNM", "initial_notes": "Blue-chip dairy"}'
```

## Daily Worker (15:45 GMT+7)

The worker runs automatically every trading day at **15:45** (after market close at 15:00):

1. Fetches all active watchlist symbols
2. Gets today's close price & volume via vnstock
3. Compares with stored **Investment Thesis** (target, stop-loss, entry zone)
4. Applies decision tree:
   - 🔴 Price ≤ Stop-Loss → **CẮT LỖ**
   - 🟢 Price in Entry Zone → **MUA THÊM**
   - 🟡 Price ≥ Target → **CHỐT LỜI**
   - ⚪ Otherwise → **GIỮ**
5. Saves daily snapshot to database
6. Sends combined report to Telegram

Run manually: `python worker.py --once`

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| API Framework | FastAPI + Uvicorn |
| AI/LLM | LangGraph + Claude (Anthropic) |
| Agent Framework | LangGraph `create_react_agent` (ReAct) |
| Market Data | vnstock (HOSE, HNX, UPCOM) |
| Technical Analysis | SMC, Elliott Wave, Wyckoff (custom engines) + pandas, numpy |
| Database | Supabase (PostgreSQL + pgvector) |
| Scheduler | APScheduler |
| Notifications | Telegram Bot API |
| Container | Docker + docker-compose |

## License

Private project — all rights reserved.
