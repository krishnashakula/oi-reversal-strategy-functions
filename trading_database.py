import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import logging
import json
from typing import Dict, List, Optional
import os

class TradingDatabase:
    """Database manager for OI Reversal Strategy trading data and performance tracking"""

    def __init__(self, db_path: str = "oi_reversal_trading.db"):
        self.db_path = db_path
        self._initialize_database()

    def _initialize_database(self):
        """Create all necessary tables for the trading system"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Market data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    spot_price REAL NOT NULL,
                    total_call_oi INTEGER,
                    total_put_oi INTEGER,
                    put_call_ratio REAL,
                    sentiment_score REAL,
                    volatility_iv REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Strike data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strike_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_data_id INTEGER,
                    strike_price REAL NOT NULL,
                    call_oi INTEGER DEFAULT 0,
                    put_oi INTEGER DEFAULT 0,
                    call_volume INTEGER DEFAULT 0,
                    put_volume INTEGER DEFAULT 0,
                    oi_ratio REAL,
                    is_atm BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (market_data_id) REFERENCES market_data (id)
                )
            ''')

            # Trading signals table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trading_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    signal_type TEXT NOT NULL, -- 'CALL' or 'PUT'
                    strike_price REAL NOT NULL,
                    entry_trigger TEXT NOT NULL, -- 'OI_RATIO_2X', 'EXTREME_CONCENTRATION'
                    confidence REAL NOT NULL,
                    oi_ratio REAL,
                    market_sentiment TEXT,
                    volatility_regime TEXT,
                    status TEXT DEFAULT 'ACTIVE', -- 'ACTIVE', 'EXECUTED', 'EXPIRED', 'CANCELLED'
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Positions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER,
                    symbol TEXT NOT NULL,
                    position_type TEXT NOT NULL, -- 'LONG_CALL', 'SHORT_PUT', etc.
                    entry_price REAL NOT NULL,
                    entry_time DATETIME NOT NULL,
                    quantity INTEGER NOT NULL,
                    stop_loss REAL,
                    target_price REAL,
                    exit_price REAL,
                    exit_time DATETIME,
                    pnl REAL DEFAULT 0,
                    pnl_percentage REAL DEFAULT 0,
                    exit_reason TEXT, -- 'TARGET_HIT', 'STOP_LOSS', 'OI_NORMALIZED', 'MANUAL'
                    status TEXT DEFAULT 'OPEN', -- 'OPEN', 'CLOSED', 'PARTIAL_CLOSE'
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (signal_id) REFERENCES trading_signals (id)
                )
            ''')

            # Performance metrics table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE NOT NULL,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    win_rate REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    avg_win REAL DEFAULT 0,
                    avg_loss REAL DEFAULT 0,
                    profit_factor REAL DEFAULT 0,
                    max_drawdown REAL DEFAULT 0,
                    sharpe_ratio REAL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date)
                )
            ''')

            # Strategy parameters table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_parameters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parameter_name TEXT NOT NULL UNIQUE,
                    parameter_value TEXT NOT NULL,
                    description TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Insert default strategy parameters
            default_params = [
                ('oi_ratio_threshold', '2.0', 'Minimum OI ratio for signal generation (Call OI > 2x Put OI)'),
                ('profit_target_pct', '15.0', 'Profit target percentage for exit'),
                ('max_risk_per_trade', '2.0', 'Maximum risk per trade as percentage of capital'),
                ('atm_strikes_limit', '6', 'Number of strikes to consider around ATM'),
                ('min_confidence', '70.0', 'Minimum confidence level for trade execution'),
                ('oi_normalization_threshold', '1.5', 'OI ratio threshold for normalization exit')
            ]

            cursor.executemany('''
                INSERT OR IGNORE INTO strategy_parameters (parameter_name, parameter_value, description)
                VALUES (?, ?, ?)
            ''', default_params)

            conn.commit()

    def save_market_data(self, symbol: str, spot_price: float, strikes_data: List[Dict],
                        sentiment: Dict, volatility: Dict) -> int:
        """Save market data and return the market_data_id"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Calculate totals
            total_call_oi = sum(s.get('call_oi', 0) for s in strikes_data)
            total_put_oi = sum(s.get('put_oi', 0) for s in strikes_data)
            put_call_ratio = total_put_oi / total_call_oi if total_call_oi > 0 else 0

            # Insert market data
            cursor.execute('''
                INSERT INTO market_data (symbol, timestamp, spot_price, total_call_oi,
                                       total_put_oi, put_call_ratio, sentiment_score, volatility_iv)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol,
                datetime.now(),
                spot_price,
                total_call_oi,
                total_put_oi,
                put_call_ratio,
                sentiment.get('score', 50),
                volatility.get('iv', 0)
            ))

            market_data_id = cursor.lastrowid

            # Insert strike data
            for strike in strikes_data:
                cursor.execute('''
                    INSERT INTO strike_data (market_data_id, strike_price, call_oi, put_oi,
                                           call_volume, put_volume, oi_ratio, is_atm)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    market_data_id,
                    strike['strike'],
                    strike.get('call_oi', 0),
                    strike.get('put_oi', 0),
                    strike.get('call_volume', 0),
                    strike.get('put_volume', 0),
                    strike.get('oi_ratio', 0),
                    strike.get('is_atm', False)
                ))

            conn.commit()
            return market_data_id

    def save_trading_signal(self, symbol: str, signal_type: str, strike_price: float,
                           entry_trigger: str, confidence: float, oi_ratio: float,
                           market_sentiment: str, volatility_regime: str) -> int:
        """Save a trading signal and return the signal_id"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO trading_signals (symbol, timestamp, signal_type, strike_price,
                                           entry_trigger, confidence, oi_ratio, market_sentiment,
                                           volatility_regime)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol,
                datetime.now(),
                signal_type,
                strike_price,
                entry_trigger,
                confidence,
                oi_ratio,
                market_sentiment,
                volatility_regime
            ))

            signal_id = cursor.lastrowid
            conn.commit()
            return signal_id

    def open_position(self, signal_id: int, symbol: str, position_type: str,
                     entry_price: float, quantity: int, stop_loss: float = None,
                     target_price: float = None) -> int:
        """Open a new position"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO positions (signal_id, symbol, position_type, entry_price,
                                     entry_time, quantity, stop_loss, target_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                signal_id,
                symbol,
                position_type,
                entry_price,
                datetime.now(),
                quantity,
                stop_loss,
                target_price
            ))

            position_id = cursor.lastrowid

            # Update signal status
            cursor.execute('UPDATE trading_signals SET status = ? WHERE id = ?',
                         ('EXECUTED', signal_id))

            conn.commit()
            return position_id

    def close_position(self, position_id: int, exit_price: float, exit_reason: str) -> bool:
        """Close an open position"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Get position details
            cursor.execute('SELECT entry_price, quantity FROM positions WHERE id = ?',
                         (position_id,))
            result = cursor.fetchone()

            if not result:
                return False

            entry_price, quantity = result
            exit_time = datetime.now()

            # Calculate P&L
            if 'CALL' in position_type.upper() or 'LONG' in position_type.upper():
                pnl = (exit_price - entry_price) * quantity
            else:  # PUT or SHORT
                pnl = (entry_price - exit_price) * quantity

            pnl_percentage = (pnl / (entry_price * quantity)) * 100

            # Update position
            cursor.execute('''
                UPDATE positions SET exit_price = ?, exit_time = ?, pnl = ?,
                                   pnl_percentage = ?, exit_reason = ?, status = ?
                WHERE id = ?
            ''', (exit_price, exit_time, pnl, pnl_percentage, exit_reason, 'CLOSED', position_id))

            conn.commit()
            return True

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('''
                SELECT p.*, s.signal_type, s.strike_price, s.confidence
                FROM positions p
                JOIN trading_signals s ON p.signal_id = s.id
                WHERE p.status = 'OPEN'
                ORDER BY p.entry_time DESC
            ''', conn)

        return df.to_dict('records')

    def get_performance_metrics(self, days: int = 30) -> Dict:
        """Calculate performance metrics for the last N days"""
        with sqlite3.connect(self.db_path) as conn:
            # Get closed positions
            df = pd.read_sql_query('''
                SELECT * FROM positions
                WHERE status = 'CLOSED' AND exit_time >= ?
                ORDER BY exit_time DESC
            ''', conn, params=(datetime.now() - timedelta(days=days),))

        if df.empty:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'max_drawdown': 0
            }

        winning_trades = df[df['pnl'] > 0]
        losing_trades = df[df['pnl'] < 0]

        total_pnl = df['pnl'].sum()
        win_rate = len(winning_trades) / len(df) * 100 if len(df) > 0 else 0

        avg_win = winning_trades['pnl'].mean() if not winning_trades.empty else 0
        avg_loss = abs(losing_trades['pnl'].mean()) if not losing_trades.empty else 0

        gross_profit = winning_trades['pnl'].sum()
        gross_loss = abs(losing_trades['pnl'].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Calculate drawdown (simplified)
        cumulative_pnl = df['pnl'].cumsum()
        max_drawdown = (cumulative_pnl - cumulative_pnl.expanding().max()).min()

        return {
            'total_trades': len(df),
            'winning_trades': len(winning_trades),
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_drawdown, 2)
        }

    def get_strategy_parameters(self) -> Dict[str, float]:
        """Get current strategy parameters"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('SELECT parameter_name, parameter_value FROM strategy_parameters', conn)

        params = {}
        for _, row in df.iterrows():
            try:
                params[row['parameter_name']] = float(row['parameter_value'])
            except ValueError:
                params[row['parameter_name']] = row['parameter_value']

        return params

    def update_strategy_parameter(self, param_name: str, param_value: str):
        """Update a strategy parameter"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE strategy_parameters
                SET parameter_value = ?, updated_at = ?
                WHERE parameter_name = ?
            ''', (param_value, datetime.now(), param_name))
            conn.commit()

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """Get recent trading signals"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('''
                SELECT * FROM trading_signals
                ORDER BY timestamp DESC
                LIMIT ?
            ''', conn, params=(limit,))

        return df.to_dict('records')

    def get_pnl_history(self, days: int = 30) -> List[Dict]:
        """Get P&L history for charting"""
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql_query('''
                SELECT DATE(exit_time) as date, SUM(pnl) as daily_pnl
                FROM positions
                WHERE status = 'CLOSED' AND exit_time >= ?
                GROUP BY DATE(exit_time)
                ORDER BY date
            ''', conn, params=(datetime.now() - timedelta(days=days),))

        return df.to_dict('records')