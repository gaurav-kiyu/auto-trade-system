"""
Persistence Service

Provides a unified interface for data persistence operations using SQLite,
JSON state files, and CSV exports with proper connection management,
error handling, and fallback mechanisms.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3

__all__ = [
    "PersistenceServiceConfig",
    "PersistenceService",
]
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.logging import LoggingService
from core.persistence.state.manager import StatePersistenceManager
from core.persistence.trades.manager import TradesPersistenceManager
from core.ports.persistence.persistence_port import (
    ConnectionError,
    ValidationError,
)
from infrastructure.adapters.persistence.sqlite_adapter import SQLiteAdapter


@dataclass
class PersistenceServiceConfig:
    """Configuration for the persistence service."""
    # Database paths
    trades_db_path: str = "data/trades.db"
    state_db_path: str = "data/trader_state.json"  # JSON file for state
    market_data_db_path: str = "data/market_data.db"

    # Connection settings
    connection_timeout: float = 30.0
    max_connections: int = 10

    # Backup settings
    enable_auto_backup: bool = True
    backup_interval_hours: int = 24
    backup_retention_count: int = 7

    # Performance settings
    enable_wal_mode: bool = True  # Write-Ahead Logging for better concurrency
    synchronous_mode: str = "NORMAL"  # FULL, NORMAL, OFF
    cache_size: int = -2000  # Negative means KB


class PersistenceService:
    """
    Unified persistence service that manages multiple persistence backends:
    - SQLite for structured data (trades, market data, etc.)
    - JSON for application state
    - CSV for exports and reports
    - Provides connection pooling, retry logic, and proper error handling
    """

    def __init__(self, config: PersistenceServiceConfig | None = None):
        self.config = config or PersistenceServiceConfig()
        self._lock = threading.RLock()

        # Initialize specialized managers
        self._trades_manager = TradesPersistenceManager(self.config.trades_db_path)
        self._state_manager = StatePersistenceManager(self.config.state_db_path)

        # Market data still uses raw adapter for now
        self._market_data_adapter = SQLiteAdapter(self.config.market_data_db_path)

        # Connection tracking
        self._connection_count = 0
        self._max_connections_reached = False

        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="persistence_service_",
            retain_days=30,
            json_log_file="",
            version="UNKNOWN",
            enable_correlation_ids=True,
            enable_contextual_logging=True
        )

        self._logger.info("PersistenceService initialized")

    def start(self) -> bool:
        """Start the persistence service and initialize connections."""
        try:
            self._logger.info("Starting persistence service...")

            # Initialize adapters
            self._initialize_adapters()

            # Run health checks
            self._perform_health_checks()

            self._logger.info("Persistence service started successfully")
            return True

        except (OSError, sqlite3.Error, ValueError) as e:
            self._logger.error(f"Failed to start persistence service: {e}")
            return False

    def stop(self) -> bool:
        """Stop the persistence service and close connections."""
        try:
            self._logger.info("Stopping persistence service...")

            # Close all adapters
            self._close_adapters()

            self._logger.info("Persistence service stopped")
            return True

        except (OSError, sqlite3.Error, ValueError) as e:
            self._logger.error(f"Error stopping persistence service: {e}")
            return False

    def _initialize_adapters(self) -> None:
        """Initialize all persistence adapters."""
        with self._lock:
            # Trades database
            self._trades_adapter = SQLiteAdapter(self.config.trades_db_path)
            if not self._trades_adapter.connect():
                raise ConnectionError(f"Failed to connect to trades database: {self.config.trades_db_path}")
            # Create trades table if it doesn't exist
            self._create_trades_table_if_not_exists()

            # Market data database
            self._market_data_adapter = SQLiteAdapter(self.config.market_data_db_path)
            if not self._market_data_adapter.connect():
                raise ConnectionError(f"Failed to connect to market data database: {self.config.market_data_db_path}")
            # Create market data table if it doesn't exist
            self._create_market_data_table_if_not_exists()

            # State adapter (JSON file)
            self._state_adapter = _JSONStateAdapter(self.config.state_db_path)
            if not self._state_adapter.connect():
                raise ConnectionError(f"Failed to connect to state file: {self.config.state_db_path}")

            self._logger.info("All persistence adapters initialized and connected")

    def _create_trades_table_if_not_exists(self) -> None:
        """Create the trades table if it doesn't exist."""
        if not self._trades_adapter:
            return

        try:
            # Check if table exists
            if not self._trades_adapter.table_exists('trades'):
                # Define schema for trades table
                schema = {
                    'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                    'symbol': 'TEXT NOT NULL',
                    'direction': 'TEXT NOT NULL',
                    'entry_price': 'REAL NOT NULL',
                    'exit_price': 'REAL',
                    'quantity': 'INTEGER NOT NULL',
                    'pnl': 'REAL DEFAULT 0',
                    'timestamp': 'TEXT NOT NULL',
                    'status': 'TEXT DEFAULT \"OPEN\"',
                    'stop_loss': 'REAL',
                    'target': 'REAL',
                    'strategy_id': 'TEXT',
                    'exchange': 'TEXT',
                    'product_type': 'TEXT'
                }
                if self._trades_adapter.create_table('trades', schema):
                    self._logger.info("Created trades table")
                else:
                    self._logger.warning("Failed to create trades table")
            else:
                self._logger.debug("Trades table already exists")
        except (sqlite3.Error, OSError) as e:
            self._logger.error(f"Error creating trades table: {e}")

    def _create_market_data_table_if_not_exists(self) -> None:
        """Create the market data table if it doesn't exist."""
        if not self._market_data_adapter:
            return

        try:
            # Check if table exists
            if not self._market_data_adapter.table_exists('market_data'):
                # Define schema for market data table
                schema = {
                    'id': 'INTEGER PRIMARY KEY AUTOINCREMENT',
                    'symbol': 'TEXT NOT NULL',
                    'timestamp': 'TEXT NOT NULL',
                    'open': 'REAL',
                    'high': 'REAL',
                    'low': 'REAL',
                    'close': 'REAL',
                    'volume': 'INTEGER',
                    'vwap': 'REAL',
                    'rsi': 'REAL',
                    'macd': 'REAL',
                    'volatility': 'REAL'
                }
                if self._market_data_adapter.create_table('market_data', schema):
                    self._logger.info("Created market data table")
                else:
                    self._logger.warning("Failed to create market data table")
            else:
                self._logger.debug("Market data table already exists")
        except (sqlite3.Error, OSError) as e:
            self._logger.error(f"Error creating market data table: {e}")

    def _close_adapters(self) -> None:
        """Close all persistence adapters."""
        with self._lock:
            adapters = [
                self._trades_adapter,
                self._market_data_adapter,
                self._state_adapter
            ]

            for adapter in adapters:
                if adapter:
                    try:
                        adapter.disconnect()
                    except (OSError, sqlite3.Error, AttributeError) as e:
                        self._logger.warning(f"Error closing adapter: {e}")

            self._trades_adapter = None
            self._market_data_adapter = None
            self._state_adapter = None

    def _perform_health_checks(self) -> None:
        """Perform health checks on all adapters."""
        health_checks = [
            ("trades", self._trades_adapter),
            ("market_data", self._market_data_adapter),
            ("state", self._state_adapter)
        ]

        for name, adapter in health_checks:
            if adapter:
                try:
                    health = adapter.health_check()
                    self._logger.info(f"{name} persistence health: {health['status']}")
                except (OSError, sqlite3.Error, AttributeError) as e:
                    self._logger.warning(f"Health check failed for {name}: {e}")

    # =============================================================================
    # TRADES PERSISTENCE
    # =============================================================================

    def save_trade(self, trade_data: dict[str, Any]) -> str:
        """
        Save a trade record to the trades database.

        Args:
            trade_data: Dictionary containing trade information

        Returns:
            Trade ID of the saved record
        """
        if not self._trades_adapter:
            raise ConnectionError("Trades adapter not initialized")

        # Ensure required fields exist
        required_fields = ['symbol', 'direction', 'entry_price', 'quantity']
        for field in required_fields:
            if field not in trade_data:
                raise ValidationError(f"Missing required field: {field}")

        # Add timestamp if not provided
        if 'timestamp' not in trade_data:
            trade_data['timestamp'] = now_ist().isoformat()

        # Save to trades table
        return self._trades_adapter.create('trades', trade_data)

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """
        Retrieve a trade by ID.

        Args:
            trade_id: The trade ID to retrieve

        Returns:
            Trade data dictionary or None if not found
        """
        if not self._trades_adapter:
            raise ConnectionError("Trades adapter not initialized")

        return self._trades_adapter.read('trades', trade_id)

    def get_trades(
        self,
        symbol: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Get trades with optional filtering.

        Args:
            symbol: Filter by symbol
            start_date: Filter by start date (inclusive)
            end_date: Filter by end date (inclusive)
            limit: Maximum number of records to return

        Returns:
            List of trade dictionaries
        """
        if not self._trades_adapter:
            raise ConnectionError("Trades adapter not initialized")

        filters = {}
        if symbol:
            filters['symbol'] = symbol
        if start_date:
            filters['timestamp__gte'] = start_date.isoformat()
        if end_date:
            filters['timestamp__lte'] = end_date.isoformat()

        return self._trades_adapter.read_many(
            table='trades',
            filters=filters,
            limit=limit,
            order_by='-timestamp'  # Most recent first
        )

    def update_trade(self, trade_id: str, trade_data: dict[str, Any]) -> bool:
        """
        Update a trade record.

        Args:
            trade_id: The trade ID to update
            trade_data: Dictionary containing updated trade information

        Returns:
            True if update successful, False otherwise
        """
        if not self._trades_adapter:
            raise ConnectionError("Trades adapter not initialized")

        return self._trades_adapter.update('trades', trade_id, trade_data)

    # =============================================================================
    # MARKET DATA PERSISTENCE
    # =============================================================================

    def save_market_data(
        self,
        symbol: str,
        data: dict[str, Any],
        timestamp: datetime | None = None
    ) -> bool:
        """
        Save market data point.

        Args:
            symbol: The symbol (e.g., 'NIFTY26JULFUT')
            data: Market data dictionary (OHLCV, indicators, etc.)
            timestamp: Optional timestamp (defaults to now)

        Returns:
            True if save successful, False otherwise
        """
        if not self._market_data_adapter:
            raise ConnectionError("Market data adapter not initialized")

        market_data_record = {
            'symbol': symbol,
            'timestamp': (timestamp or now_ist()).isoformat(),
            **data
        }

        try:
            self._market_data_adapter.create('market_data', market_data_record)
            return True
        except (sqlite3.Error, OSError, ValueError) as e:
            self._logger.error(f"Failed to save market data for {symbol}: {e}")
            return False

    def get_market_data(
        self,
        symbol: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Get market data for a symbol.

        Args:
            symbol: The symbol to get data for
            start_time: Optional start time filter
            end_time: Optional end time filter
            limit: Optional limit on number of records

        Returns:
            List of market data dictionaries
        """
        if not self._market_data_adapter:
            raise ConnectionError("Market data adapter not initialized")

        filters = {'symbol': symbol}
        if start_time:
            filters['timestamp__gte'] = start_time.isoformat()
        if end_time:
            filters['timestamp__lte'] = end_time.isoformat()

        # Get all matching records and sort in Python (since adapter doesn't support order_by)
        results = self._market_data_adapter.read_many(
            table='market_data',
            filters=filters,
            limit=limit
        )

        # Sort by timestamp descending (most recent first)
        results.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return results

    def get_latest_market_data(self, symbol: str) -> dict[str, Any] | None:
        """
        Get the latest market data point for a symbol.

        Args:
            symbol: The symbol to get data for

        Returns:
            Latest market data dictionary or None if not found
        """
        data = self.get_market_data(symbol=symbol, limit=1)
        return data[0] if data else None

    # =============================================================================
    # APPLICATION STATE PERSISTENCE
    # =============================================================================

    def save_state(self, state: dict[str, Any]) -> bool:
        """
        Save application state to JSON file.

        Args:
            state: Dictionary containing application state

        Returns:
            True if save successful, False otherwise
        """
        if not self._state_adapter:
            raise ConnectionError("State adapter not initialized")

        try:
            # Add metadata
            state_with_metadata = {
                **state,
                '_metadata': {
                    'saved_at': now_ist().isoformat(),
                    'version': '2.45'
                }
            }

            return self._state_adapter.save_state(state_with_metadata)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            self._logger.error(f"Failed to save application state: {e}")
            return False

    def load_state(self) -> dict[str, Any] | None:
        """
        Load application state from JSON file.

        Returns:
            Application state dictionary or None if not found/error
        """
        if not self._state_adapter:
            raise ConnectionError("State adapter not initialized")

        try:
            state = self._state_adapter.load_state()
            if state and '_metadata' in state:
                # Remove metadata before returning to caller
                state_copy = state.copy()
                del state_copy['_metadata']
                return state_copy
            return state
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self._logger.error(f"Failed to load application state: {e}")
            return None

    def delete_state(self) -> bool:
        """
        Delete application state file.

        Returns:
            True if delete successful, False otherwise
        """
        if not self._state_adapter:
            raise ConnectionError("State adapter not initialized")

        try:
            return self._state_adapter.delete_state()
        except (OSError, FileNotFoundError, PermissionError) as e:
            self._logger.error(f"Failed to delete application state: {e}")
            return False

    # =============================================================================
    # CSV EXPORT OPERATIONS
    # =============================================================================

    def export_trades_to_csv(
        self,
        file_path: str | Path,
        symbol: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None
    ) -> bool:
        """
        Export trades to CSV file.

        Args:
            file_path: Path to the CSV file to create
            symbol: Optional symbol filter
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            True if export successful, False otherwise
        """
        if not self._trades_adapter:
            raise ConnectionError("Trades adapter not initialized")

        try:
            # Get trades data
            trades = self.get_trades(symbol=symbol, start_date=start_date, end_date=end_date)

            if not trades:
                self._logger.warning("No trades found to export")
                # Create empty CSV with headers
                self._write_empty_csv(file_path, [
                    'id', 'symbol', 'direction', 'entry_price', 'exit_price',
                    'quantity', 'pnl', 'timestamp', 'status'
                ])
                return True

            # Prepare CSV rows
            rows = []
            for trade in trades:
                # Flatten the trade data for CSV
                row = {
                    'id': trade.get('id', ''),
                    'symbol': trade.get('symbol', ''),
                    'direction': trade.get('direction', ''),
                    'entry_price': trade.get('entry_price', 0),
                    'exit_price': trade.get('exit_price', 0),
                    'quantity': trade.get('quantity', 0),
                    'pnl': trade.get('pnl', 0),
                    'timestamp': trade.get('timestamp', ''),
                    'status': trade.get('status', '')
                }
                rows.append(row)

            # Write to CSV
            headers = [
                'id', 'symbol', 'direction', 'entry_price', 'exit_price',
                'quantity', 'pnl', 'timestamp', 'status'
            ]

            return self._write_csv_file(file_path, rows, headers)

        except (OSError, ValueError, TypeError, csv.Error) as e:
            self._logger.error(f"Failed to export trades to CSV: {e}")
            return False

    def _write_csv_file(
        self,
        file_path: str | Path,
        rows: list[dict[str, Any]],
        headers: list[str]
    ) -> bool:
        """Write data to CSV file."""
        try:
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            import csv
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)

            self._logger.info(f"Successfully wrote CSV file to {file_path} with {len(rows)} rows")
            return True

        except (OSError, ValueError, TypeError, csv.Error) as e:
            self._logger.error(f"Failed to write CSV file {file_path}: {e}")
            return False

    def _write_empty_csv(
        self,
        file_path: str | Path,
        headers: list[str]
    ) -> bool:
        """Write an empty CSV file with just headers."""
        return self._write_csv_file(file_path, [], headers)

    # =============================================================================
    # SERVICE STATUS AND MONITORING
    # =============================================================================

    def get_service_status(self) -> dict[str, Any]:
        """
        Get the current status of the persistence service.

        Returns:
            Dictionary containing service status information
        """
        status_info = {
            'service': 'PersistenceService',
            'status': 'running' if all([
                self._trades_adapter and self._trades_adapter.is_connected(),
                self._market_data_adapter and self._market_data_adapter.is_connected(),
                self._state_adapter and self._state_adapter.is_connected()
            ]) else 'error',
            'adapters': {}
        }

        # Check each adapter
        adapters = [
            ('trades', self._trades_adapter),
            ('market_data', self._market_data_adapter),
            ('state', self._state_adapter)
        ]

        for name, adapter in adapters:
            if adapter:
                try:
                    health = adapter.health_check()
                    status_info['adapters'][name] = {
                        'status': health.get('status', 'unknown'),
                        'connected': health.get('connected', False),
                        'backend': health.get('backend', 'unknown')
                    }
                except (OSError, sqlite3.Error, AttributeError) as e:
                    status_info['adapters'][name] = {
                        'status': 'error',
                        'connected': False,
                        'error': str(e)
                    }
            else:
                status_info['adapters'][name] = {
                    'status': 'not_initialized',
                    'connected': False
                }

        return status_info

    def health_check(self) -> dict[str, Any]:
        """
        Perform a comprehensive health check.

        Returns:
            Dictionary containing health check results
        """
        return self.get_service_status()


class _JSONStateAdapter:
    """Adapter for JSON file-based state persistence."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self._is_connected = False
        self._logger.debug(f"JSONStateAdapter initialized for {file_path}")

    def connect(self) -> bool:
        """Connect to the JSON state file (ensure directory exists)."""
        try:
            with self._lock:
                # Ensure directory exists
                self.file_path.parent.mkdir(parents=True, exist_ok=True)

                # If file doesn't exist, create it with empty object
                if not self.file_path.exists():
                    self._write_state({})

                self._is_connected = True
                self._logger.debug(f"Connected to JSON state file: {self.file_path}")
                return True

        except (OSError, PermissionError, ValueError) as e:
            self._logger.error(f"Failed to connect to JSON state file {self.file_path}: {e}")
            self._is_connected = False
            return False

    def disconnect(self) -> None:
        """Disconnect (no-op for file-based storage)."""
        with self._lock:
            self._is_connected = False
            self._logger.debug(f"Disconnected from JSON state file: {self.file_path}")

    def is_connected(self) -> bool:
        """Check if connected to the JSON state file."""
        return self._is_connected

    def save_state(self, state: dict[str, Any]) -> bool:
        """Save state to JSON file."""
        try:
            with self._lock:
                self._write_state(state)
                self._logger.debug(f"State saved to {self.file_path}")
                return True
        except (OSError, TypeError, ValueError) as e:
            self._logger.error(f"Failed to save state to {self.file_path}: {e}")
            return False

    def load_state(self) -> dict[str, Any] | None:
        """Load state from JSON file."""
        try:
            with self._lock:
                if not self.file_path.exists():
                    self._logger.debug(f"State file {self.file_path} does not exist")
                    return None

                with open(self.file_path, encoding='utf-8') as f:
                    state = json.load(f)

                self._logger.debug(f"State loaded from {self.file_path}")
                return state

        except json.JSONDecodeError as e:
            self._logger.error(f"Invalid JSON in state file {self.file_path}: {e}")
            return None
        except Exception as e:
            self._logger.error(f"Failed to load state from {self.file_path}: {e} (type: {type(e).__name__})")
            return None

    def delete_state(self) -> bool:
        """Delete the state file."""
        try:
            with self._lock:
                if self.file_path.exists():
                    self.file_path.unlink()
                    self._logger.debug(f"State file {self.file_path} deleted")
                self._is_connected = False
                return True
        except (OSError, FileNotFoundError, PermissionError) as e:
            self._logger.error(f"Failed to delete state file {self.file_path}: {e}")
            return False

    def health_check(self) -> dict[str, Any]:
        """Perform health check on the JSON state adapter."""
        try:
            file_exists = self.file_path.exists()
            file_readable = os.access(self.file_path, os.R_OK) if file_exists else False
            file_writable = os.access(self.file_path.parent, os.W_OK) if self.file_path.parent.exists() else False

            return {
                'status': 'healthy' if (file_exists and file_readable and file_writable) else 'unhealthy',
                'connected': self._is_connected,
                'backend': 'JSONFileAdapter',
                'file_path': str(self.file_path),
                'file_exists': file_exists,
                'file_readable': file_readable,
                'file_writable': file_writable
            }
        except (OSError, ValueError) as e:
            return {
                'status': 'error',
                'connected': self._is_connected,
                'backend': 'JSONFileAdapter',
                'error': str(e)
            }

    def _write_state(self, state: dict[str, Any]) -> None:
        """Write state dictionary to JSON file."""
        # Ensure directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write with indentation for readability
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, default=str, ensure_ascii=False)
