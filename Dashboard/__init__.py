import logging
import json
import azure.functions as func
from datetime import datetime

def main(req: func.HttpRequest) -> func.HttpResponse:
    """Dashboard HTTP Function - Returns basic status"""

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
        # Simple test response
        dashboard_data = {
            'status': 'success',
            'message': 'OI Reversal Strategy Dashboard API',
            'timestamp': str(datetime.now()),
            'version': '1.0.0',
            'functions': ['dashboard', 'manual', 'strategy-runner']
        }

        # Handle CORS for web frontend
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }

        return func.HttpResponse(
            json.dumps(dashboard_data),
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