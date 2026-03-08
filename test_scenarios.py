"""Quick verification of scenario models and serialization."""
import json
from models.state import ScenarioDetail, InvestmentStrategy

# Test ScenarioDetail creation
scenarios = [
    ScenarioDetail(
        label="BULLISH", probability=50,
        trigger="Breakout > 100k", invalidation="< 80k",
        strategy="BUY_DCA", entry_range=[85000, 95000],
        target_price=120000, stop_loss=80000,
        timeframe="3-6 thang", status="ACTIVE",
    ),
    ScenarioDetail(
        label="BASE", probability=30,
        trigger="Range 85-105k", invalidation="Break range",
        strategy="HOLD", entry_range=[85000, 95000],
        target_price=105000, stop_loss=80000,
        timeframe="1-3 thang", status="ACTIVE",
    ),
    ScenarioDetail(
        label="BEARISH", probability=20,
        trigger="Breakdown < 85k", invalidation="Recovery > 105k",
        strategy="REDUCE", entry_range=[],
        target_price=70000, stop_loss=80000,
        timeframe="1-3 thang", status="ACTIVE",
    ),
]

# Test serialization (mimics what nodes.py does for DB storage)
scenarios_json = json.dumps(
    [s.model_dump() for s in scenarios],
    default=str, ensure_ascii=False,
)
print(f"Serialized {len(scenarios_json)} chars")

# Test deserialization (mimics what worker.py does)
parsed = json.loads(scenarios_json)
print(f"Parsed back {len(parsed)} scenarios: {[s['label'] for s in parsed]}")
for s in parsed:
    print(f"  {s['label']}: {s['probability']}% | strategy={s['strategy']} | status={s['status']}")

# Test InvestmentStrategy with scenarios
strategy = InvestmentStrategy(
    thesis_summary="Test thesis",
    primary_scenario="BULLISH",
    scenarios=scenarios,
    entry_price_range=[85000, 95000],
    target_price=120000,
    stop_loss=80000,
    risk_level="LOW",
    reeval_triggers=["Earnings Q1/2026", "Break 80k support"],
)
print(f"\nStrategy: primary={strategy.primary_scenario}")
print(f"Scenarios: {len(strategy.scenarios)}")
print(f"Reeval triggers: {strategy.reeval_triggers}")

# Test reeval_triggers JSON
reeval_json = json.dumps(strategy.reeval_triggers, ensure_ascii=False)
print(f"Reeval JSON: {reeval_json}")

print("\n✅ ALL VERIFICATION PASSED")
