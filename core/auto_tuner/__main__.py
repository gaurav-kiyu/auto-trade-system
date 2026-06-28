"""
CLI entry point for the auto-tuner.

Allows: python -m core.auto_tuner --days 30 --json
"""

from core.auto_tuner.tuner import _cli

_cli()
