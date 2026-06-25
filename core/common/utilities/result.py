"""
Result Type Utilities

This module provides a functional Result type for error handling,
similar to Rust's Result type or Either in functional programming.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar('T')
E = TypeVar('E')


@dataclass(frozen=True)
class Result(Generic[T, E]):
    """
    A functional Result type representing either success (Ok) or failure (Err).

    This is similar to Rust's Result<T, E> type.
    """
    _value: T | None = None
    _error: E | None = None

    def __post_init__(self):
        """Ensure that we don't have both _error and _value set to non-None values."""
        if self._error is not None and self._value is not None:
            raise ValueError("Result cannot have both value and error")

    @classmethod
    def ok(cls, value: T) -> Result[T, E]:
        """Create a successful Result."""
        return cls(_value=value, _error=None)

    @classmethod
    def err(cls, error: E) -> Result[T, E]:
        """Create a failed Result."""
        return cls(_value=None, _error=error)

    @property
    def is_success(self) -> bool:
        """Check if the Result is a success."""
        return self._error is None

    @property
    def is_failure(self) -> bool:
        """Check if the Result is a failure."""
        return self._error is not None

    def unwrap(self) -> T:
        """
        Get the value from a successful Result.

        Raises:
            ValueError: If the Result is a failure
        """
        if self.is_failure:
            raise ValueError(f"Called unwrap() on an Err value: {self._error}")
        return self._value  # type: ignore

    def unwrap_err(self) -> E:
        """
        Get the error from a failed Result.

        Raises:
            ValueError: If the Result is a success
        """
        if self.is_success:
            raise ValueError(f"Called unwrap_err() on an Ok value: {self._value}")
        return self._error  # type: ignore

    def unwrap_or(self, default: T) -> T:
        """
        Get the value from a successful Result, or return a default.

        Args:
            default: The default value to return if Result is a failure

        Returns:
            The value if successful, otherwise the default
        """
        return self._value if self.is_success else default

    def unwrap_or_else(self, f: Callable[[E], T]) -> T:
        """
        Get the value from a successful Result, or compute a default from the error.

        Args:
            f: A function that takes the error and returns a default value

        Returns:
            The value if successful, otherwise f(error)
        """
        return self._value if self.is_success else f(self._error)  # type: ignore

    def map(self, f: Callable[[T], Any]) -> Result[Any, E]:
        """
        Map a function over the success value.

        Args:
            f: A function to apply to the success value

        Returns:
            A new Result with the mapped value, or the same error
        """
        if self.is_failure:
            return self  # type: ignore
        return Result.ok(f(self._value))  # type: ignore

    def map_err(self, f: Callable[[E], Any]) -> Result[T, Any]:
        """
        Map a function over the error value.

        Args:
            f: A function to apply to the error value

        Returns:
            A new Result with the mapped error, or the same value
        """
        if self.is_success:
            return self  # type: ignore
        return Result.err(f(self._error))  # type: ignore

    def and_then(self, f: Callable[[T], Result[Any, E]]) -> Result[Any, E]:
        """
        Chain a function that returns a Result over the success value.

        Args:
            f: A function that takes the success value and returns a Result

        Returns:
            The result of applying f to the success value, or the original error
        """
        if self.is_failure:
            return self  # type: ignore
        return f(self._value)  # type: ignore

    def or_else(self, f: Callable[[E], Result[T, Any]]) -> Result[T, Any]:
        """
        Chain a function that returns a Result over the error value.

        Args:
            f: A function that takes the error and returns a Result

        Returns:
            The original success value, or the result of applying f to the error
        """
        if self.is_success:
            return self  # type: ignore
        return f(self._error)  # type: ignore

    def __str__(self) -> str:
        """String representation of the Result."""
        if self.is_success:
            return f"Ok({self._value})"
        return f"Err({self._error})"

    def __repr__(self) -> str:
        """Detailed string representation of the Result."""
        return self.__str__()


# Convenience aliases for common usage
Success = Result.ok
Failure = Result.err

# Type aliases for common Result types
StringResult = Result[str, str]
IntResult = Result[int, str]
BoolResult = Result[bool, str]


__all__ = [
    "BoolResult",
    "E",
    "Failure",
    "IntResult",
    "Result",
    "StringResult",
    "Success",
    "T",
]

