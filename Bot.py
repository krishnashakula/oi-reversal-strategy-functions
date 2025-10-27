import requests
import time
import logging
import json
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np

# Configure logging for production level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('realtime_feed.log'),
        logging.StreamHandler()
    ]
)

# Set specific log levels for noisy modules
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

def sanitize_log_message(message):
    """Remove potentially harmful content from log messages"""
    if not isinstance(message, str):
        return str(message)
    
    # Remove script tags and their content
    import re
    message = re.sub(r'<script[^>]*>.*?</script>', '[SCRIPT REMOVED]', message, flags=re.DOTALL | re.IGNORECASE)
    message = re.sub(r'<script[^>]*>', '[SCRIPT TAG REMOVED]', message, flags=re.IGNORECASE)
    
    # Truncate very long messages
    if len(message) > 1000:
        message = message[:1000] + "... [TRUNCATED]"
    
    return message

class StreetSmartTradingEngine:
    def __init__(self, symbols=None, poll_interval=30):
        self.symbols = symbols or ['RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'NIFTY.NS']
        self.poll_interval = poll_interval
        self.session = requests.Session()
        
        # Enhanced headers to mimic browser behavior more closely
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.nseindia.com/'
        })
        
        # Initialize session with NSE with better error handling
        self._initialize_session()
        
        # Risk management parameters
        self.max_risk_per_trade = 0.02  # 2% of capital
        self.min_reward_ratio = 1.5     # Minimum 1.5:1 reward-to-risk
        self.max_position_size = 0.1    # Max 10% of capital per position

    def _initialize_session(self):
        """Initialize NSE session with proper authentication flow"""
        try:
            # First visit to main page
            logging.info("Initializing NSE session...")
            response = self.session.get('https://www.nseindia.com', timeout=15)
            if response.status_code != 200:
                logging.warning(f"Failed to initialize NSE session: {response.status_code}")
                return
            
            # Extract and set cookies
            cookies = response.cookies
            if cookies:
                logging.debug(f"Session initialized with {len(cookies)} cookies")
            
            # Wait a bit for session to establish
            time.sleep(2)
            
            # Visit option chain page to set additional cookies
            option_chain_url = 'https://www.nseindia.com/option-chain'
            response2 = self.session.get(option_chain_url, timeout=15)
            if response2.status_code == 200:
                logging.info("NSE session initialized successfully")
                # Store additional cookies from option chain page
                if response2.cookies:
                    logging.debug(f"Additional cookies from option-chain: {len(response2.cookies)}")
            else:
                logging.warning(f"Failed to access option chain page: {response2.status_code}")
                
        except Exception as e:
            logging.error(f"Error initializing NSE session: {e}")

    def _refresh_session_if_needed(self, response):
        """Refresh session if we get authentication errors"""
        if response.status_code in [401, 403]:
            logging.info("Authentication error detected, refreshing session...")
            self._initialize_session()
            return True
        return False

    def _get_api_url(self, symbol):
        """Get the appropriate API URL for the symbol type"""
        symbol_clean = symbol.replace('.NS', '')
        
        # Check if it's an index
        indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
        if any(index in symbol_clean.upper() for index in indices):
            # Index options chain
            return f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol_clean.upper()}'
        else:
            # Equity options chain
            return f'https://www.nseindia.com/api/option-chain-equities?symbol={symbol_clean.upper()}'

    def _try_alternative_approach(self, symbol):
        """Try alternative approach for stubborn symbols"""
        logging.info(f"Trying alternative approach for {symbol}")
        
        try:
            symbol_clean = symbol.replace('.NS', '')
            
            # For indices, try a different approach
            if 'NIFTY' in symbol_clean.upper():
                # Try the main indices page first
                self.session.get('https://www.nseindia.com/market-data/live-equity-market', timeout=10)
                time.sleep(1)
                
                # Try different index URLs
                index_urls = [
                    f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol_clean.upper()}',
                    f'https://www.nseindia.com/api/liveEquity-derivatives?symbol={symbol_clean.upper()}'
                ]
                
                for url in index_urls:
                    try:
                        response = self.session.get(url, timeout=15)
                        if response.status_code == 200:
                            data = response.json()
                            logging.info(f"Alternative approach succeeded for {symbol} with URL: {url}")
                            return data
                    except:
                        continue
            else:
                # For equities, try visiting multiple pages to establish session
                pages_to_visit = [
                    'https://www.nseindia.com/market-data/live-equity-market',
                    f'https://www.nseindia.com/get-quotes/equity?symbol={symbol_clean}',
                    'https://www.nseindia.com/option-chain'
                ]
                
                for page in pages_to_visit:
                    try:
                        self.session.get(page, timeout=10)
                        time.sleep(1)
                    except:
                        continue
                
                # Try the equity API with different headers
                url = f'https://www.nseindia.com/api/option-chain-equities?symbol={symbol_clean.upper()}'
                headers = self.session.headers.copy()
                headers.update({
                    'Referer': f'https://www.nseindia.com/get-quotes/equity?symbol={symbol_clean}',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/plain, */*'
                })
                
                response = self.session.get(url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        logging.info(f"Alternative approach succeeded for {symbol}")
                        return data
                    except ValueError:
                        pass
                        
        except Exception as e:
            logging.debug(f"Alternative approach failed for {symbol}: {e}")
            
        return None

    def _is_html_response(self, response):
        """Check if response contains HTML content"""
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            return True
        if response.text and response.text.strip().startswith('<'):
            return True
        return False

    def _log_safe_error(self, symbol, response):
        """Log error response safely without exposing HTML/tracking content"""
        if self._is_html_response(response):
            logging.warning(f"NSE returned HTML error page for {symbol} (status: {response.status_code})")
            # Extract title if possible for better error info
            if '<title>' in response.text and '</title>' in response.text:
                title_start = response.text.find('<title>') + 7
                title_end = response.text.find('</title>')
                if title_end > title_start:
                    title = response.text[title_start:title_end].strip()
                    logging.debug(f"HTML error title for {symbol}: {sanitize_log_message(title)}")
        else:
            # Safe to log non-HTML responses
            error_preview = response.text[:100] + "..." if len(response.text) > 100 else response.text
            logging.error(f"API error for {symbol}: {response.status_code} - {sanitize_log_message(error_preview)}")

        return None

    def fetch_options_chain(self, symbol):
        """Fetch options chain data for a symbol using NSE API with enhanced authentication handling"""
        url = self._get_api_url(symbol)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Add symbol-specific headers and referer
                headers = self.session.headers.copy()
                symbol_clean = symbol.replace('.NS', '')
                headers['Referer'] = f'https://www.nseindia.com/get-quotes/equity?symbol={symbol_clean}'
                
                response = self.session.get(url, headers=headers, timeout=20)
                
                # Handle authentication errors with session refresh
                if response.status_code in [401, 403]:
                    if attempt < max_retries - 1:  # Don't refresh on last attempt
                        logging.warning(f"Authentication failed for {symbol}, refreshing session (attempt {attempt + 1}/{max_retries})")
                        self._refresh_session_if_needed(response)
                        time.sleep(3)  # Wait longer after session refresh
                        continue
                    else:
                        logging.error(f"Authentication failed for {symbol} after {max_retries} attempts")
                        # Try alternative approach as last resort
                        alt_data = self._try_alternative_approach(symbol)
                        if alt_data:
                            return alt_data
                        return None
                
                if response.status_code == 200:
                    # Check if response is actually JSON
                    try:
                        # Handle compressed responses (brotli, gzip, etc.)
                        content_encoding = response.headers.get('content-encoding', '').lower()
                        if content_encoding == 'br':
                            # Manual brotli decompression if needed
                            try:
                                import brotli
                                # Get raw response for manual decompression
                                raw_response = self.session.get(url, headers=headers, timeout=20, stream=True)
                                raw_content = raw_response.raw.read()
                                decompressed = brotli.decompress(raw_content)
                                data = json.loads(decompressed.decode('utf-8'))
                            except ImportError:
                                # If brotli not available, try normal JSON (requests may auto-decompress)
                                data = response.json()
                            except Exception:
                                # Fallback to normal JSON parsing
                                data = response.json()
                        elif 'gzip' in content_encoding or response.content.startswith(b'\x1f\x8b'):
                            # Handle gzip compression
                            import gzip
                            decompressed = gzip.decompress(response.content)
                            data = json.loads(decompressed.decode('utf-8'))
                        else:
                            data = response.json()
                        logging.info(f"Successfully fetched options chain for {symbol}")
                        return data
                    except ValueError as e:
                        # Response is not JSON, might be HTML error page
                        if self._is_html_response(response):
                            logging.warning(f"NSE returned HTML error page for {symbol} (status: {response.status_code})")
                            if attempt < max_retries - 1:
                                logging.info(f"Retrying {symbol} after HTML error...")
                                time.sleep(2)
                                continue
                            # Try alternative approach for HTML errors too
                            alt_data = self._try_alternative_approach(symbol)
                            if alt_data:
                                return alt_data
                        else:
                            logging.error(f"Invalid JSON response for {symbol}: {e}")
                            return None
                else:
                    # Handle other error status codes
                    if response.status_code == 404:
                        logging.warning(f"Symbol {symbol} not found or not available")
                    elif response.status_code >= 500:
                        logging.warning(f"NSE server error for {symbol} (status: {response.status_code})")
                        if attempt < max_retries - 1:
                            logging.info(f"Retrying {symbol} after server error...")
                            time.sleep(2)
                            continue
                    else:
                        logging.error(f"Failed to fetch {symbol}: HTTP {response.status_code}")
                    
                    # Log error safely
                    self._log_safe_error(symbol, response)
                    return None
                    
            except requests.exceptions.Timeout:
                logging.warning(f"Timeout fetching data for {symbol} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
                return None
            except requests.exceptions.ConnectionError:
                logging.warning(f"Connection error for {symbol} (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(3)
                    continue
                return None
            except Exception as e:
                logging.error(f"Unexpected error fetching {symbol}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
        
        # Final fallback: try alternative approach
        logging.info(f"All retries failed for {symbol}, trying alternative approach...")
        alt_data = self._try_alternative_approach(symbol)
        if alt_data:
            return alt_data
            
        return None

    def calculate_market_sentiment(self, strikes_data, spot_price):
        """Calculate overall market sentiment from OI distribution"""
        if not strikes_data:
            return {'sentiment': 'NEUTRAL', 'score': 50, 'confidence': 0}

        total_call_oi = sum(s['call_oi'] for s in strikes_data)
        total_put_oi = sum(s['put_oi'] for s in strikes_data)
        
        if total_call_oi + total_put_oi == 0:
            return {'sentiment': 'NEUTRAL', 'score': 50, 'confidence': 0}

        put_call_ratio = total_put_oi / total_call_oi
        
        # Sentiment scoring
        if put_call_ratio > 1.2:
            sentiment = 'BEARISH'
            score = min(100, 50 + (put_call_ratio - 1) * 25)
        elif put_call_ratio < 0.8:
            sentiment = 'BULLISH'
            score = max(0, 50 - (1/put_call_ratio - 1) * 25)
        else:
            sentiment = 'NEUTRAL'
            score = 50

        # Confidence based on OI volume
        total_oi = total_call_oi + total_put_oi
        confidence = min(100, total_oi / 1000000 * 100)  # Scale confidence by OI volume

        return {
            'sentiment': sentiment,
            'score': round(score, 1),
            'confidence': round(confidence, 1),
            'put_call_ratio': round(put_call_ratio, 2)
        }

    def calculate_volatility(self, strikes_data, spot_price):
        """Calculate implied volatility from option chain"""
        if not strikes_data:
            return {'iv': 0, 'volatility_regime': 'LOW'}

        # Calculate straddle prices and implied volatility
        atm_strikes = [s for s in strikes_data if abs(s['strike'] - spot_price) < spot_price * 0.02]
        
        if not atm_strikes:
            return {'iv': 0, 'volatility_regime': 'UNKNOWN'}

        avg_call_oi = np.mean([s['call_oi'] for s in atm_strikes])
        avg_put_oi = np.mean([s['put_oi'] for s in atm_strikes])
        
        # Simple volatility proxy based on OI concentration
        oi_concentration = min(avg_call_oi, avg_put_oi) / max(avg_call_oi, avg_put_oi) if max(avg_call_oi, avg_put_oi) > 0 else 0
        
        if oi_concentration > 0.7:
            volatility_regime = 'HIGH'
            iv = 25 + oi_concentration * 15
        elif oi_concentration > 0.4:
            volatility_regime = 'MEDIUM'
            iv = 15 + oi_concentration * 10
        else:
            volatility_regime = 'LOW'
            iv = 5 + oi_concentration * 10

        return {
            'iv': round(iv, 1),
            'volatility_regime': volatility_regime,
            'oi_concentration': round(oi_concentration, 2)
        }

    def generate_trading_decision(self, signals, sentiment, volatility, spot_price):
        """Generate actionable trading decision with risk management"""
        if not signals:
            return {
                'action': 'HOLD',
                'confidence': 60,
                'reason': 'No strong signals detected',
                'risk_level': 'LOW',
                'position_size': 0,
                'stop_loss': None,
                'target': None
            }

        # Prioritize strongest signal
        best_signal = max(signals, key=lambda x: x['confidence'])
        
        # Risk assessment
        risk_multiplier = 1.0
        if volatility['volatility_regime'] == 'HIGH':
            risk_multiplier = 0.7
        elif sentiment['sentiment'] == best_signal['type']:
            risk_multiplier = 1.2  # Sentiment confirmation

        # Position sizing based on confidence and risk
        confidence_factor = best_signal['confidence'] / 100
        position_size_pct = min(self.max_position_size, self.max_risk_per_trade * confidence_factor * risk_multiplier)
        
        # Stop loss and target calculation
        if best_signal['type'] == 'CALL':
            stop_loss = spot_price * 0.97  # 3% stop loss
            target = spot_price * 1.06     # 6% target
            risk_amount = spot_price - stop_loss
            reward_amount = target - spot_price
        else:  # PUT
            stop_loss = spot_price * 1.03  # 3% stop loss
            target = spot_price * 0.94     # 6% target
            risk_amount = stop_loss - spot_price
            reward_amount = spot_price - target

        reward_risk_ratio = reward_amount / risk_amount if risk_amount > 0 else 0

        # Decision logic
        if best_signal['confidence'] >= 80 and reward_risk_ratio >= self.min_reward_ratio:
            action = 'BUY' if best_signal['type'] == 'CALL' else 'SELL'
            risk_level = 'MEDIUM' if position_size_pct > 0.05 else 'LOW'
        elif best_signal['confidence'] >= 70:
            action = 'WATCH'
            risk_level = 'LOW'
            position_size_pct = 0
        else:
            action = 'HOLD'
            risk_level = 'LOW'
            position_size_pct = 0

        return {
            'action': action,
            'confidence': best_signal['confidence'],
            'reason': f"Strong {best_signal['type']} signal at ₹{best_signal['strike']} with OI ratio {best_signal['oi_ratio']}",
            'risk_level': risk_level,
            'position_size': round(position_size_pct * 100, 1),
            'stop_loss': round(stop_loss, 2),
            'target': round(target, 2),
            'reward_risk_ratio': round(reward_risk_ratio, 1),
            'signal_type': best_signal['type'],
            'strike_price': best_signal['strike']
        }

    def process_options_data(self, data, symbol):
        """Process and analyze options chain data with street smart logic"""
        if not data or 'records' not in data or 'data' not in data['records']:
            logging.warning(f"No data to process for {symbol}")
            return None

        processed_data = []
        signals = []
        spot_price = data['records'].get('underlyingValue', 0)

        for strike_data in data['records']['data']:
            try:
                strike = strike_data.get('strikePrice', 0)
                ce = strike_data.get('CE', {})
                pe = strike_data.get('PE', {})
                
                call_oi = ce.get('openInterest', 0)
                put_oi = pe.get('openInterest', 0)
                call_volume = ce.get('totalTradedVolume', 0)
                put_volume = pe.get('totalTradedVolume', 0)

                if call_oi + put_oi == 0:
                    continue

                oi_ratio = put_oi / call_oi if call_oi > 0 else 0

                record = {
                    'strike': strike,
                    'call_oi': call_oi,
                    'put_oi': put_oi,
                    'oi_ratio': round(oi_ratio, 2),
                    'call_volume': call_volume,
                    'put_volume': put_volume,
                    'spot_price': spot_price,
                    'timestamp': datetime.now().isoformat()
                }

                # Enhanced signal detection with multiple criteria - ATM within 6 strikes only
                strike_distance_points = abs(strike - spot_price)
                max_strikes_away = 6 * 50  # 6 strikes * 50 points per strike for NIFTY
                is_atm_strike = strike_distance_points <= max_strikes_away
                
                # Only process strikes within ATM range
                if is_atm_strike:
                    processed_data.append(record)
                
                if is_atm_strike:  # Within 6 strikes of ATM
                    if oi_ratio > 2.5:  # Strong bearish
                        signals.append({
                            'type': 'PUT',
                            'strike': strike,
                            'signal': 'STRONG BEARISH REVERSAL',
                            'oi_ratio': oi_ratio,
                            'confidence': min(95, 70 + (oi_ratio - 2.5) * 10),
                            'strength': 'VERY_STRONG'
                        })
                    elif oi_ratio > 2.0:  # Moderate bearish
                        signals.append({
                            'type': 'PUT',
                            'strike': strike,
                            'signal': 'BEARISH REVERSAL',
                            'oi_ratio': oi_ratio,
                            'confidence': min(85, 60 + (oi_ratio - 2) * 12),
                            'strength': 'STRONG'
                        })
                    elif oi_ratio < 0.4:  # Strong bullish
                        signals.append({
                            'type': 'CALL',
                            'strike': strike,
                            'signal': 'STRONG BULLISH REVERSAL',
                            'oi_ratio': oi_ratio,
                            'confidence': min(95, 70 + (1/oi_ratio - 2.5) * 10) if oi_ratio > 0 else 95,
                            'strength': 'VERY_STRONG'
                        })
                    elif oi_ratio < 0.5:  # Moderate bullish
                        signals.append({
                            'type': 'CALL',
                            'strike': strike,
                            'signal': 'BULLISH REVERSAL',
                            'oi_ratio': oi_ratio,
                            'confidence': min(85, 60 + (1/oi_ratio - 2) * 12) if oi_ratio > 0 else 85,
                            'strength': 'STRONG'
                        })

            except Exception as e:
                logging.error(f"Error processing strike data for {symbol}: {e}")
                continue

        # Sort and limit data
        processed_data = sorted(processed_data, key=lambda x: x['strike'])
        
        # Calculate market analytics
        sentiment = self.calculate_market_sentiment(processed_data, spot_price)
        volatility = self.calculate_volatility(processed_data, spot_price)
        
        # Generate trading decision
        trading_decision = self.generate_trading_decision(signals, sentiment, volatility, spot_price)

        return {
            'symbol': symbol,
            'data': processed_data[:20],  # Top 20 strikes within 6 strikes of ATM
            'signals': signals,
            'sentiment': sentiment,
            'volatility': volatility,
            'trading_decision': trading_decision,
            'spot_price': spot_price,
            'timestamp': datetime.now().isoformat()
        }

    def fetch_all_data(self):
        """Fetch and process data for all symbols"""
        all_data = []
        for symbol in self.symbols:
            logging.info(f"Fetching data for {symbol}")
            raw_data = self.fetch_options_chain(symbol)
            if raw_data:
                processed_data = self.process_options_data(raw_data, symbol)
                if processed_data:
                    all_data.append(processed_data)
            time.sleep(2)  # Rate limiting
        return all_data

def create_decision_gauge(decision):
    """Create a gauge chart for trading decision confidence"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=decision['confidence'],
        title={'text': f"{decision['action']} Confidence"},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 40], 'color': "lightgray"},
                {'range': [40, 70], 'color': "yellow"},
                {'range': [70, 100], 'color': "green"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 80
            }
        }
    ))
    fig.update_layout(height=200)
    return fig

def create_sentiment_chart(sentiment):
    """Create sentiment visualization"""
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=sentiment['score'],
        title={'text': f"Market Sentiment: {sentiment['sentiment']}"},
        delta={'reference': 50},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 40], 'color': "red"},
                {'range': [40, 60], 'color': "yellow"},
                {'range': [60, 100], 'color': "green"}
            ]
        }
    ))
    fig.update_layout(height=200)
    return fig

if __name__ == "__main__":
    st.set_page_config(
        page_title="Street Smart OI Trading Dashboard",
        page_icon="🎯",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Enhanced CSS for professional trading dashboard
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(45deg, #1e3c72, #2a5298);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 1rem;
    }
    .decision-card {
        background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
        border-radius: 15px;
        padding: 1.5rem;
        color: white;
        text-align: center;
        box-shadow: 0 8px 16px rgba(0, 0, 0, 0.2);
        margin: 1rem 0;
    }
    .decision-card.hold {
        background: linear-gradient(135deg, #ff9800 0%, #f57c00 100%);
    }
    .decision-card.sell {
        background: linear-gradient(135deg, #f44336 0%, #d32f2f 100%);
    }
    .signal-alert {
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
        font-weight: bold;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .bullish { background: linear-gradient(135deg, #4CAF50, #45a049); color: white; }
    .bearish { background: linear-gradient(135deg, #f44336, #d32f2f); color: white; }
    .watch { background: linear-gradient(135deg, #ff9800, #f57c00); color: white; }
    .metric-box {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        border-left: 4px solid #007bff;
    }
    .risk-high { border-left-color: #dc3545; }
    .risk-medium { border-left-color: #ffc107; }
    .risk-low { border-left-color: #28a745; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<h1 class="main-header">🎯 Street Smart OI Trading Dashboard</h1>', unsafe_allow_html=True)
    st.markdown("**Actionable Trading Decisions • Risk Management • Market Intelligence**")

    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Trading Controls")
        
        selected_symbols = st.multiselect(
            "Select Symbols",
            ['RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'NIFTY.NS'],
            default=['RELIANCE.NS', 'TCS.NS', 'NIFTY.NS']
        )
        
        risk_tolerance = st.selectbox(
            "Risk Tolerance",
            ["Conservative", "Moderate", "Aggressive"],
            index=1
        )
        
        debug_mode = st.checkbox("Debug Mode (show detailed errors)", value=False)
        
        refresh_rate = st.slider("Refresh Rate (seconds)", 10, 300, 30)
        
        st.markdown("---")
        st.markdown("### 📊 Decision Framework")
        st.info("**Street Smart Logic:**\n- OI Ratio > 2.5: Strong Reversal\n- Risk/Reward > 1.5: Tradeable\n- Confidence > 80%: Execute\n- Position Size: Risk-based\n- **ATM Focus: Within 6 strikes only**")
        
        if st.button("🔄 Manual Refresh"):
            st.rerun()

    # Initialize trading engine
    engine = StreetSmartTradingEngine(symbols=selected_symbols, poll_interval=refresh_rate)
    
    # Adjust logging level based on debug mode
    if debug_mode:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.info("Debug mode enabled - showing detailed error information")
    else:
        logging.getLogger().setLevel(logging.INFO)
    
    # Adjust risk parameters based on tolerance
    if risk_tolerance == "Conservative":
        engine.max_risk_per_trade = 0.01
        engine.min_reward_ratio = 2.0
    elif risk_tolerance == "Aggressive":
        engine.max_risk_per_trade = 0.03
        engine.min_reward_ratio = 1.2

    # Main dashboard
    placeholder = st.empty()

    while True:
        with st.spinner('Analyzing market data for trading decisions...'):
            data = engine.fetch_all_data()

        with placeholder.container():
            if data:
                # Overall market summary
                total_buy_signals = sum(1 for d in data if d.get('trading_decision', {}).get('action') == 'BUY')
                total_sell_signals = sum(1 for d in data if d.get('trading_decision', {}).get('action') == 'SELL')
                avg_confidence = np.mean([d.get('trading_decision', {}).get('confidence', 0) for d in data])
                
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Buy Signals", total_buy_signals)
                with col2:
                    st.metric("Sell Signals", total_sell_signals)
                with col3:
                    st.metric("Avg Confidence", f"{avg_confidence:.1f}%")
                with col4:
                    st.metric("Last Update", datetime.now().strftime("%H:%M:%S"))

                st.markdown("---")

                # Individual symbol analysis
                for symbol_data in data:
                    symbol = symbol_data['symbol']
                    decision = symbol_data.get('trading_decision', {})
                    sentiment = symbol_data.get('sentiment', {})
                    volatility = symbol_data.get('volatility', {})
                    signals = symbol_data.get('signals', [])

                    with st.expander(f"🎯 {symbol} Trading Decision", expanded=True):
                        # Primary Decision Card
                        decision_class = decision.get('action', 'HOLD').lower()
                        st.markdown(f"""
                        <div class="decision-card {decision_class}">
                            <h2 style="margin: 0; font-size: 2rem;">{decision.get('action', 'HOLD')}</h2>
                            <p style="margin: 0.5rem 0; font-size: 1.1rem;">{decision.get('reason', 'No clear signal')}</p>
                            <p style="margin: 0; font-size: 0.9rem;">Confidence: {decision.get('confidence', 0)}% | Risk: {decision.get('risk_level', 'LOW')}</p>
                        </div>
                        """, unsafe_allow_html=True)

                        # Key metrics in columns
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("Spot Price", f"₹{symbol_data.get('spot_price', 0):.2f}")
                        with col2:
                            st.metric("Position Size", f"{decision.get('position_size', 0)}%")
                        with col3:
                            st.metric("Stop Loss", f"₹{decision.get('stop_loss', 0):.2f}" if decision.get('stop_loss') else "N/A")
                        with col4:
                            st.metric("Target", f"₹{decision.get('target', 0):.2f}" if decision.get('target') else "N/A")

                        # Risk/Reward Analysis
                        if decision.get('reward_risk_ratio', 0) > 0:
                            st.markdown("### 📊 Risk/Reward Analysis")
                            rr_col1, rr_col2, rr_col3 = st.columns(3)
                            with rr_col1:
                                st.metric("Risk/Reward Ratio", f"{decision.get('reward_risk_ratio', 0):.1f}:1")
                            with rr_col2:
                                st.metric("Volatility", f"{volatility.get('iv', 0)}% ({volatility.get('volatility_regime', 'LOW')})")
                            with rr_col3:
                                st.metric("Market Sentiment", f"{sentiment.get('sentiment', 'NEUTRAL')} ({sentiment.get('score', 50)}%)")

                        # Charts section
                        st.markdown("### 📈 Market Analysis")
                        chart_col1, chart_col2 = st.columns(2)
                        with chart_col1:
                            st.plotly_chart(create_decision_gauge(decision), use_container_width=True, key=f"decision_gauge_{symbol}")
                        with chart_col2:
                            st.plotly_chart(create_sentiment_chart(sentiment), use_container_width=True, key=f"sentiment_chart_{symbol}")

                        # Active signals
                        if signals:
                            st.markdown("### 🚨 Active Signals")
                            for sig in signals[:3]:  # Show top 3 signals
                                signal_class = "bullish" if sig['type'] == 'CALL' else "bearish"
                                st.markdown(f"""
                                <div class="signal-alert {signal_class}">
                                    <strong>{sig['signal']}</strong> at ₹{sig['strike']} | OI Ratio: {sig['oi_ratio']} | Confidence: {sig['confidence']}%
                                </div>
                                """, unsafe_allow_html=True)

                        # Quick action buttons
                        st.markdown("### ⚡ Quick Actions")
                        action_col1, action_col2, action_col3 = st.columns(3)
                        with action_col1:
                            if st.button(f"📱 Set Alert for {symbol}", key=f"alert_{symbol}"):
                                st.success(f"Alert set for {symbol} at ₹{decision.get('strike_price', symbol_data.get('spot_price', 0))}")
                        with action_col2:
                            if st.button(f"📊 View Chart", key=f"chart_{symbol}"):
                                st.info(f"Opening detailed chart for {symbol}...")
                        with action_col3:
                            if st.button(f"📋 Add to Watchlist", key=f"watch_{symbol}"):
                                st.success(f"Added {symbol} to watchlist")

                        st.caption(f"Analysis updated: {symbol_data['timestamp']}")
            else:
                st.error("❌ Failed to fetch market data. Please check your internet connection and try again.")
                st.info("💡 If issues persist, the NSE API may be temporarily unavailable during market hours.")
                
                # Show debug info if enabled
                if debug_mode:
                    st.markdown("### 🔍 Debug Information")
                    st.warning("**Recent API Issues Detected:**")
                    st.info("- NSE may be returning HTML error pages instead of JSON")
                    st.info("- This often happens during high volatility or server maintenance")
                    st.info("- Check the log file 'realtime_feed.log' for detailed error information")
                    st.info("- Try reducing refresh rate or switching to different symbols")
                    
                    # Show authentication status
                    st.markdown("#### 🔐 Authentication Status")
                    try:
                        # Test session with a simple request
                        test_response = engine.session.get('https://www.nseindia.com', timeout=5)
                        if test_response.status_code == 200:
                            st.success("✅ NSE Session Active")
                        else:
                            st.error(f"❌ NSE Session Issue (Status: {test_response.status_code})")
                    except Exception:
                        st.error("❌ Cannot connect to NSE")

        time.sleep(refresh_rate)
        st.rerun()