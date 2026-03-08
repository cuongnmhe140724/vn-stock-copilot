from typing import TypedDict, List, Optional
from pydantic import BaseModel, Field

# --- THÀNH PHẦN CỦA ĐỊNH GIÁ ---
class FinancialAnalysis(BaseModel):
    revenue_growth: float = Field(description="Tăng trưởng doanh thu YoY (%)")
    profit_growth: float = Field(description="Tăng trưởng lợi nhuận YoY (%)")
    roe: float = Field(description="Tỷ lệ lợi nhuận trên vốn chủ sở hữu")
    pe_ratio: float = Field(description="Chỉ số P/E hiện tại")
    debt_to_equity: float = Field(description="Tỷ lệ Nợ/Vốn chủ sở hữu")
    is_healthy: bool = Field(description="Đánh giá sức khỏe tài chính tổng quát")

class TechnicalSignals(BaseModel):
    trend: str = Field(description="Xu hướng: UP, DOWN, SIDEWAYS")
    rsi: float = Field(description="Chỉ số RSI")
    ma_alignment: str = Field(description="Trạng thái các đường MA (ví dụ: MA20 > MA50)")
    support_zone: str = Field(description="Vùng hỗ trợ gần nhất")
    resistance_zone: str = Field(description="Vùng kháng cự gần nhất")

# --- KỊCH BẢN ĐẦU TƯ ---
class ScenarioDetail(BaseModel):
    """Chi tiết một kịch bản đầu tư (Bullish / Base / Bearish)."""
    label: str = Field(description="BULLISH / BASE / BEARISH")
    probability: int = Field(description="Xác suất xảy ra (0-100%)")
    trigger: str = Field(description="Điều kiện kích hoạt kịch bản")
    invalidation: str = Field(description="Điều kiện phá vỡ kịch bản")
    entry_range: List[float] = Field(default_factory=list, description="Vùng giá mua [min, max]")
    target_price: float = Field(default=0, description="Giá mục tiêu")
    stop_loss: float = Field(default=0, description="Giá cắt lỗ")
    strategy: str = Field(description="BUY_AGGRESSIVE / BUY_DCA / HOLD / ACCUMULATE / REDUCE / SELL / HEDGE")
    timeframe: str = Field(default="", description="Khoảng thời gian dự kiến (e.g. '3-6 tháng')")
    status: str = Field(default="ACTIVE", description="ACTIVE / TRIGGERED / INVALIDATED")

# --- KẾ HOẠCH HÀNH ĐỘNG ---
class InvestmentStrategy(BaseModel):
    thesis_summary: str = Field(description="Tóm tắt luận điểm đầu tư trong 2 câu")
    primary_scenario: str = Field(default="BASE", description="Kịch bản chính: BULLISH / BASE / BEARISH")
    scenarios: List[ScenarioDetail] = Field(default_factory=list, description="Danh sách 3 kịch bản")
    entry_price_range: List[float] = Field(description="Vùng giá mua gom [min, max] (từ kịch bản chính)")
    target_price: float = Field(description="Giá mục tiêu (từ kịch bản chính)")
    stop_loss: float = Field(description="Giá cắt lỗ (từ kịch bản chính)")
    risk_level: str = Field(description="Mức độ rủi ro: LOW, MEDIUM, HIGH")
    reeval_triggers: List[str] = Field(default_factory=list, description="Danh sách trigger cần tái đánh giá")

# --- LANGGRAPH STATE ---
class AgentState(TypedDict):
    # Metadata
    ticker: str
    current_price: float
    mode: str  # "agent_mode" (Claude) | "signal_mode" (DeepSeek R1)
    
    # Raw Data từ các Tool
    raw_financials: dict
    raw_news: List[str]
    raw_ohlc: dict
    
    # Phân tích có cấu trúc từ LLM
    financial_analysis: Optional[FinancialAnalysis]
    technical_signals: Optional[TechnicalSignals]
    
    # Advanced TA from tools
    smc_analysis: Optional[dict]
    elliott_analysis: Optional[dict]
    wyckoff_analysis: Optional[dict]
    
    # Kết quả cuối cùng
    previous_thesis: Optional[str]       # Lấy từ DB để so sánh
    previous_scenarios: Optional[list]   # Kịch bản trước đó từ DB (parsed JSON)
    current_strategy: Optional[InvestmentStrategy]
    daily_delta_note: Optional[str]      # Ghi chú về biến động trong ngày
    final_message: str                   # Nội dung gửi cho User qua Telegram


# --- DAILY FOLLOW-UP STATE ---
class DailyFollowUpState(TypedDict):
    """State for the daily watchlist follow-up workflow."""
    symbol: str
    current_price: float
    close_price: float
    volume: int
    change_percent: float

    # Thesis data from DB
    thesis_target_price: Optional[float]
    thesis_stop_loss: Optional[float]
    thesis_entry_min: Optional[float]
    thesis_entry_max: Optional[float]

    # Output
    action_signal: str  # BUY_MORE, HOLD, SELL, WATCH
    ai_commentary: str
