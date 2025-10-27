import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
from trading_database import TradingDatabase

class OIReversalStrategy:
    """
    OI Reversal Strategy Implementation

    Strategy Rules:
    - Entry: Call OI > 2x Put OI at same strike (extreme retail concentration)
    - Action: Take opposite side (if Call OI extreme, go SHORT/PUT)
    - Exit: When OI normalizes (ratio returns to normal) OR 15% profit target
    - Target Win Rate: 88%
    """

    def __init__(self, db: TradingDatabase, capital: float = 100000):
        self.db = db
        self.capital = capital
        self.params = self.db.get_strategy_parameters()

        # Strategy parameters
        self.oi_ratio_threshold = self.params.get('oi_ratio_threshold', 2.0)
        self.profit_target_pct = self.params.get('profit_target_pct', 15.0)
        self.max_risk_per_trade = self.params.get('max_risk_per_trade', 2.0)
        self.atm_strikes_limit = int(self.params.get('atm_strikes_limit', 6))
        self.min_confidence = self.params.get('min_confidence', 70.0)
        self.oi_normalization_threshold = self.params.get('oi_normalization_threshold', 1.5)

        logging.info(f"OI Reversal Strategy initialized with parameters: {self.params}")

    def detect_extreme_oi_concentration(self, strikes_data: List[Dict], spot_price: float) -> List[Dict]:
        """
        Detect extreme OI concentration signals

        Entry Trigger: Call OI > 2x Put OI at same strike
        This indicates extreme retail concentration on calls, suggesting reversal to puts
        """
        signals = []

        # Focus on ATM strikes only (within 6 strikes)
        strike_interval = 50  # Assuming 50 point intervals for NIFTY
        max_distance = self.atm_strikes_limit * strike_interval

        atm_strikes = [
            strike for strike in strikes_data
            if abs(strike['strike'] - spot_price) <= max_distance
        ]

        for strike in atm_strikes:
            call_oi = strike.get('call_oi', 0)
            put_oi = strike.get('put_oi', 0)

            if call_oi == 0:
                continue

            oi_ratio = put_oi / call_oi

            # Entry condition: Call OI > 2x Put OI (extreme call concentration)
            if oi_ratio < (1 / self.oi_ratio_threshold):  # oi_ratio < 0.5 when threshold = 2.0
                confidence = self._calculate_signal_confidence(strike, spot_price, oi_ratio)

                if confidence >= self.min_confidence:
                    signal = {
                        'type': 'PUT',  # Opposite side of extreme concentration
                        'strike': strike['strike'],
                        'entry_trigger': 'OI_RATIO_2X',
                        'confidence': confidence,
                        'oi_ratio': oi_ratio,
                        'call_oi': call_oi,
                        'put_oi': put_oi,
                        'spot_price': spot_price,
                        'signal_strength': self._classify_signal_strength(oi_ratio),
                        'expected_win_rate': 88.0  # Target win rate
                    }
                    signals.append(signal)

            # Also check for extreme put concentration (Put OI > 2x Call OI)
            elif oi_ratio > self.oi_ratio_threshold:
                confidence = self._calculate_signal_confidence(strike, spot_price, oi_ratio)

                if confidence >= self.min_confidence:
                    signal = {
                        'type': 'CALL',  # Opposite side of extreme concentration
                        'strike': strike['strike'],
                        'entry_trigger': 'OI_RATIO_2X',
                        'confidence': confidence,
                        'oi_ratio': oi_ratio,
                        'call_oi': call_oi,
                        'put_oi': put_oi,
                        'spot_price': spot_price,
                        'signal_strength': self._classify_signal_strength(1/oi_ratio),  # Inverse for puts
                        'expected_win_rate': 88.0
                    }
                    signals.append(signal)

        return signals

    def _calculate_signal_confidence(self, strike: Dict, spot_price: float, oi_ratio: float) -> float:
        """Calculate confidence score for the signal"""
        base_confidence = 60.0

        # Distance from ATM (closer = higher confidence)
        distance_from_spot = abs(strike['strike'] - spot_price)
        atm_factor = max(0, 1 - (distance_from_spot / (self.atm_strikes_limit * 50)))
        base_confidence += atm_factor * 20

        # OI ratio extremity (more extreme = higher confidence)
        if oi_ratio < 0.5:  # Call OI > 2x Put OI
            extremity_factor = min(1.0, (1 / oi_ratio) / self.oi_ratio_threshold)
        else:  # Put OI > 2x Call OI
            extremity_factor = min(1.0, oi_ratio / self.oi_ratio_threshold)

        base_confidence += extremity_factor * 20

        # Volume confirmation (higher volume = higher confidence)
        total_volume = strike.get('call_volume', 0) + strike.get('put_volume', 0)
        volume_factor = min(1.0, total_volume / 10000)  # Normalize by 10k volume
        base_confidence += volume_factor * 10

        return min(95.0, base_confidence)

    def _classify_signal_strength(self, oi_ratio: float) -> str:
        """Classify signal strength based on OI ratio extremity"""
        if oi_ratio <= 0.3:
            return 'VERY_STRONG'
        elif oi_ratio <= 0.4:
            return 'STRONG'
        elif oi_ratio <= 0.5:
            return 'MODERATE'
        else:
            return 'WEAK'

    def should_exit_position(self, position: Dict, current_market_data: Dict) -> Tuple[bool, str]:
        """
        Check if position should be exited

        Exit conditions:
        1. OI normalizes (ratio returns to normal levels)
        2. 15% profit target achieved
        3. Stop loss hit (if implemented)
        """
        symbol = position['symbol']
        position_type = position['position_type']
        entry_price = position['entry_price']
        current_spot = current_market_data.get('spot_price', 0)

        if not current_spot:
            return False, "No current market data"

        # Check profit target (15%)
        current_pnl_pct = self._calculate_current_pnl_pct(position, current_spot)

        if current_pnl_pct >= self.profit_target_pct:
            return True, f"Profit target hit ({current_pnl_pct:.1f}%)"

        # Check OI normalization
        strikes_data = current_market_data.get('strikes_data', [])
        strike_data = next((s for s in strikes_data if s['strike'] == position.get('strike_price')), None)

        if strike_data:
            call_oi = strike_data.get('call_oi', 0)
            put_oi = strike_data.get('put_oi', 0)

            if call_oi > 0:
                current_oi_ratio = put_oi / call_oi

                # OI has normalized if ratio is back to reasonable levels
                if position_type.upper() in ['SHORT_CALL', 'LONG_PUT']:
                    # We were betting on puts, check if call OI is no longer extreme
                    if current_oi_ratio >= self.oi_normalization_threshold:
                        return True, f"OI normalized (ratio: {current_oi_ratio:.2f})"
                elif position_type.upper() in ['LONG_CALL', 'SHORT_PUT']:
                    # We were betting on calls, check if put OI is no longer extreme
                    if current_oi_ratio <= (1 / self.oi_normalization_threshold):
                        return True, f"OI normalized (ratio: {current_oi_ratio:.2f})"

        # Check stop loss (if implemented)
        stop_loss = position.get('stop_loss')
        if stop_loss:
            if position_type.upper() in ['LONG_CALL', 'SHORT_PUT']:
                if current_spot <= stop_loss:
                    return True, f"Stop loss hit at {current_spot}"
            else:  # SHORT_CALL, LONG_PUT
                if current_spot >= stop_loss:
                    return True, f"Stop loss hit at {current_spot}"

        return False, "Hold position"

    def _calculate_current_pnl_pct(self, position: Dict, current_spot: float) -> float:
        """Calculate current P&L percentage"""
        entry_price = position['entry_price']
        position_type = position['position_type']

        if position_type.upper() in ['LONG_CALL', 'SHORT_PUT']:
            pnl_pct = ((current_spot - entry_price) / entry_price) * 100
        else:  # SHORT_CALL, LONG_PUT
            pnl_pct = ((entry_price - current_spot) / entry_price) * 100

        return pnl_pct

    def calculate_position_size(self, signal: Dict, spot_price: float) -> Tuple[int, float, float]:
        """
        Calculate position size based on risk management

        Returns: (quantity, stop_loss, target_price)
        """
        risk_amount = self.capital * (self.max_risk_per_trade / 100)

        # For options, risk is typically the premium paid
        # Using spot price as proxy for simplicity
        if signal['type'] == 'CALL':
            # Long call: risk is premium paid, target is 15% upside
            stop_loss = spot_price * 0.97  # 3% stop loss
            target_price = spot_price * 1.15  # 15% target
            quantity = max(1, int(risk_amount / (spot_price * 0.03)))  # Risk 3% of entry
        else:  # PUT
            # Long put: risk is premium paid, target is 15% downside
            stop_loss = spot_price * 1.03  # 3% stop loss
            target_price = spot_price * 0.85  # 15% target
            quantity = max(1, int(risk_amount / (spot_price * 0.03)))  # Risk 3% of entry

        return quantity, stop_loss, target_price

    def execute_signal(self, signal: Dict, market_data: Dict) -> Optional[int]:
        """
        Execute a trading signal

        Returns position_id if successful, None otherwise
        """
        try:
            symbol = signal.get('symbol', 'UNKNOWN')
            spot_price = market_data.get('spot_price', 0)

            if not spot_price:
                logging.error(f"No spot price available for {symbol}")
                return None

            # Save signal to database
            signal_id = self.db.save_trading_signal(
                symbol=symbol,
                signal_type=signal['type'],
                strike_price=signal['strike'],
                entry_trigger=signal['entry_trigger'],
                confidence=signal['confidence'],
                oi_ratio=signal['oi_ratio'],
                market_sentiment=market_data.get('sentiment', {}).get('sentiment', 'NEUTRAL'),
                volatility_regime=market_data.get('volatility', {}).get('volatility_regime', 'MEDIUM')
            )

            # Calculate position size
            quantity, stop_loss, target_price = self.calculate_position_size(signal, spot_price)

            # Determine position type
            if signal['type'] == 'CALL':
                position_type = 'LONG_CALL'
                entry_price = spot_price  # Using spot as proxy
            else:
                position_type = 'LONG_PUT'
                entry_price = spot_price  # Using spot as proxy

            # Open position
            position_id = self.db.open_position(
                signal_id=signal_id,
                symbol=symbol,
                position_type=position_type,
                entry_price=entry_price,
                quantity=quantity,
                stop_loss=stop_loss,
                target_price=target_price
            )

            logging.info(f"Executed OI Reversal signal: {signal['type']} {symbol} at {signal['strike']} "
                        f"(Confidence: {signal['confidence']}%, OI Ratio: {signal['oi_ratio']:.2f})")

            return position_id

        except Exception as e:
            logging.error(f"Error executing signal: {e}")
            return None

    def monitor_and_exit_positions(self, current_market_data: Dict):
        """Monitor open positions and exit if conditions are met"""
        open_positions = self.db.get_open_positions()

        for position in open_positions:
            should_exit, exit_reason = self.should_exit_position(position, current_market_data)

            if should_exit:
                # Get current price (using spot price as proxy)
                exit_price = current_market_data.get('spot_price', position['entry_price'])

                # Close position
                success = self.db.close_position(position['id'], exit_price, exit_reason)

                if success:
                    logging.info(f"Closed position {position['id']} for {position['symbol']}: {exit_reason}")
                else:
                    logging.error(f"Failed to close position {position['id']}")

    def run_strategy_cycle(self, market_data: Dict) -> Dict:
        """
        Run one complete strategy cycle:
        1. Detect signals
        2. Execute new signals
        3. Monitor and exit existing positions
        4. Update performance metrics
        """
        results = {
            'signals_detected': 0,
            'positions_opened': 0,
            'positions_closed': 0,
            'total_pnl': 0
        }

        try:
            # Save market data
            strikes_data = market_data.get('data', [])
            spot_price = market_data.get('spot_price', 0)
            sentiment = market_data.get('sentiment', {})
            volatility = market_data.get('volatility', {})

            if strikes_data and spot_price:
                market_data_id = self.db.save_market_data(
                    symbol=market_data.get('symbol', 'UNKNOWN'),
                    spot_price=spot_price,
                    strikes_data=strikes_data,
                    sentiment=sentiment,
                    volatility=volatility
                )

                # Detect signals
                signals = self.detect_extreme_oi_concentration(strikes_data, spot_price)
                results['signals_detected'] = len(signals)

                # Execute signals
                for signal in signals:
                    signal['symbol'] = market_data.get('symbol', 'UNKNOWN')
                    position_id = self.execute_signal(signal, market_data)
                    if position_id:
                        results['positions_opened'] += 1

                # Monitor and exit positions
                self.monitor_and_exit_positions(market_data)

                # Get current P&L
                performance = self.db.get_performance_metrics(days=1)
                results['total_pnl'] = performance.get('total_pnl', 0)

        except Exception as e:
            logging.error(f"Error in strategy cycle: {e}")

        return results

    def get_strategy_status(self) -> Dict:
        """Get current strategy status and performance"""
        performance = self.db.get_performance_metrics(days=30)
        open_positions = self.db.get_open_positions()
        recent_signals = self.db.get_recent_signals(limit=10)

        return {
            'performance': performance,
            'open_positions': len(open_positions),
            'recent_signals': len(recent_signals),
            'parameters': self.params,
            'last_updated': datetime.now().isoformat()
        }