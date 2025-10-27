import logging
import json
import azure.functions as func
from datetime import datetime
from trading_database import TradingDatabase
from oi_reversal_strategy import OIReversalStrategy

def main(req: func.HttpRequest) -> func.HttpResponse:
    """Dashboard HTTP Function - Returns strategy status and performance data"""

    logging.info('Dashboard function triggered')

    # Handle preflight OPTIONS request for CORS
    if req.method == 'OPTIONS':
        return func.HttpResponse(
            status_code=200,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type'
            }
        )

    try:
        # Initialize components
        db = TradingDatabase()
        strategy = OIReversalStrategy(db)

        # Get dashboard data
        status = strategy.get_strategy_status()
        performance = status['performance']

        # Get recent signals and positions
        recent_signals = db.get_recent_signals(limit=10)
        open_positions = db.get_open_positions()

        # Get P&L history for charts
        pnl_history = db.get_pnl_history(days=30)

        # Prepare dashboard response
        dashboard_data = {
            'status': 'success',
            'timestamp': status.get('last_updated', ''),
            'performance': {
                'win_rate': performance.get('win_rate', 0),
                'total_pnl': performance.get('total_pnl', 0),
                'total_trades': performance.get('total_trades', 0),
                'winning_trades': performance.get('winning_trades', 0),
                'profit_factor': performance.get('profit_factor', 0),
                'max_drawdown': performance.get('max_drawdown', 0)
            },
            'positions': {
                'open_count': len(open_positions),
                'open_positions': open_positions[:5]  # Last 5 positions
            },
            'signals': {
                'recent_count': len(recent_signals),
                'recent_signals': recent_signals[:5]  # Last 5 signals
            },
            'charts': {
                'pnl_history': pnl_history
            },
            'parameters': status.get('parameters', {})
        }

        # Handle CORS for web frontend
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }

        return func.HttpResponse(
            json.dumps(dashboard_data, default=str),
            status_code=200,
            headers=headers
        )

    except Exception as e:
        logging.error(f'Dashboard function error: {e}')

        error_response = {
            'status': 'error',
            'message': str(e),
            'timestamp': str(datetime.now())
        }

        return func.HttpResponse(
            json.dumps(error_response),
            status_code=500,
            headers={
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
        )