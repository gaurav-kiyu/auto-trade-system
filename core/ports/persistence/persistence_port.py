"""
Persistence Port Interface

This interface defines the contract that all persistence adapters must implement.
It provides a unified way to store and retrieve data using different backends
(SQLite, JSON, CSV, etc.) with proper connection management and error handling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any


class PersistenceError(Exception):
    """Base exception for persistence-related errors."""
    pass


class ConnectionError(PersistenceError):
    """Exception raised when connection to persistence backend fails."""
    pass


class ValidationError(PersistenceError):
    """Exception raised when data validation fails."""
    pass


class NotFoundError(PersistenceError):
    """Exception raised when requested data is not found."""
    pass


class PersistencePort(ABC):
    """
    Abstract base class for persistence adapters.

    All persistence implementations (SQLite, JSON, CSV, etc.) must inherit from this class
    and implement the required methods.
    """

    def __init__(self, connection_string: str):
        """
        Initialize the persistence adapter.

        Args:
            connection_string: Connection string or path for the persistence backend
        """
        self.connection_string = connection_string
        self._is_connected = False

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to the persistence backend.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to the persistence backend."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """
        Check if connected to the persistence backend.

        Returns:
            True if connected, False otherwise
        """
        pass

    # CREATE operations
    @abstractmethod
    def create(self, table: str, data: dict[str, Any]) -> Any:
        """
        Create a new record.

        Args:
            table: Table/collection name
            data: Data to insert

        Returns:
            ID of the created record
        """
        pass

    @abstractmethod
    def create_many(self, table: str, data_list: list[dict[str, Any]]) -> list[Any]:
        """
        Create multiple records.

        Args:
            table: Table/collection name
            data_list: List of data dictionaries to insert

        Returns:
            List of IDs of the created records
        """
        pass

    # READ operations
    @abstractmethod
    def read(self, table: str, record_id: Any) -> dict[str, Any] | None:
        """
        Read a record by ID.

        Args:
            table: Table/collection name
            record_id: ID of the record to read

        Returns:
            Dictionary containing the record data, or None if not found
        """
        pass

    @abstractmethod
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
            table: Table/collection name
            filters: Dictionary of field-value pairs to filter by
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Field to order results by (prefix with '-' for descending)

        Returns:
            List of dictionaries containing the record data
        """
        pass

    @abstractmethod
    def read_one(
        self,
        table: str,
        filters: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Read a single record matching filters.

        Args:
            table: Table/collection name
            filters: Dictionary of field-value pairs to match

        Returns:
            Dictionary containing the record data, or None if not found
        """
        pass

    @abstractmethod
    def count(
        self,
        table: str,
        filters: dict[str, Any] | None = None
    ) -> int:
        """
        Count records matching filters.

        Args:
            table: Table/collection name
            filters: Dictionary of field-value pairs to filter by

        Returns:
            Number of matching records
        """
        pass

    # UPDATE operations
    @abstractmethod
    def update(
        self,
        table: str,
        record_id: Any,
        data: dict[str, Any]
    ) -> bool:
        """
        Update a record by ID.

        Args:
            table: Table/collection name
            record_id: ID of the record to update
            data: Data to update

        Returns:
            True if update successful, False otherwise
        """
        pass

    @abstractmethod
    def update_many(
        self,
        table: str,
        filters: dict[str, Any],
        data: dict[str, Any]
    ) -> int:
        """
        Update multiple records matching filters.

        Args:
            table: Table/collection name
            filters: Dictionary of field-value pairs to match
            data: Data to update

        Returns:
            Number of records updated
        """
        pass

    # DELETE operations
    @abstractmethod
    def delete(self, table: str, record_id: Any) -> bool:
        """
        Delete a record by ID.

        Args:
            table: Table/collection name
            record_id: ID of the record to delete

        Returns:
            True if deletion successful, False otherwise
        """
        pass

    @abstractmethod
    def delete_many(
        self,
        table: str,
        filters: dict[str, Any]
    ) -> int:
        """
        Delete multiple records matching filters.

        Args:
            table: Table/collection name
            filters: Dictionary of field-value pairs to match

        Returns:
            Number of records deleted
        """
        pass

    # TRANSACTION operations
    @abstractmethod
    def begin_transaction(self) -> None:
        """Begin a transaction."""
        pass

    @abstractmethod
    def commit_transaction(self) -> None:
        """Commit the current transaction."""
        pass

    @abstractmethod
    def rollback_transaction(self) -> None:
        """Rollback the current transaction."""
        pass

    # UTILITY operations
    @abstractmethod
    def table_exists(self, table: str) -> bool:
        """
        Check if a table/collection exists.

        Args:
            table: Table/collection name

        Returns:
            True if table exists, False otherwise
        """
        pass

    @abstractmethod
    def create_table(self, table: str, schema: dict[str, Any]) -> bool:
        """
        Create a table/collection with the specified schema.

        Args:
            table: Table/collection name
            schema: Dictionary defining the table schema

        Returns:
            True if table created successfully, False otherwise
        """
        pass

    @abstractmethod
    def drop_table(self, table: str) -> bool:
        """
        Drop a table/collection.

        Args:
            table: Table/collection name

        Returns:
            True if table dropped successfully, False otherwise
        """
        pass

    def health_check(self) -> dict[str, Any]:
        """
        Perform a health check on the persistence backend.

        Returns:
            Dictionary containing health check results
        """
        return {
            "status": "unknown",
            "connected": self.is_connected(),
            "backend": self.__class__.__name__,
            "connection_string": self.connection_string
        }

    @abstractmethod
    def save_state(self, state: dict[str, Any]) -> bool:
        """Save application state."""
        pass

    @abstractmethod
    def save_trade(self, trade_data: dict[str, Any]) -> str:
        """Save a trade record."""
        pass


# Specialized persistence ports for different data types

class StatePersistencePort(PersistencePort):
    """Persistence port specifically for application state (JSON)."""

    @abstractmethod
    def save_state(self, state: dict[str, Any]) -> bool:
        """Save application state."""
        pass

    @abstractmethod
    def load_state(self) -> dict[str, Any] | None:
        """Load application state."""
        pass

    @abstractmethod
    def delete_state(self) -> bool:
        """Delete application state."""
        pass


class TradePersistencePort(PersistencePort):
    """Persistence port specifically for trade data."""

    @abstractmethod
    def save_trade(self, trade_data: dict[str, Any]) -> str:
        """Save a trade record."""
        pass

    @abstractmethod
    def get_trade(self, trade_id: str) -> dict[str, Any] | None:
        """Get a trade by ID."""
        pass

    @abstractmethod
    def get_trades(
        self,
        symbol: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get trades with optional filtering."""
        pass

    @abstractmethod
    def update_trade(self, trade_id: str, trade_data: dict[str, Any]) -> bool:
        """Update a trade record."""
        pass


class MarketDataPersistencePort(PersistencePort):
    """Persistence port specifically for market data."""

    @abstractmethod
    def save_market_data(
        self,
        symbol: str,
        data: dict[str, Any],
        timestamp: datetime | None = None
    ) -> bool:
        """Save market data point."""
        pass

    @abstractmethod
    def get_market_data(
        self,
        symbol: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Get market data for a symbol."""
        pass

    @abstractmethod
    def get_latest_market_data(self, symbol: str) -> dict[str, Any] | None:
        """Get the latest market data point for a symbol."""
        pass


class CSVPersistencePort(PersistencePort):
    """Persistence port specifically for CSV file operations."""

    @abstractmethod
    def append_row(self, file_path: str | Path, row: dict[str, Any]) -> bool:
        """Append a row to a CSV file."""
        pass

    @abstractmethod
    def write_rows(self, file_path: str | Path, rows: list[dict[str, Any]], headers: list[str]) -> bool:
        """Write rows to a CSV file."""
        pass

    @abstractmethod
    def read_rows(self, file_path: str | Path) -> list[dict[str, Any]]:
        """Read rows from a CSV file."""
        pass

    @abstractmethod
    def file_exists(self, file_path: str | Path) -> bool:
        """Check if a CSV file exists."""
        pass
