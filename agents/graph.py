"""LangGraph state machine – wires researcher → analyst → strategist."""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, START, END

from models.state import AgentState
from agents.nodes import researcher_node, analyst_node, strategist_node

logger = logging.getLogger(__name__)


def build_graph() -> StateGraph:
    """Build and return the compiled analysis graph."""

    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("strategist", strategist_node)

    # Wire edges: START → researcher → analyst → strategist → END
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "strategist")
    graph.add_edge("strategist", END)

    return graph.compile()


# Pre-compiled graph singleton
_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def run_analysis(ticker: str) -> AgentState:
    """Run the full analysis pipeline for a given ticker.

    Returns the final AgentState with all analysis results.
    """
    logger.info("🚀 Starting analysis pipeline for %s", ticker)

    graph = _get_graph()

    initial_state: AgentState = {
        "ticker": ticker.upper(),
        "current_price": 0.0,
        "raw_financials": {},
        "raw_news": [],
        "raw_ohlc": {},
        "financial_analysis": None,
        "technical_signals": None,
        "previous_thesis": None,
        "current_strategy": None,
        "daily_delta_note": None,
        "final_message": "",
    }

    result = graph.invoke(initial_state)
    logger.info("✅ Analysis pipeline completed for %s", ticker)
    return result
