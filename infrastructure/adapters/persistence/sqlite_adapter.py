"""
SQLite Persistence Adapter

Implements the PersistencePort interface using SQLite for structured data storage.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.ports.persistence.persistence_port import (
    ConnectionError,
    PersistenceError,
    PersistencePort,
    ValidationError,
)

logger = logging.getLogger(__name__)


class SQLiteAdapter(PersistencePort):
    """
    SQLite persistence adapter that implements the PersistencePort interface.
    Provides methods for all specialized ports through interface compliance.
    """

    def __init__(self, database_path: str | Path):
        """
        Initialize the SQLite adapter.

        Args:
            database_path: Path to the SQLite database file
        """
        super().__init__(str(database_path))
        self.database_path = Path(database_path)
        self._connection: sqlite3.Connection | None = None
        self._transaction_depth = 0
        self._lock = threading.Lock()

        # Ensure the directory exists
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """
        Establish connection to the SQLite database.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            if self._connection is not None:
                # Already connected
                return True

            self._connection = sqlite3.connect(
                str(self.database_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            # Enable foreign key constraints
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Return rows as dictionaries
            self._connection.row_factory = sqlite3.Row
            self._is_connected = True
            logger.info(f"Connected to SQLite database at {self.database_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to SQLite database: {e}")
            self._connection = None
            self._is_connected = False
            raise ConnectionError(f"Failed to connect to SQLite database: {e}")

    def disconnect(self) -> None:
        """Close connection to the SQLite database."""
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info(f"Disconnected from SQLite database at {self.database_path}")
            except Exception as e:
                logger.warning(f"Error while disconnecting from SQLite: {e}")
            finally:
                self._connection = None
                self._is_connected = False

    def is_connected(self) -> bool:
        """
        Check if connected to the SQLite database.

        Returns:
            True if connected, False otherwise
        """
        return self._connection is not None and self._transaction_depth >= 0

    # Transaction management
    def begin_transaction(self) -> None:
        """Begin a transaction."""
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if self._transaction_depth == 0:
            self._connection.execute("BEGIN")
        self._transaction_depth += 1

    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if self._transaction_depth <= 0:
            raise PersistenceError("No transaction to commit")
        self._transaction_depth -= 1
        if self._transaction_depth == 0:
            self._connection.commit()

    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if self._transaction_depth <= 0:
            raise PersistenceError("No transaction to rollback")
        self._transaction_depth -= 1
        if self._transaction_depth == 0:
            self._connection.rollback()

    # Helper methods
    def _execute(self, query: str, parameters: tuple | dict = ()) -> sqlite3.Cursor:
        """Execute a query and return the cursor."""
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        with self._lock:
            try:
                return self._connection.execute(query, parameters)
            except Exception as e:
                logger.error(f"SQLite query failed: {query} with params {parameters}")
                raise PersistenceError(f"SQLite query failed: {e}")

    def _execute_many(self, query: str, parameters_list: list[tuple | dict]) -> sqlite3.Cursor:
        """Execute a query multiple times with different parameters."""
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        with self._lock:
            try:
                return self._connection.executemany(query, parameters_list)
            except Exception as e:
                logger.error(f"SQLite executemany failed: {query}")
                raise PersistenceError(f"SQLite executemany failed: {e}")

    def _commit_if_needed(self):
        """Commit if not in a transaction."""
        if self.is_connected() and self._transaction_depth == 0:
            self._connection.commit()

    # Table management
    def table_exists(self, table: str) -> bool:
        """
        Check if a table exists.

        Args:
            table: Table name

        Returns:
            True if table exists, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            cursor = self._execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,)
            )
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check if table {table} exists: {e}")
            raise PersistenceError(f"Failed to check if table {table} exists: {e}")

    def create_table(self, table: str, schema: dict[str, Any]) -> bool:
        """
        Create a table with the specified schema.

        Args:
            table: Table name
            schema: Dictionary defining the table schema (column name -> type)

        Returns:
            True if table created successfully, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if self.table_exists(table):
            logger.info(f"Table {table} already exists")
            return True

        try:
            columns = []
            for column_name, column_type in schema.items():
                columns.append(f"{column_name} {column_type}")
            create_query = f"CREATE TABLE {table} ({', '.join(columns)})"
            self._execute(create_query)
            self._commit_if_needed()
            logger.info(f"Created table {table} with schema: {schema}")
            return True
        except Exception as e:
            logger.error(f"Failed to create table {table}: {e}")
            raise PersistenceError(f"Failed to create table {table}: {e}")

    def drop_table(self, table: str) -> bool:
        """
        Drop a table.

        Args:
            table: Table name

        Returns:
            True if table dropped successfully, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if not self.table_exists(table):
            logger.warning(f"Table {table} does not exist")
            return False

        try:
            self._execute(f"DROP TABLE {table}")
            self._commit_if_needed()
            logger.info(f"Dropped table {table}")
            return True
        except Exception as e:
            logger.error(f"Failed to drop table {table}: {e}")
            raise PersistenceError(f"Failed to drop table {table}: {e}")

    # CRUD operations
    def create(self, table: str, data: dict[str, Any]) -> Any:
        """
        Create a new record.

        Args:
            table: Table name
            data: Data to insert

        Returns:
            ID of the created record (lastrowid)
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if not data:
            raise ValidationError("No data provided for insertion")

        try:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            cursor = self._execute(query, tuple(data.values()))
            self._commit_if_needed()
            lastrowid = cursor.lastrowid
            logger.debug(f"Created record in {table} with ID {lastrowid}")
            return lastrowid
        except Exception as e:
            logger.error(f"Failed to create record in {table}: {e}")
            raise PersistenceError(f"Failed to create record in {table}: {e}")

    def create_many(self, table: str, data_list: list[dict[str, Any]]) -> list[Any]:
        """
        Create multiple records.

        Args:
            table: Table name
            data_list: List of data dictionaries to insert

        Returns:
            List of IDs of the created records
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if not data_list:
            return []

        # All dictionaries must have the same keys
        first_keys = set(data_list[0].keys())
        for i, data in enumerate(data_list):
            if set(data.keys()) != first_keys:
                raise ValidationError(f"All dictionaries must have the same keys. Mismatch at index {i}")

        try:
            columns = ", ".join(first_keys)
            placeholders = ", ".join(["?"] * len(first_keys))
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            parameters = [tuple(data.values()) for data in data_list]
            cursor = self._execute_many(query, parameters)
            self._commit_if_needed()
            # Note: lastrowid only gives the last inserted row ID, not all
            # We'll return a list of rowids - this is not efficient for large inserts
            # For simplicity, we'll return the lastrowid and count, but ideally we'd use RETURNING
            lastrowid = cursor.lastrowid
            rowcount = cursor.rowcount
            logger.debug(f"Created {rowcount} records in {table}, last ID: {lastrowid}")
            # Generate a list of IDs (this is approximate and may not be accurate in concurrent scenarios)
            return list(range(lastrowid - rowcount + 1, lastrowid + 1))
        except Exception as e:
            logger.error(f"Failed to create multiple records in {table}: {e}")
            raise PersistenceError(f"Failed to create multiple records in {table}: {e}")

    def read(self, table: str, record_id: Any) -> dict[str, Any] | None:
        """
        Read a record by ID.

        Args:
            table: Table name
            record_id: ID of the record to read

        Returns:
            Dictionary containing the record data, or None if not found
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            query = f"SELECT * FROM {table} WHERE id = ?"
            cursor = self._execute(query, (record_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception as e:
            logger.error(f"Failed to read record {record_id} from {table}: {e}")
            raise PersistenceError(f"Failed to read record {record_id} from {table}: {e}")

    def read_many(
        self,
        table: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order_by: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Read multiple records with filtering and pagination.

        Args:
            table: Table name
            filters: Dictionary of field-value pairs to filter by
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Field to order results by (prefix with '-' for descending)

        Returns:
            List of dictionaries containing the record data
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            # Build query parts and parameters
            query_parts = [f"SELECT * FROM {table}"]
            params = []

            # Add WHERE clause if filters provided
            if filters:
                conditions = []
                for key, value in filters.items():
                    conditions.append(f"{key} = ?")
                    params.append(value)
                if conditions:
                    query_parts.append("WHERE " + " AND ".join(conditions))

            # Add ORDER BY clause if provided
            if order_by:
                # Handle descending order
                if order_by.startswith('-'):
                    query_parts.append(f"ORDER BY {order_by[1:]} DESC")
                else:
                    query_parts.append(f"ORDER BY {order_by}")

            # Add OFFSET if provided
            if offset is not None:
                query_parts.append(f"OFFSET {offset}")
                params.append(offset)

            # Add LIMIT if provided
            if limit is not None:
                query_parts.append("LIMIT ?")
                params.append(limit)

            # Execute query
            query = " ".join(query_parts)
            cursor = self._execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to read multiple records from {table}: {e}")
            raise PersistenceError(f"Failed to read multiple records from {table}: {e}")

    def read_one(
        self,
        table: str,
        filters: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Read a single record matching filters.

        Args:
            table: Table name
            filters: Dictionary of field-value pairs to match

        Returns:
            Dictionary containing the record data, or None if not found
        """
        results = self.read_many(table, filters=filters, limit=1)
        return results[0] if results else None

    def count(
        self,
        table: str,
        filters: dict[str, Any] | None = None
    ) -> int:
        """
        Count records matching filters.

        Args:
            table: Table name
            filters: Dictionary of field-value pairs to filter by

        Returns:
            Number of matching records
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            query_parts = [f"SELECT COUNT(*) FROM {table}"]
            params = []

            if filters:
                conditions = []
                for key, value in filters.items():
                    conditions.append(f"{key} = ?")
                    params.append(value)
                if conditions:
                    query_parts.append("WHERE " + " AND ".join(conditions))

            query = " ".join(query_parts)
            cursor = self._execute(query, tuple(params))
            row = cursor.fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"Failed to count records in {table}: {e}")
            raise PersistenceError(f"Failed to count records in {table}: {e}")

    def update(
        self,
        table: str,
        record_id: Any,
        data: dict[str, Any]
    ) -> bool:
        """
        Update a record by ID.

        Args:
            table: Table name
            record_id: ID of the record to update
            data: Data to update

        Returns:
            True if update successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if not data:
            raise ValidationError("No data provided for update")

        try:
            set_clause = ", ".join([f"{key} = ?" for key in data.keys()])
            query = f"UPDATE {table} SET {set_clause} WHERE id = ?"
            parameters = tuple(data.values()) + (record_id,)
            cursor = self._execute(query, parameters)
            self._commit_if_needed()
            updated = cursor.rowcount > 0
            logger.debug(f"Updated {cursor.rowcount} records in {table}")
            return updated
        except Exception as e:
            logger.error(f"Failed to update record {record_id} in {table}: {e}")
            raise PersistenceError(f"Failed to update record {record_id} in {table}: {e}")

    def update_many(
        self,
        table: str,
        filters: dict[str, Any],
        data: dict[str, Any]
    ) -> int:
        """
        Update multiple records matching filters.

        Args:
            table: Table name
            filters: Dictionary of field-value pairs to match
            data: Data to update

        Returns:
            Number of records updated
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        if not data:
            raise ValidationError("No data provided for update")

        try:
            set_clause = ", ".join([f"{key} = ?" for key in data.keys()])
            where_conditions = []
            params = []
            for key, value in filters.items():
                where_conditions.append(f"{key} = ?")
                params.append(value)
            params.extend(data.values())  # Add the update values

            query = f"UPDATE {table} SET {set_clause} WHERE {' AND '.join(where_conditions)}"
            cursor = self._execute(query, tuple(params))
            self._commit_if_needed()
            updated = cursor.rowcount
            logger.debug(f"Updated {updated} records in {table}")
            return updated
        except Exception as e:
            logger.error(f"Failed to update multiple records in {table}: {e}")
            raise PersistenceError(f"Failed to update multiple records in {table}: {e}")

    def delete(self, table: str, record_id: Any) -> bool:
        """
        Delete a record by ID.

        Args:
            table: Table name
            record_id: ID of the record to delete

        Returns:
            True if deletion successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            query = f"DELETE FROM {table} WHERE id = ?"
            cursor = self._execute(query, (record_id,))
            self._commit_if_needed()
            deleted = cursor.rowcount > 0
            logger.debug(f"Deleted {cursor.rowcount} records from {table}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete record {record_id} from {table}: {e}")
            raise PersistenceError(f"Failed to delete record {record_id} from {table}: {e}")

    def delete_many(
        self,
        table: str,
        filters: dict[str, Any]
    ) -> int:
        """
        Delete multiple records matching filters.

        Args:
            table: Table name
            filters: Dictionary of field-value pairs to match

        Returns:
            Number of records deleted
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            where_conditions = []
            params = []
            for key, value in filters.items():
                where_conditions.append(f"{key} = ?")
                params.append(value)
            query = f"DELETE FROM {table} WHERE {' AND '.join(where_conditions)}"
            cursor = self._execute(query, tuple(params))
            self._commit_if_needed()
            deleted = cursor.rowcount
            logger.debug(f"Deleted {deleted} records from {table}")
            return deleted
        except Exception as e:
            logger.error(f"Failed to delete multiple records from {table}: {e}")
            raise PersistenceError(f"Failed to delete multiple records from {table}: {e}")

    # StatePersistencePort implementation
    def save_state(self, state: dict[str, Any]) -> bool:
        """
        Save application state to a JSON blob in a dedicated table.

        Args:
            state: State dictionary to save

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            # Ensure the state table exists
            if not self.table_exists("app_state"):
                self.create_table("app_state", {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "state_json": "TEXT NOT NULL",
                    "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                })

            state_json = json.dumps(state)
            # Upsert: delete existing and insert new (since we only want one state record)
            self._execute("DELETE FROM app_state")
            self._execute(
                "INSERT INTO app_state (state_json) VALUES (?)",
                (state_json,)
            )
            self._commit_if_needed()
            logger.debug("Application state saved to SQLite")
            return True
        except Exception as e:
            logger.error(f"Failed to save application state: {e}")
            raise PersistenceError(f"Failed to save application state: {e}")

    def load_state(self) -> dict[str, Any] | None:
        """
        Load application state from the database.

        Returns:
            State dictionary, or None if no state exists
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            if not self.table_exists("app_state"):
                return None
            cursor = self._execute("SELECT state_json FROM app_state ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            if row is None:
                return None
            state_json = row[0]
            return json.loads(state_json)
        except Exception as e:
            logger.error(f"Failed to load application state: {e}")
            raise PersistenceError(f"Failed to load application state: {e}")

    def delete_state(self) -> bool:
        """
        Delete application state from the database.

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            if self.table_exists("app_state"):
                self._execute("DELETE FROM app_state")
                self._commit_if_needed()
                logger.debug("Application state deleted from SQLite")
            return True
        except Exception as e:
            logger.error(f"Failed to delete application state: {e}")
            raise PersistenceError(f"Failed to delete application state: {e}")

    # TradePersistencePort implementation
    def save_trade(self, trade_data: dict[str, Any]) -> str:
        """
        Save a trade record.

        Args:
            trade_data: Trade data dictionary

        Returns:
            ID of the created trade record
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            # Ensure the trades table exists
            if not self.table_exists("trades"):
                self.create_table("trades", {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "symbol": "TEXT NOT NULL",
                    "direction": "TEXT NOT NULL",  # BUY/SELL
                    "strike_price": "REAL",
                    "lot_size": "INTEGER",
                    "entry_price": "REAL",
                    "entry_time": "TIMESTAMP",
                    "exit_price": "REAL",
                    "exit_time": "TIMESTAMP",
                    "exit_reason": "TEXT",
                    "gross_pnl": "REAL",
                    "brokerage": "REAL",
                    "taxes": "REAL",
                    "net_pnl": "REAL",
                    "strategy": "TEXT",
                    "tags": "TEXT",  # JSON array
                    "regime_at_entry": "TEXT",
                    "session_at_entry": "TEXT",
                    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                })

            # Convert tags to JSON if present
            if "tags" in trade_data and isinstance(trade_data["tags"], list):
                trade_data["tags"] = json.dumps(trade_data["tags"])

            trade_id = self.create("trades", trade_data)
            logger.debug(f"Trade saved with ID {trade_id}")
            return str(trade_id)
        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
            raise PersistenceError(f"Failed to save trade: {e}")

    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """
        Get a trade by ID.

        Args:
            trade_id: Trade ID

        Returns:
            Trade data dictionary, or None if not found
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            trade = self.read("trades", int(trade_id))
            if trade is None:
                return None
            # Convert tags from JSON if present
            if "tags" in trade and trade["tags"] is not None:
                try:
                    trade["tags"] = json.loads(trade["tags"])
                except (json.JSONDecodeError, TypeError):
                    # If it's not valid JSON, leave it as is
                    pass
            return trade
        except Exception as e:
            logger.error(f"Failed to get trade {trade_id}: {e}")
            raise PersistenceError(f"Failed to get trade {trade_id}: {e}")

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
            start_date: Filter by entry time >= start_date
            end_date: Filter by entry time <= end_date
            limit: Maximum number of trades to return

        Returns:
            List of trade data dictionaries
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            filters = {}
            if symbol:
                filters["symbol"] = symbol
            if start_date:
                filters["entry_time"] = (">=", start_date.isoformat())
            if end_date:
                # We'll handle end_date specially in the query since we need <=
                pass  # We'll handle this in the custom query below

            # Since we have mixed filter types, we'll build a custom query
            query_parts = ["SELECT * FROM trades"]
            conditions = []
            params = []

            if symbol:
                conditions.append("symbol = ?")
                params.append(symbol)
            if start_date:
                conditions.append("entry_time >= ?")
                params.append(start_date.isoformat())
            if end_date:
                conditions.append("entry_time <= ?")
                params.append(end_date.isoformat())

            if conditions:
                query_parts.append("WHERE " + " AND ".join(conditions))

            query_parts.append("ORDER BY entry_time DESC")
            if limit is not None:
                query_parts.append(f"LIMIT {limit}")

            query = " ".join(query_parts)
            cursor = self._execute(query, tuple(params))
            rows = cursor.fetchall()
            trades = [dict(row) for row in rows]

            # Convert tags from JSON if present
            for trade in trades:
                if "tags" in trade and trade["tags"] is not None:
                    try:
                        trade["tags"] = json.loads(trade["tags"])
                    except (json.JSONDecodeError, TypeError):
                        pass

            return trades
        except Exception as e:
            logger.error(f"Failed to get trades: {e}")
            raise PersistenceError(f"Failed to get trades: {e}")

    def update_trade(self, trade_id: str, trade_data: dict[str, Any]) -> bool:
        """
        Update a trade record.

        Args:
            trade_id: Trade ID
            trade_data: Updated trade data

        Returns:
            True if update successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            # Convert tags to JSON if present
            if "tags" in trade_data and isinstance(trade_data["tags"], list):
                trade_data["tags"] = json.dumps(trade_data["tags"])

            updated = self.update("trades", int(trade_id), trade_data)
            if updated:
                logger.debug(f"Trade {trade_id} updated")
            return updated
        except Exception as e:
            logger.error(f"Failed to update trade {trade_id}: {e}")
            raise PersistenceError(f"Failed to update trade {trade_id}: {e}")

    # MarketDataPersistencePort implementation
    def save_market_data(
        self,
        symbol: str,
        data: dict[str, Any],
        timestamp: datetime | None = None
    ) -> bool:
        """
        Save market data point.

        Args:
            symbol: Trading symbol
            data: Market data dictionary (bid, ask, last, volume, etc.)
            timestamp: Timestamp of the data (defaults to now)

        Returns:
            True if successful, False otherwise
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            # Ensure the market_data table exists
            if not self.table_exists("market_data"):
                self.create_table("market_data", {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "symbol": "TEXT NOT NULL",
                    "bid": "REAL",
                    "ask": "REAL",
                    "last": "REAL",
                    "volume": "INTEGER",
                    "timestamp": "TIMESTAMP NOT NULL",
                    "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                })

            if timestamp is None:
                timestamp = now_ist()

            # Ensure timestamp is in ISO format for storage
            if isinstance(timestamp, datetime):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)

            market_data = {
                "symbol": symbol,
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "last": data.get("last"),
                "volume": data.get("volume"),
                "timestamp": timestamp_str
            }

            self.create("market_data", market_data)
            logger.debug(f"Market data saved for {symbol} at {timestamp_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to save market data for {symbol}: {e}")
            raise PersistenceError(f"Failed to save market data for {symbol}: {e}")

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
            symbol: Trading symbol
            start_time: Filter by timestamp >= start_time
            end_time: Filter by timestamp <= end_time
            limit: Maximum number of records to return

        Returns:
            List of market data dictionaries
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            query_parts = ["SELECT * FROM market_data WHERE symbol = ?"]
            params = [symbol]

            if start_time:
                query_parts.append("AND timestamp >= ?")
                params.append(start_time.isoformat())
            if end_time:
                query_parts.append("AND timestamp <= ?")
                params.append(end_time.isoformat())

            query_parts.append("ORDER BY timestamp DESC")
            if limit is not None:
                query_parts.append(f"LIMIT {limit}")

            query = " ".join(query_parts)
            cursor = self._execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            raise PersistenceError(f"Failed to get market data for {symbol}: {e}")

    def get_latest_market_data(self, symbol: str) -> dict[str, Any] | None:
        """
        Get the latest market data point for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Latest market data dictionary, or None if not found
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to database")
        try:
            query = """
                SELECT * FROM market_data
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """
            cursor = self._execute(query, (symbol,))
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception as e:
            logger.error(f"Failed to get latest market data for {symbol}: {e}")
            raise PersistenceError(f"Failed to get latest market data for {symbol}: {e}")

    # CSVPersistencePort implementation - we'll implement basic CSV operations
    # Note: For CSV, we don't use the database, so we'll implement file-based methods
    def append_row(self, file_path: str | Path, row: dict[str, Any]) -> bool:
        """
        Append a row to a CSV file.

        Args:
            file_path: Path to the CSV file
            row: Row data as dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Determine if we need to write headers
            write_headers = not file_path.exists()

            import csv
            with open(file_path, 'a', newline='', encoding='utf-8') as csvfile:
                if row:
                    writer = csv.DictWriter(csvfile, fieldnames=row.keys())
                    if write_headers:
                        writer.writeheader()
                    writer.writerow(row)
            logger.debug(f"Appended row to CSV file {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to append row to CSV {file_path}: {e}")
            raise PersistenceError(f"Failed to append row to CSV {file_path}: {e}")

    def write_rows(self, file_path: str | Path, rows: list[dict[str, Any]], headers: list[str]) -> bool:
        """
        Write rows to a CSV file.

        Args:
            file_path: Path to the CSV file
            rows: List of row dictionaries
            headers: List of column headers

        Returns:
            True if successful, False otherwise
        """
        try:
            file_path = Path(file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            import csv
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                if rows:
                    writer.writerows(rows)
            logger.debug(f"Wrote {len(rows)} rows to CSV file {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to write rows to CSV {file_path}: {e}")
            raise PersistenceError(f"Failed to write rows to CSV {file_path}: {e}")

    def read_rows(self, file_path: str | Path) -> list[dict[str, Any]]:
        """
        Read rows from a CSV file.

        Args:
            file_path: Path to the CSV file

        Returns:
            List of row dictionaries
        """
        try:
            file_path = Path(file_path)
            if not file_path.exists():
                return []

            import csv
            with open(file_path, newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                return [row for row in reader]
        except Exception as e:
            logger.error(f"Failed to read rows from CSV {file_path}: {e}")
            raise PersistenceError(f"Failed to read rows from CSV {file_path}: {e}")

    def file_exists(self, file_path: str | Path) -> bool:
        """
        Check if a CSV file exists.

        Args:
            file_path: Path to the CSV file

        Returns:
            True if file exists, False otherwise
        """
        return Path(file_path).exists()

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the SQLite database.

        Returns:
            Dictionary containing health check results
        """
        try:
            connected = self.is_connected()
            db_size = self.database_path.stat().st_size if self.database_path.exists() else 0
            return {
                "status": "healthy" if connected else "unhealthy",
                "connected": connected,
                "backend": "SQLite",
                "database_path": str(self.database_path),
                "database_size_bytes": db_size,
                "sqlite_version": sqlite3.sqlite_version if connected else None
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "connected": False,
                "backend": "SQLite",
                "error": str(e)
            }


# Factory function for easy instantiation
def create_sqlite_persistence(database_path: str | Path) -> SQLiteAdapter:
    """
    Factory function to create and connect an SQLite adapter.

    Args:
        database_path: Path to the SQLite database file

    Returns:
        Connected SQLiteAdapter instance
    """
    adapter = SQLiteAdapter(database_path)
    if not adapter.connect():
        raise ConnectionError(f"Failed to connect to SQLite database at {database_path}")
    return adapter
