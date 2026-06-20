# Infrastructure Inventory

Generated: 2026-06-20

## Infrastructure Modules
- infrastructure\__init__.py
- infrastructure\adapters\__init__.py
- infrastructure\adapters\brokers\kite\__init__.py
- infrastructure\adapters\brokers\kite\adapter.py
- infrastructure\adapters\correlation_id\correlation_id_adapter.py
- infrastructure\adapters\market_data\commodity\__init__.py
- infrastructure\adapters\market_data\commodity\mcx_commodity_adapter.py
- infrastructure\adapters\market_data\currency\__init__.py
- infrastructure\adapters\market_data\currency\cds_currency_adapter.py
- infrastructure\adapters\market_data\equity\__init__.py
- infrastructure\adapters\market_data\equity\nse_equity_adapter.py
- infrastructure\adapters\market_data\nse\adapter.py
- infrastructure\adapters\market_data\websocket\__init__.py
- infrastructure\adapters\market_data\websocket\nse_index_ws_adapter.py
- infrastructure\adapters\market_data\yahoofinance\adapter.py
- infrastructure\adapters\metrics\metrics_adapter.py
- infrastructure\adapters\ml_model\ml_model_adapter.py
- infrastructure\adapters\notifications\email_adapter.py
- infrastructure\adapters\notifications\telegram_adapter.py
- infrastructure\adapters\persistence\sqlite_adapter.py
- infrastructure\config\logging_adapter.py
- infrastructure\config\secure_config.py
- infrastructure\config\secure_config_adapter.py
- infrastructure\market_data\market_data_cache.py
- infrastructure\market_data\reference_data.py
- infrastructure\security\audit_logger.py
- infrastructure\security\credential_storage.py
- infrastructure\security\input_validator.py

## Deployment Artifacts
- Dockerfile
- docker-compose.yml
- Makefile
- supervisord.conf

## CI/CD
- bitbucket-pipelines.yml - Bitbucket CI
- .pre-commit-config.yaml - Pre-commit hooks
- .dockerignore - Docker ignore rules