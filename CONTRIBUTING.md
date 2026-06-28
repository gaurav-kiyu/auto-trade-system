# Contributing to OPB Index Options Buying Bot

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## How to Contribute

### Reporting Bugs

1. Check the issue tracker for existing reports
2. Include a clear title and description
3. Provide steps to reproduce, expected behavior, and actual behavior
4. Include logs, screenshots, and configuration details

### Suggesting Features

1. Describe the feature and its use case
2. Explain how it aligns with the project's architecture
3. Provide examples of how it would work

### Pull Requests

1. **Branch naming**: Use `feature/<description>` or `fix/<description>` or `release/v<version>`
2. **Pre-implementation check**: Run `python scripts/pre_implementation_check.py --files <your-files>` before committing
3. **Tests**: All new code must include tests. Run `python -m pytest tests/ -q` to verify
4. **Constitution compliance**: Run `python scripts/score_system.py --ci` to verify governance compliance
5. **Dead code**: Run `python scripts/scan_dead_code.py` to ensure no dead code is introduced
6. **Hygiene**: Run `python scripts/hygiene_check.py` to verify repository hygiene

## Development Setup

```bash
# Clone the repository
git clone <repo-url>
cd OPB_FINAL_MT

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/ -q

# Run in paper mode
python index_app/index_trader.py --paper
```

## Code Style

- Follow PEP 8 conventions
- Use type hints on all public functions
- Use `from __future__ import annotations` at the top of all modules
- Write docstrings for all public classes and methods
- Keep functions focused and modular

## Architecture Rules

- All broker API calls must go through `core/adapters/broker_adapters.py`
- Never call Kite/Angel SDK directly from core modules
- Paper mode must never reach a real broker API
- All time checks use `core/datetime_ist.py` — never use `datetime.now()` directly
- New config keys must have safe defaults in `index_config.defaults.json`
- After adding config keys, run `python scripts/generate_config_schemas.py`

## Testing

```bash
# Run all tests
python -m pytest tests/ -q

# Run specific test file
python -m pytest tests/test_<module>.py -v

# Run governance tests
python -m pytest tests/test_constitution.py tests/test_score_system.py -q
```

## Release Process

Releases follow semantic versioning (v2.x.x). See `scripts/release_governance.py` for automated release pipeline.
