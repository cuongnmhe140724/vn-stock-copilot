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

# --- KẾ HOẠCH HÀNH ĐỘNG ---
class InvestmentStrategy(BaseModel):
    thesis_summary: str = Field(description="Tóm tắt luận điểm đầu tư trong 2 câu")
    entry_price_range: List[float] = Field(description="Vùng giá mua gom [min, max]")
    target_price: float = Field(description="Giá mục tiêu dài hạn")
    stop_loss: float = Field(description="Giá cắt lỗ tuyệt đối")
    risk_level: str = Field(description="Mức độ rủi ro: LOW, MEDIUM, HIGH")

# --- LANGGRAPH STATE ---
class AgentState(TypedDict):
    # Metadata
    ticker: str
    current_price: float
    
    # Raw Data từ các Tool
    raw_financials: dict
    raw_news: List[str]
    raw_ohlc: dict
    
    # Phân tích có cấu trúc từ LLM
    financial_analysis: Optional[FinancialAnalysis]
    technical_signals: Optional[TechnicalSignals]
    
    # Kết quả cuối cùng
    previous_thesis: Optional[str] # Lấy từ DB để so sánh
    current_strategy: Optional[InvestmentStrategy]
    daily_delta_note: Optional[str] # Ghi chú về biến động trong ngày
    final_message: str # Nội dung gửi cho User qua Telegram


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
