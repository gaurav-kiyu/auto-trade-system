"""Tests for core.utils_numeric - shared numeric coercion helpers."""

from __future__ import annotations

import math

from core.utils_numeric import safe_float, safe_num


class TestSafeFloat:
    """Tests for safe_float() - core numeric coercion."""

    def test_none_returns_default(self) -> None:
        assert safe_float(None) == 0.0
        assert safe_float(None, 42.0) == 42.0

    def test_valid_numbers(self) -> None:
        assert safe_float(0) == 0.0
        assert safe_float(42) == 42.0
        assert safe_float(3.14) == 3.14
        assert safe_float(-1.5) == -1.5

    def test_string_numbers(self) -> None:
        assert safe_float("3.14") == 3.14
        assert safe_float("42") == 42.0
        assert safe_float("-0.5") == -0.5

    def test_nan_returns_default(self) -> None:
        assert safe_float(float("nan")) == 0.0
        assert safe_float(math.nan, 100.0) == 100.0

    def test_inf_returns_default(self) -> None:
        assert safe_float(float("inf")) == 0.0
        assert safe_float(float("-inf")) == 0.0

    def test_string_surrounded_by_whitespace(self) -> None:
        assert safe_float("  3.14  ") == 3.14
        assert safe_float("  42  ") == 42.0

    def test_invalid_strings_returns_default(self) -> None:
        assert safe_float("abc") == 0.0
        assert safe_float("") == 0.0
        assert safe_float("1.2.3") == 0.0

    def test_zero_returns_zero(self) -> None:
        assert safe_float(0) == 0.0
        assert safe_float(0.0) == 0.0
        assert safe_float("0") == 0.0

    def test_bool_coerces_to_float(self) -> None:
        assert safe_float(True) == 1.0
        assert safe_float(False) == 0.0

    def test_large_values(self) -> None:
        assert safe_float(1e6) == 1_000_000.0
        assert safe_float(1e-6) == 0.000001


class TestSafeNum:
    """Tests for safe_num() - legacy alias for safe_float."""

    def test_is_alias_of_safe_float(self) -> None:
        assert safe_num(42) == safe_float(42)
        assert safe_num(None) == safe_float(None)
        assert safe_num("abc") == safe_float("abc")
        assert safe_num(float("nan")) == safe_float(float("nan"))

    def test_none_returns_default(self) -> None:
        assert safe_num(None) == 0.0
        assert safe_num(None, 99.9) == 99.9

    def test_valid_inputs(self) -> None:
        assert safe_num(3.14) == 3.14
        assert safe_num("3.14") == 3.14
        assert safe_num(0) == 0.0

    def test_invalid_inputs(self) -> None:
        assert safe_num("not_a_number") == 0.0
        assert safe_num([]) == 0.0
        assert safe_num({}) == 0.0
