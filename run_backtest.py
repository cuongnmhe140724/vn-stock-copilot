"""CLI entry point for running backtests.

Usage::

    python run_backtest.py --ticker FPT --start 2024-01-01 --end 2024-12-31
    python run_backtest.py --ticker VCB --start 2024-01-01 --end 2024-12-31 --mode agent_mode
    python run_backtest.py --ticker VNM --start 2024-06-01 --end 2024-12-31 --rebalance 5 --plot
"""

from __future__ import annotations

import argparse
import logging
import sys
import json

# Ensure project root is on path
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Run a backtest for a Vietnamese stock using AI-powered signals.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_backtest.py --ticker FPT --start 2024-01-01 --end 2024-12-31
  python run_backtest.py --ticker VCB --mode agent_mode --rebalance 5
  python run_backtest.py --ticker VNM --start 2024-06-01 --end 2024-12-31 --plot
        """,
    )

    parser.add_argument("--ticker", required=True, help="Stock symbol (e.g. FPT, VCB, VNM)")
    parser.add_argument("--start", default="2024-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2024-12-31", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--mode", default="signal_mode",
        choices=["signal_mode", "agent_mode"],
        help="signal_mode=DeepSeek R1 (cheap), agent_mode=full Claude pipeline (expensive)",
    )
    parser.add_argument("--cash", type=float, default=100_000_000, help="Initial cash in VND (default: 100M)")
    parser.add_argument("--rebalance", type=int, default=2, help="Re-evaluate every N bars (default: 2)")
    parser.add_argument("--commission", type=float, default=0.0015, help="Commission rate (default: 0.15%%)")
    parser.add_argument("--position-size", type=float, default=0.9, help="Position size fraction (default: 0.9)")
    parser.add_argument("--max-bars", type=int, default=0, help="Stop after N bars (0=run all). Partial report generated.")
    parser.add_argument("--plot", action="store_true", help="Show chart after backtest")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s │ %(name)-30s │ %(levelname)-7s │ %(message)s",
    )

    # Run backtest
    from backtesting.runner import run_backtest

    try:
        result = run_backtest(
            ticker=args.ticker.upper(),
            start_date=args.start,
            end_date=args.end,
            mode=args.mode,
            initial_cash=args.cash,
            rebalance_every=args.rebalance,
            commission=args.commission,
            position_size_pct=args.position_size,
            max_bars=args.max_bars,
            plot=args.plot,
        )

        if args.json:
            print(json.dumps(result.to_dict(), default=str, indent=2, ensure_ascii=False))

        # Exit with appropriate code
        sys.exit(0)

    except Exception as exc:
        logging.exception("Backtest failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
