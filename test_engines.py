"""Quick standalone test for the 3 TA engines."""
from services import vnstock_service
from services.smc_calculator import SMCCalculator
from services.elliott_engine import ElliottWaveEngine
from services.wyckoff_engine import WyckoffEngine

# Fetch data
df = vnstock_service.get_price_history("FPT", days=365)
if isinstance(df, dict):
    print("ERROR:", df)
else:
    print(f"Loaded {len(df)} bars")

    # Test SMC
    smc = SMCCalculator(df.tail(100).reset_index(drop=True))
    s = smc.summary()
    print(f"SMC trend: {s['current_trend']}")
    print(f"  Bullish OBs: {len(s['active_bullish_order_blocks'])}")
    print(f"  Bearish OBs: {len(s['active_bearish_order_blocks'])}")
    print(f"  Unfilled FVGs: {len(s['unfilled_fvg'])}")

    # Test Elliott
    ew = ElliottWaveEngine(df.tail(200).reset_index(drop=True), zigzag_threshold=0.05)
    e = ew.summary()
    print(f"Elliott: {e['primary_structure']}")
    print(f"  Wave: {e['current_wave_label']}")
    print(f"  Pivots: {e['total_zigzag_pivots']}")
    print(f"  Targets: {e['target_fibonacci_zones']}")

    # Test Wyckoff
    wk = WyckoffEngine(df.tail(200).reset_index(drop=True))
    w = wk.summary()
    print(f"Wyckoff: {w['phase']}")
    print(f"  POC: {w['point_of_control']}")
    print(f"  Value Area: {w['value_area']}")
    print(f"  Trading Range: {w['trading_range']}")

    print("\nALL TESTS PASSED")
