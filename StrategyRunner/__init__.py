import logging
import azure.functions as func
from datetime import datetime
from trading_database import TradingDatabase
from oi_reversal_strategy import OIReversalStrategy
from Bot import StreetSmartTradingEngine

def main(timer: func.TimerRequest) -> None:
    """Timer-triggered function to run OI Reversal Strategy cycle"""

    if timer.past_due:
        logging.info('StrategyRunner function is running late!')

    logging.info('StrategyRunner function triggered at %s', datetime.now())

    try:
        # Initialize components
        db = TradingDatabase()
        strategy = OIReversalStrategy(db)
        engine = StreetSmartTradingEngine(symbols=['NIFTY.NS', 'BANKNIFTY.NS'], poll_interval=30)

        # Fetch market data
        market_data_list = engine.fetch_all_data()

        if not market_data_list:
            logging.warning('No market data fetched')
            return

        total_signals = 0
        total_positions_opened = 0
        total_positions_closed = 0

        # Run strategy for each symbol
        for market_data in market_data_list:
            try:
                symbol = market_data.get('symbol', 'UNKNOWN')
                logging.info(f'Running strategy cycle for {symbol}')

                # Execute strategy cycle
                results = strategy.run_strategy_cycle(market_data)

                signals = results.get('signals_detected', 0)
                positions_opened = results.get('positions_opened', 0)
                positions_closed = results.get('positions_closed', 0)

                total_signals += signals
                total_positions_opened += positions_opened
                total_positions_closed += positions_closed

                logging.info(f'{symbol}: {signals} signals, +{positions_opened} positions opened, -{positions_closed} positions closed')

            except Exception as e:
                symbol = market_data.get('symbol', 'UNKNOWN')
                logging.error(f'Error processing {symbol}: {e}')
                continue

        # Log summary
        logging.info(f'Strategy cycle completed: {total_signals} signals detected, '
                    f'{total_positions_opened} positions opened, {total_positions_closed} positions closed')

        # Get current performance for monitoring
        performance = db.get_performance_metrics(days=1)
        win_rate = performance.get('win_rate', 0)
        total_pnl = performance.get('total_pnl', 0)

        logging.info(f'Current performance - Win Rate: {win_rate:.1f}%, Total P&L: ₹{total_pnl:,.0f}')

    except Exception as e:
        logging.error(f'Critical error in StrategyRunner: {e}')
        raise  # Re-raise to mark function as failed