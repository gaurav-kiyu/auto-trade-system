"""
Input Validation Module

This module provides comprehensive input validation for all external inputs to prevent
injection attacks, malformed data, and other security vulnerabilities.
"""

from __future__ import annotations

import re
import html
from typing import Any, Dict, List, Optional, Pattern, Union
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Exception raised when input validation fails."""
    pass


class ValidationRule:
    """Base class for validation rules."""

    def __init__(self, description: str = ""):
        self.description = description

    def validate(self, value: Any) -> bool:
        """Validate the given value. Returns True if valid, False otherwise."""
        raise NotImplementedError

    def error_message(self) -> str:
        """Return an error message for when validation fails."""
        return f"Validation failed: {self.description}"


class RequiredRule(ValidationRule):
    """Ensures the value is not None or empty."""

    def __init__(self):
        super().__init__("Value is required")

    def validate(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        if isinstance(value, (list, dict, set)) and len(value) == 0:
            return False
        return True


class TypeRule(ValidationRule):
    """Ensures the value is of a specific type."""

    def __init__(self, expected_type: Union[type, tuple]):
        if isinstance(expected_type, type):
            type_name = expected_type.__name__
        else:
            # Handle tuple of types
            type_names = [t.__name__ for t in expected_type]
            type_name = " or ".join(type_names)
        super().__init__(f"Must be of type {type_name}")
        self.expected_type = expected_type

    def validate(self, value: Any) -> bool:
        return isinstance(value, self.expected_type)


class RegexRule(ValidationRule):
    """Ensures the value matches a specific regex pattern."""

    def __init__(self, pattern: Union[str, Pattern], description: str = None):
        if isinstance(pattern, str):
            pattern = re.compile(pattern)
        super().__init__(description or f"Must match pattern: {pattern.pattern}")
        self.pattern = pattern

    def validate(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(self.pattern.match(value))


class LengthRule(ValidationRule):
    """Ensures the value length is within specified bounds."""

    def __init__(self, min_length: int = 0, max_length: int = None):
        if max_length is None:
            super().__init__(f"Minimum length: {min_length}")
        else:
            super().__init__(f"Length must be between {min_length} and {max_length}")
        self.min_length = min_length
        self.max_length = max_length

    def validate(self, value: Any) -> bool:
        if not isinstance(value, (str, list, tuple, dict, set)):
            return False
        length = len(value)
        if length < self.min_length:
            return False
        if self.max_length is not None and length > self.max_length:
            return False
        return True


class RangeRule(ValidationRule):
    """Ensures the value is within a specific numeric range."""

    def __init__(self, min_value: Union[int, float] = None, max_value: Union[int, float] = None):
        if min_value is None and max_value is None:
            super().__init__("No range specified")
        elif min_value is None:
            super().__init__(f"Maximum value: {max_value}")
        elif max_value is None:
            super().__init__(f"Minimum value: {min_value}")
        else:
            super().__init__(f"Value must be between {min_value} and {max_value}")
        self.min_value = min_value
        self.max_value = max_value

    def validate(self, value: Any) -> bool:
        if not isinstance(value, (int, float)):
            return False
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value > self.max_value:
            return False
        return True


class ChoiceRule(ValidationRule):
    """Ensures the value is one of the allowed choices."""

    def __init__(self, choices: List[Any]):
        super().__init__(f"Must be one of: {', '.join(map(str, choices))}")
        self.choices = set(choices)

    def validate(self, value: Any) -> bool:
        return value in self.choices


class EmailRule(ValidationRule):
    """Ensures the value is a valid email address."""

    def __init__(self):
        super().__init__("Must be a valid email address")
        # Simple email regex - for production, consider using a more robust validation
        self.pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

    def validate(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(self.pattern.match(value))


class URLRule(ValidationRule):
    """Ensures the value is a valid URL."""

    def __init__(self, schemes: List[str] = None):
        if schemes is None:
            schemes = ['http', 'https']
        super().__init__(f"Must be a valid URL with schemes: {', '.join(schemes)}")
        # Simple URL validation - for production, consider using urllib.parse or a library
        scheme_part = '|'.join(schemes)
        self.pattern = re.compile(
            rf'^(?:{scheme_part})://'  # scheme
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
            r'localhost|'  # localhost
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
            r'(?::\d+)?'  # port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    def validate(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(self.pattern.match(value))


@dataclass
class ValidationResult:
    """Result of a validation operation."""
    is_valid: bool
    value: Any = None
    error_message: str = ""
    validated_fields: Dict[str, Any] = None

    def __post_init__(self):
        if self.validated_fields is None:
            self.validated_fields = {}


class Validator:
    """Main validator class that applies multiple rules to a value."""

    def __init__(self, *rules: ValidationRule):
        self.rules = list(rules)

    def validate(self, value: Any, field_name: str = "value") -> ValidationResult:
        """
        Validate a value against all rules.

        Args:
            value: The value to validate
            field_name: Name of the field being validated (for error messages)

        Returns:
            ValidationResult indicating success or failure
        """
        for rule in self.rules:
            if not rule.validate(value):
                error_msg = f"Field '{field_name}': {rule.error_message()}"
                logger.warning(f"Input validation failed: {error_msg}")
                return ValidationResult(
                    is_valid=False,
                    error_message=error_msg
                )

        return ValidationResult(
            is_valid=True,
            value=value,
            validated_fields={field_name: value}
        )

    def validate_dict(self, data: Dict[str, Any], field_validators: Dict[str, 'Validator']) -> ValidationResult:
        """
        Validate a dictionary against field-specific validators.

        Args:
            data: Dictionary to validate
            field_validators: Mapping of field names to Validator instances

        Returns:
            ValidationResult with all validated fields or error information
        """
        validated_data = {}
        errors = []

        # Check for required fields that are missing
        for field_name, validator in field_validators.items():
            # Check if any of the validator's rules require the field
            has_required_rule = any(isinstance(rule, RequiredRule) for rule in validator.rules)
            if has_required_rule and field_name not in data:
                errors.append(f"Field '{field_name}': is required")
                continue

            # If field is present, validate it
            if field_name in data:
                result = validator.validate(data[field_name], field_name)
                if result.is_valid:
                    validated_data.update(result.validated_fields)
                else:
                    errors.append(result.error_message)

        # Check for unexpected fields
        expected_fields = set(field_validators.keys())
        actual_fields = set(data.keys())
        unexpected_fields = actual_fields - expected_fields
        if unexpected_fields:
            logger.warning(f"Unexpected fields in input: {unexpected_fields}")
            # Depending on security requirements, you might want to reject unexpected fields
            # For now, we'll just warn but still validate what we can

        if errors:
            return ValidationResult(
                is_valid=False,
                error_message="; ".join(errors)
            )

        return ValidationResult(
            is_valid=True,
            validated_fields=validated_data
        )


# Predefined validators for common input types

# Telegram command validation
TELEGRAM_COMMAND_VALIDATOR = Validator(
    RequiredRule(),
    RegexRule(r'^[a-zA-Z][a-zA-Z0-9_]*$', "Telegram command must start with a letter and contain only letters, numbers, and underscores"),
    LengthRule(max_length=32)
)

# Telegram message text validation (basic)
TELEGRAM_MESSAGE_VALIDATOR = Validator(
    RequiredRule(),
    LengthRule(max_length=4096)  # Telegram message limit
)

# Configuration key validation
CONFIG_KEY_VALIDATOR = Validator(
    RequiredRule(),
    RegexRule(r'^[a-zA-Z][a-zA-Z0-9_]*$', "Configuration key must start with a letter and contain only letters, numbers, and underscores"),
    LengthRule(min_length=1, max_length=64)
)

# Numeric configuration values
POSITIVE_INTEGER_VALIDATOR = Validator(
    TypeRule(int),
    RangeRule(min_value=0)
)

POSITIVE_FLOAT_VALIDATOR = Validator(
    TypeRule(float),
    RangeRule(min_value=0.0)
)

# Percentage values (0-100)
PERCENTAGE_VALIDATOR = Validator(
    TypeRule((int, float)),
    RangeRule(min_value=0.0, max_value=100.0)
)

# Probability values (0-1)
PROBABILITY_VALIDATOR = Validator(
    TypeRule((int, float)),
    RangeRule(min_value=0.0, max_value=1.0)
)

# Symbol validation (for trading instruments)
SYMBOL_VALIDATOR = Validator(
    RequiredRule(),
    RegexRule(r'^[A-Z0-9\^\.&\-]+$', "Symbol must contain only uppercase letters, numbers, and ^ . & -"),
    LengthRule(min_length=1, max_length=20)
)

# Timeframe validation
TIMEFRAME_VALIDATOR = Validator(
    RequiredRule(),
    RegexRule(r'^\d+(m|h|d|w)$', "Timeframe must be in format: number + m(hours|minutes|days|weeks) e.g., 5m, 1h, 1d"),
    LengthRule(min_length=2, max_length=10)
)


def sanitize_html(text: str) -> str:
    """
    Sanitize text for HTML output to prevent XSS attacks.

    Args:
        text: Input text to sanitize

    Returns:
        HTML-escaped string safe for web output
    """
    if not isinstance(text, str):
        text = str(text)
    return html.escape(text)


def sanitize_sql_like_input(text: str) -> str:
    """
    Sanitize input to prevent SQL-like injection (basic protection).
    Note: This is not a replacement for proper parameterized queries.

    Args:
        text: Input text to sanitize

    Returns:
        Sanitized string
    """
    if not isinstance(text, str):
        text = str(text)

    # Basic SQL injection prevention - remove or escape dangerous patterns
    dangerous_patterns = [
        r'(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION)\b',
        r'[\'"]',  # Single and double quotes
        r'--',     # SQL comment
        r'/\\*.*?\\*/',  # Multi-line comment
    ]

    sanitized = text
    for pattern in dangerous_patterns:
        sanitized = re.sub(pattern, '', sanitized)

    return sanitized.strip()


def validate_and_sanitize_telegram_command(command: str) -> str:
    """
    Validate and sanitize a Telegram command.

    Args:
        command: The command string (may or may not include the leading /)

    Returns:
        Sanitized command string (without the leading /)

    Raises:
        ValidationError: If validation fails
    """
    # Remove leading slash if present
    if command.startswith('/'):
        command = command[1:]

    result = TELEGRAM_COMMAND_VALIDATOR.validate(command, "telegram_command")
    if not result.is_valid:
        raise ValidationError(result.error_message)

    # Additional sanitization - only allow alphanumeric and underscore
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '', result.value)
    if not sanitized:
        raise ValidationError("Command contains no valid characters after sanitization")

    return sanitized.lower()  # Normalize to lowercase


def validate_telegram_message(message: str) -> str:
    """
    Validate a Telegram message.

    Args:
        message: The message text

    Returns:
        The validated message

    Raises:
        ValidationError: If validation fails
    """
    result = TELEGRAM_MESSAGE_VALIDATOR.validate(message, "telegram_message")
    if not result.is_valid:
        raise ValidationError(result.error_message)
    return result.value


# Export public interface
__all__ = [
    'ValidationError',
    'ValidationRule',
    'RequiredRule',
    'TypeRule',
    'RegexRule',
    'LengthRule',
    'RangeRule',
    'ChoiceRule',
    'EmailRule',
    'URLRule',
    'ValidationResult',
    'Validator',
    'TELEGRAM_COMMAND_VALIDATOR',
    'TELEGRAM_MESSAGE_VALIDATOR',
    'CONFIG_KEY_VALIDATOR',
    'POSITIVE_INTEGER_VALIDATOR',
    'POSITIVE_FLOAT_VALIDATOR',
    'PERCENTAGE_VALIDATOR',
    'PROBABILITY_VALIDATOR',
    'SYMBOL_VALIDATOR',
    'TIMEFRAME_VALIDATOR',
    'sanitize_html',
    'sanitize_sql_like_input',
    'validate_and_sanitize_telegram_command',
    'validate_telegram_message',
]