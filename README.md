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
        A["📊 Analyst"]
        S["🎯 Strategist"]
        R --> A --> S
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
    S --> DB
    S -->|"Report"| TG
    CJ --> DB
    CJ -->|"Alerts"| TG
    CJ --> VN
```

## Project Structure

```
stock-agent/
├── agents/
│   ├── __init__.py
│   ├── nodes.py              # LangGraph nodes (researcher, analyst, strategist)
│   └── graph.py              # StateGraph wiring & compilation
├── database/
│   ├── __init__.py
│   ├── migrations/
│   │   └── 001_init_schema.sql  # Initial tables (stocks, watchlist, theses, snapshots)
│   ├── migrate.py               # Python migration runner
│   ├── schema.sql               # Postgres DDL reference
│   ├── supabase_client.py       # Singleton Supabase client
│   └── crud.py                  # CRUD operations for all tables
├── models/
│   ├── __init__.py
│   └── state.py              # Pydantic schemas & LangGraph AgentState
├── prompts/
│   ├── __init__.py
│   └── system_prompts.py     # Super System Prompt + Daily Follow-up Prompt
├── services/
│   ├── __init__.py
│   ├── vnstock_service.py    # Financial data & technical indicators
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
| AI/LLM | LangGraph + Claude 3.5 Sonnet (Anthropic) |
| Market Data | vnstock (HOSE, HNX, UPCOM) |
| Database | Supabase (PostgreSQL + pgvector) |
| Scheduler | APScheduler |
| Notifications | Telegram Bot API |
| Technical Analysis | pandas, numpy, ta |
| Container | Docker + docker-compose |

## License

Private project — all rights reserved.
