import logging
import json
import azure.functions as func
from datetime import datetime
from trading_database import TradingDatabase
from oi_reversal_strategy import OIReversalStrategy
from Bot import StreetSmartTradingEngine

def main(req: func.HttpRequest) -> func.HttpResponse:
    """Manual trigger HTTP function for manual operations"""

    logging.info('ManualTrigger function triggered')

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
        # Get action from route
        action = req.route_params.get('action', 'status')

        # Initialize components
        db = TradingDatabase()
        strategy = OIReversalStrategy(db)

        response_data = {'status': 'success', 'action': action, 'timestamp': str(datetime.now())}

        if action == 'cycle':
            # Run single strategy cycle
            symbols = req.params.get('symbols', 'NIFTY.NS').split(',')

            engine = StreetSmartTradingEngine(symbols=symbols, poll_interval=30)
            market_data_list = engine.fetch_all_data()

            total_signals = 0
            total_positions = 0

            for market_data in market_data_list:
                results = strategy.run_strategy_cycle(market_data)
                total_signals += results.get('signals_detected', 0)
                total_positions += results.get('positions_opened', 0)

            response_data.update({
                'signals_detected': total_signals,
                'positions_opened': total_positions,
                'symbols_processed': len(market_data_list)
            })

        elif action == 'status':
            # Get strategy status
            status = strategy.get_strategy_status()
            response_data['strategy_status'] = status

        elif action == 'parameters':
            # Get or update parameters
            if req.method == 'POST':
                # Update parameters
                req_body = req.get_json()
                for param_name, param_value in req_body.items():
                    db.update_strategy_parameter(param_name, str(param_value))
                response_data['message'] = 'Parameters updated successfully'
            else:
                # Get parameters
                params = strategy.get_strategy_parameters()
                response_data['parameters'] = params

        elif action == 'reset':
            # Reset strategy (clear positions, etc.)
            # Note: This is a dangerous operation, should be protected
            logging.warning('Strategy reset requested')
            response_data['message'] = 'Reset functionality not implemented yet'

        else:
            response_data = {
                'status': 'error',
                'message': f'Unknown action: {action}',
                'available_actions': ['cycle', 'status', 'parameters', 'reset']
            }

        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }

        return func.HttpResponse(
            json.dumps(response_data, default=str),
            status_code=200,
            headers=headers
        )

    except Exception as e:
        logging.error(f'ManualTrigger function error: {e}')

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