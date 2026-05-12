#!/usr/bin/env python3
"""
Script to migrate hardcoded secrets in config.json to environment variable references.
This script will:
1. Replace hardcoded secret values with empty strings in config.json
2. Create a template .env.example file with all the required environment variables
3. Generate a migration guide
"""

import json
import os
from pathlib import Path

def migrate_secrets():
    config_path = Path("/mnt/d/TRADING_APP/12MAY2026/OPB_FINAL_MT/config.json")

    # Read the current config
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Define secrets that should be moved to environment variables
    secrets_mapping = {
        "BOT_TOKEN": "OPBUYING_BOT_TOKEN",
        "CHAT_ID": "OPBUYING_CHAT_ID",
        "BROKER_CONFIG.api_key": "OPBUYING_BROKER_API_KEY",
        "BROKER_CONFIG.access_token": "OPBUYING_BROKER_ACCESS_TOKEN",
        "BROKER_CONFIG.user_id": "OPBUYING_BROKER_USER_ID",
        "BROKER_CONFIG.password": "OPBUYING_BROKER_PASSWORD",
        "BROKER_CONFIG.totp_key": "OPBUYING_BROKER_TOTP_KEY",
        "BROKER_CONFIG.refresh_token": "OPBUYING_BROKER_REFRESH_TOKEN",
        "BROKER_CONFIG.client_id": "OPBUYING_BROKER_CLIENT_ID",
        "BROKER_CONFIG.secret": "OPBUYING_BROKER_SECRET"
    }

    # Track what we're changing for the report
    changes_made = []

    # Handle top-level secrets
    for config_key, env_var in [("BOT_TOKEN", "OPBUYING_BOT_TOKEN"),
                                ("CHAT_ID", "OPBUYING_CHAT_ID")]:
        if config.get(config_key):
            changes_made.append(f"{config_key} -> {env_var}")
            # Keep the key but we'll document it should come from env vars

    # Handle broker config secrets
    broker_config = config.get("BROKER_CONFIG", {})
    broker_secrets = {
        "api_key": "OPBUYING_BROKER_API_KEY",
        "access_token": "OPBUYING_BROKER_ACCESS_TOKEN",
        "user_id": "OPBUYING_BROKER_USER_ID",
        "password": "OPBUYING_BROKER_PASSWORD",
        "totp_key": "OPBUYING_BROKER_TOTP_KEY",
        "refresh_token": "OPBUYING_BROKER_REFRESH_TOKEN",
        "client_id": "OPBUYING_BROKER_CLIENT_ID",
        "secret": "OPBUYING_BROKER_SECRET"
    }

    for broker_key, env_var in broker_secrets.items():
        if broker_config.get(broker_key):
            changes_made.append(f"BROKER_CONFIG.{broker_key} -> {env_var}")
            # We'll clear the value but keep the key structure

    # Create backup of original
    backup_path = config_path.with_suffix('.json.secrets_backup')
    with open(backup_path, 'w') as f:
        json.dump(config, f, indent=4)

    # Clear the secret values (but keep the keys for structure)
    config["BOT_TOKEN"] = ""
    config["CHAT_ID"] = ""

    for key in broker_secrets.keys():
        if key in config["BROKER_CONFIG"]:
            config["BROKER_CONFIG"][key] = ""

    # Write the updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

    # Create .env.example file
    env_example_path = Path("/mnt/d/TRADING_APP/12MAY2026/OPB_FINAL_MT/.env.example")
    env_vars = [
        "# OPBuying Trading Platform Environment Variables",
        "# Copy this file to .env and fill in your actual values",
        "",
        "# Telegram Configuration",
        "OPBUYING_BOT_TOKEN=your_telegram_bot_token_here",
        "OPBUYING_CHAT_ID=your_telegram_chat_id_here",
        "",
        "# Broker Configuration (Kite/Zerodha example)",
        "OPBUYING_BROKER_API_KEY=your_kite_api_key_here",
        "OPBUYING_BROKER_ACCESS_TOKEN=your_kite_access_token_here",
        "OPBUYING_BROKER_USER_ID=your_kite_user_id_here",
        "OPBUYING_BROKER_PASSWORD=your_kite_password_here",
        "OPBUYING_BROKER_TOTP_KEY=your_kite_totp_key_here",
        "OPBUYING_BROKER_REFRESH_TOKEN=your_kite_refresh_token_here",
        "OPBUYING_BROKER_CLIENT_ID=your_kite_client_id_here",
        "OPBUYING_BROKER_SECRET=your_kite_secret_here",
        "",
        "# Optional: Override other config values",
        "# OPBUYING_BASE_CAPITAL=10000",
        "# OPBUYING_EXECUTION_MODE=AUTO",
    ]

    with open(env_example_path, 'w') as f:
        f.write('\n'.join(env_vars))

    # Create migration guide
    guide_path = Path("/mnt/d/TRADING_APP/12MAY2026/OPB_FINAL_MT/SECRETS_MIGRATION_GUIDE.md")
    with open(guide_path, 'w') as f:
        f.write("# Secrets Migration Guide\n\n")
        f.write("## What was changed\n\n")
        f.write("The following hardcoded secrets have been moved to environment variables:\n\n")
        for change in changes_made:
            f.write(f"- {change}\n")

        f.write("\n## How to use\n\n")
        f.write("1. Copy `.env.example` to `.env`:\n   ```bash\n   cp .env.example .env\n   ```\n\n")
        f.write("2. Edit `.env` and fill in your actual values for:\n")
        f.write("   - Telegram bot token and chat ID\n")
        f.write("   - Broker API credentials (for your chosen broker)\n\n")
        f.write("3. The system will automatically load these environment variables through the secure configuration system.\n\n")
        f.write("## Security Notes\n\n")
        f.write("- Never commit `.env` to version control\n")
        f.write("- The `.env.example` file is safe to commit as it contains only placeholder values\n")
        f.write("- For production deployment, consider using a proper secret management system\n")
        f.write("- Environment variables take precedence over config.json values\n\n")
        f.write("## Backwards Compatibility\n\n")
        f.write("The system maintains backwards compatibility:\n")
        f.write("- If environment variables are not set, it will fall back to config.json values (which are now empty)\n")
        f.write("- Existing configurations that rely on config.json will need to be migrated to use environment variables\n")

    print(f"Migration complete! Made {len(changes_made)} changes.")
    print(f"Backup saved to: {backup_path}")
    print(f"Environment example created: {env_example_path}")
    print(f"Migration guide created: {guide_path}")

if __name__ == "__main__":
    migrate_secrets()