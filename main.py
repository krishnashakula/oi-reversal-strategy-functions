#!/usr/bin/env python3
"""
OI Reversal Strategy - Main Application

This application implements the OI Reversal Strategy with:
- 88% Win Rate Target
- Entry: Call OI > 2x Put OI at same strike
- Exit: OI normalizes or 15% profit
- Database tracking and forward testing
- Professional dashboard
- Azure deployment ready
"""

import argparse
import logging
import sys
from datetime import datetime
from trading_database import TradingDatabase
from oi_reversal_strategy import OIReversalStrategy
from forward_tester import ForwardTester
from oi_reversal_dashboard import run_oi_reversal_dashboard

def setup_logging(log_level=logging.INFO):
    """Setup logging configuration"""
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('oi_reversal_strategy.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Reduce noise from external libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('streamlit').setLevel(logging.WARNING)

def run_dashboard():
    """Run the Streamlit dashboard"""
    print("🚀 Starting OI Reversal Strategy Dashboard...")
    print("📊 Dashboard will be available at: http://localhost:8501")

    try:
        run_oi_reversal_dashboard()
    except Exception as e:
        print(f"❌ Error starting dashboard: {e}")
        sys.exit(1)

def run_forward_test(duration_hours=24, cycle_interval_minutes=5, symbols=None):
    """Run forward testing"""
    if symbols is None:
        symbols = ['NIFTY.NS', 'BANKNIFTY.NS']

    print(f"🔄 Starting Forward Test for {duration_hours} hours")
    print(f"📈 Symbols: {', '.join(symbols)}")
    print(f"⏱️  Cycle Interval: {cycle_interval_minutes} minutes")
    print("📊 View results at: http://localhost:8501")

    try:
        tester = ForwardTester(
            symbols=symbols,
            test_duration_hours=duration_hours
        )

        tester.run_continuous_test(cycle_interval_seconds=cycle_interval_minutes * 60)

    except KeyboardInterrupt:
        print("\n⏹️  Forward testing stopped by user")
    except Exception as e:
        print(f"❌ Error in forward testing: {e}")
        sys.exit(1)

def run_single_cycle(symbols=None):
    """Run a single strategy cycle"""
    if symbols is None:
        symbols = ['NIFTY.NS']

    print(f"🔄 Running single strategy cycle for: {', '.join(symbols)}")

    try:
        from Bot import StreetSmartTradingEngine

        # Initialize components
        db = TradingDatabase()
        strategy = OIReversalStrategy(db)
        engine = StreetSmartTradingEngine(symbols=symbols, poll_interval=30)

        # Fetch data and run strategy
        market_data_list = engine.fetch_all_data()

        total_signals = 0
        total_positions = 0

        for market_data in market_data_list:
            results = strategy.run_strategy_cycle(market_data)
            total_signals += results.get('signals_detected', 0)
            total_positions += results.get('positions_opened', 0)

            symbol = market_data.get('symbol', 'UNKNOWN')
            print(f"📊 {symbol}: {results.get('signals_detected', 0)} signals, "
                  f"{results.get('positions_opened', 0)} positions opened")

        print(f"✅ Cycle completed: {total_signals} signals detected, {total_positions} positions opened")

    except Exception as e:
        print(f"❌ Error in single cycle: {e}")
        sys.exit(1)

def show_status():
    """Show current strategy status"""
    try:
        db = TradingDatabase()
        strategy = OIReversalStrategy(db)
        status = strategy.get_strategy_status()

        print("📊 OI Reversal Strategy Status")
        print("=" * 40)

        performance = status['performance']
        print(f"Win Rate: {performance.get('win_rate', 0):.1f}% (Target: 88%)")
        print(f"Total P&L: ₹{performance.get('total_pnl', 0):,.0f}")
        print(f"Total Trades: {performance.get('total_trades', 0)}")
        print(f"Open Positions: {status.get('open_positions', 0)}")
        print(f"Recent Signals: {status.get('recent_signals', 0)}")

        print("\n📋 Strategy Parameters:")
        params = status['parameters']
        for param, value in params.items():
            print(f"  {param}: {value}")

        print(f"\n📅 Last Updated: {status.get('last_updated', 'Never')}")

    except Exception as e:
        print(f"❌ Error getting status: {e}")
        sys.exit(1)

def main():
    """Main application entry point"""
    parser = argparse.ArgumentParser(
        description="OI Reversal Strategy - 88% Win Rate Target",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py dashboard              # Run dashboard
  python main.py test --duration 24     # Run 24-hour forward test
  python main.py cycle --symbols NIFTY.NS BANKNIFTY.NS  # Single cycle
  python main.py status                 # Show strategy status
        """
    )

    parser.add_argument(
        'command',
        choices=['dashboard', 'test', 'cycle', 'status'],
        help='Command to run'
    )

    parser.add_argument(
        '--duration',
        type=int,
        default=24,
        help='Test duration in hours (default: 24)'
    )

    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='Cycle interval in minutes (default: 5)'
    )

    parser.add_argument(
        '--symbols',
        nargs='+',
        default=['NIFTY.NS', 'BANKNIFTY.NS'],
        help='Symbols to trade (default: NIFTY.NS BANKNIFTY.NS)'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level (default: INFO)'
    )

    args = parser.parse_args()

    # Setup logging
    log_level = getattr(logging, args.log_level.upper())
    setup_logging(log_level)

    print("🎯 OI Reversal Strategy v1.0")
    print("Target: 88% Win Rate | Entry: Call OI > 2x Put OI | Exit: OI Normalizes or 15% Profit")
    print("-" * 70)

    # Execute command
    if args.command == 'dashboard':
        run_dashboard()
    elif args.command == 'test':
        run_forward_test(
            duration_hours=args.duration,
            cycle_interval_minutes=args.interval,
            symbols=args.symbols
        )
    elif args.command == 'cycle':
        run_single_cycle(symbols=args.symbols)
    elif args.command == 'status':
        show_status()

if __name__ == "__main__":
    main()