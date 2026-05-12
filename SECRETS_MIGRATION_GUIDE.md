# Secrets Migration Guide

## What was changed

The following hardcoded secrets have been moved to environment variables:


## How to use

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and fill in your actual values for:
   - Telegram bot token and chat ID
   - Broker API credentials (for your chosen broker)

3. The system will automatically load these environment variables through the secure configuration system.

## Security Notes

- Never commit `.env` to version control
- The `.env.example` file is safe to commit as it contains only placeholder values
- For production deployment, consider using a proper secret management system
- Environment variables take precedence over config.json values

## Backwards Compatibility

The system maintains backwards compatibility:
- If environment variables are not set, it will fall back to config.json values (which are now empty)
- Existing configurations that rely on config.json will need to be migrated to use environment variables
