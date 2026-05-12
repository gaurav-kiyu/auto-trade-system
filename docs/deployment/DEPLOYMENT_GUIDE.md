# Deployment Guide: Refactored NSE Index Options Trading Platform

## Overview
This guide provides instructions for deploying the refactored NSE index options trading platform. The deployment follows the clean architecture principles and maintains all the non-negotiable constraints:
- Self-hosted first
- Vendor independent
- Open-source/free stack preferred
- Local deployment fully functional
- No mandatory cloud dependencies
- No proprietary managed AI services
- No SaaS lock-in

## Prerequisites

### System Requirements
- Operating System: Linux (Ubuntu 20.04+ recommended), Windows 10+, or macOS
- Python: 3.10 through 3.19 (enforced at startup)
- Memory: Minimum 4GB RAM (8GB+ recommended)
- Storage: Minimum 10GB free space
- Network: Internet connectivity for initial setup and market data (optional for offline mode)

### Software Dependencies
The platform has two dependency tiers:

#### Core Dependencies (Required)
```
jsonschema>=4.20
requests>=2.31.0
yfinance>=0.2.36
pandas>=2.0.0
numpy>=1.24.0
```

#### Optional Dependencies (Enable specific features)
```
# Dashboard server
flask>=3.0.0
flask-socketio>=5.3.0

# Phase 5 — ML Signal Classifier
lightgbm>=4.0.0
scikit-learn>=1.3.0

# Phase 6 — PDF Report Generator
reportlab>=4.0.0

# v2.44 Item 12 — News Sentinel (RSS feed parsing)
feedparser>=6.0.0

# v2.44 Item 20 — A/B Strategy Tester (Mann-Whitney U significance test)
scipy>=1.11.0

# v2.45 Item 19 — Prometheus metrics export
prometheus-client>=0.20.0

# Live broker execution (optional — NOT needed for paper/manual trading)
# kiteconnect>=5.0.0
# pyotp>=2.9.0
```

## Deployment Methods

### Method 1: Direct Installation (Recommended for Development)

#### Step 1: Clone or Copy the Repository
```bash
# If cloning from git
git clone <repository-url>
cd OPB_FINAL_MT

# If copying existing files
cd /path/to/OPB_FINAL_MT
```

#### Step 2: Set Up Environment Variables (Secrets)
Create a `.env` file in the project root with your secrets (never commit this file):

```bash
# Telegram Bot
OPBUYING_BOT_TOKEN=your_telegram_bot_token_here
OPBUYING_CHAT_ID=your_telegram_chat_id_here

# Broker Credentials (Example for Zerodha Kite)
OPBUYING_KITE_API_KEY=your_kite_api_key_here
OPBUYING_KITE_ACCESS_TOKEN=your_kite_access_token_here
OPBUYING_KITE_USER_ID=your_kite_user_id_here
OPBUYING_KITE_PASSWORD=your_kite_password_here
OPBUYING_KITE_TOTP_KEY=your_kite_totp_key_here

# Optional: Angel Broking
# OPBUYING_ANGEL_API_KEY=your_angel_api_key_here
# OPBUYING_ANGEL_CLIENT_ID=your_angel_client_id_here
# OPBUYING_ANGEL_PASSWORD=your_angel_password_here
# OPBUYING_ANGEL_TOTP_KEY=your_angel_totp_key_here
# OPBUYING_ANGEL_REFRESH_TOKEN=your_angel_refresh_token_here
```

> **Important**: Never commit the `.env` file to version control. The `.gitignore` file should already exclude `*.env` files.

#### Step 3: Install Dependencies
```bash
# Install core dependencies
pip install -r requirements.txt

# Optional: Install development dependencies
pip install -r requirements-dev.txt

# Optional: Install specific feature dependencies as needed
pip install lightgbm scikit-learn reportlab feedparser scipy prometheus-client
```

#### Step 4: Configure the Application
Copy the configuration templates and customize as needed:

```bash
# Copy template configs
cp config/index_config.defaults.json config/config.json
cp config/stock_config.defaults.json config/stock_config.json

# Edit config.json to set your preferences
# Important: Set PAPER_MODE=true for initial testing
```

#### Step 5: Run the Application
```bash
# Paper trading mode (recommended for initial testing)
python index_app/index_trader.py --paper

# Or via module execution
python -m index_app.index_trader --paper

# Live trading mode (only after thorough testing in paper mode)
# NEVER use live trading without extensive paper trading validation
python index_app/index_trader.py
```

### Method 2: Docker Deployment (Recommended for Production)

#### Step 1: Install Docker and Docker Compose
Follow the official Docker installation guide for your operating system.

#### Step 2: Build and Run Using Docker Compose
```bash
# Copy docker configuration files if needed
cp docker-compose.yml.example docker-compose.yml
cp .env.example .env

# Edit .env with your secrets (as described in Method 1, Step 2)

# Build the Docker images
docker compose build

# Start the services
docker compose up -d

# View logs
docker compose logs -f opb

# Stop the services
docker compose down
```

#### Step 3: Docker Configuration Details
The `docker-compose.yml` file defines:
- `opb` service: Main trading application
- Uses multi-stage Dockerfile for minimal image size
- Runs in paper mode by default (safe for testing)
- Exposes web dashboard on port 8765 (if enabled)
- Uses volume mounting for persistent storage:
  - `./data`: SQLite databases and persistent files
  - `./logs`: Application logs
  - `./config`: Configuration files

### Method 3: Manual Deployment (Advanced)

For custom deployment scenarios, you can deploy components individually:

#### Core Application
```bash
# Main trading engine
python index_app/index_trader.py [--paper] [--debug] [--selftest]

# Web dashboard (optional)
python dashboard_server.py

# Backtesting engine
python run_backtest.py

# Analysis tools
python run_analysis.py
```

#### Component Services
Individual services can be run independently for microservices-style deployment:
- Signal generation service
- Risk management service
- Portfolio management service
- Execution service
- Notification service

## Configuration Guide

### Configuration Precedence
The system uses a 4-layer configuration system (in order of precedence):
1. **Defaults**: `index_config.defaults.json` (single source of truth for default values)
2. **Config Files**: `config.json` (user-overridden values)
3. **Local Config**: `config.local.json` (local overrides, not committed to git)
4. **Environment Variables**: `OPBUYING_*` secrets and overrides

### Essential Configuration Keys

#### Trading Parameters
- `BASE_CAPITAL`: Starting capital for paper trading account
- `MAX_DAILY_LOSS`: Maximum daily loss before trading stops (INR)
- `MAX_DRAWDOWN`: Maximum drawdown as percentage (0.0-1.0)
- `PAPER_MODE`: Enable paper trading mode (true/false)
- `EXECUTION_MODE`: LIVE, PAPER, or MANUAL_SIGNAL_ONLY
- `MANUAL_SIGNALS_ONLY`: Enable manual signal only mode

#### Risk Management
- `SL_PCT`: Stop loss percentage
- `TARGET_PCT`: Target profit percentage
- `TRAIL_PCT`: Trailing stop percentage
- `PORTFOLIO_MAX_SL_RISK_PCT`: Maximum portfolio risk per stop loss
- `MAX_OPEN`: Maximum number of concurrent open positions
- `MAX_TRADES_DAY`: Maximum trades per day

#### Technical Analysis
- `SIGNAL_THRESHOLD_STRONG`: Minimum signal strength for strong signals
- `SIGNAL_THRESHOLD_MODERATE`: Minimum signal strength for moderate signals
- `SCAN_INTERVAL`: Seconds between market scans

#### ML Configuration
- `ML_CLASSIFIER_ENABLED`: Enable ML signal classifier
- `ML_MIN_TRADES_TO_TRAIN`: Minimum trades before ML training
- `ML_MODEL_PATH`: Path to save/load ML model
- `ML_RETRAIN_INTERVAL_HOURS`: Hours between ML retraining

#### Notifications
- `TELEGRAM_ENABLED`: Enable Telegram notifications
- `BOT_TOKEN`: Telegram bot account token (from env)
- `CHAT_ID`: Telegram chat ID (from env)
- `TELEGRAM_ALERTS_ENABLED`: Enable alert notifications

#### Broker Configuration
- `BROKER_DRIVER`: KITE or ANGEL (or PAPER for paper trading)
- Use `OPBUYING_*` environment variables for all broker secrets

#### Dashboard (Optional)
- `WEB_DASHBOARD_ENABLED`: Enable web dashboard
- `WEB_DASHBOARD_PORT`: Port for web dashboard (default 8765)
- `WEB_DASHBOARD_AUTH_TOKEN`: Authentication token (empty = no auth)

## Security Considerations

### Secret Management
1. **Never store secrets in config files**: All secrets must be in `OPBUYING_*` environment variables
2. **Use .env files for local development**: But ensure they are excluded from version control
3. **Rotate secrets regularly**: Change API keys and tokens periodically
4. **Use separate accounts**: Consider using separate broker accounts for paper vs live trading

### File Permissions
Ensure proper file permissions on sensitive files:
```bash
# Restrict permissions on config files
chmod 600 config.json
chmod 600 config.local.json
chmod 600 .env

# Restrict permissions on database files
chmod 600 data/*.db
chmod 600 trades.db
chmod 600 trade_journal.db
```

### Network Security
1. **Firewall rules**: Restrict outbound connections to only necessary services
2. **API rate limiting**: Respect broker API rate limits to avoid bans
3. **Secure connections**: Ensure all API connections use HTTPS/WSS

## Monitoring and Observability

### Logging
The system uses structured logging with the following levels:
- `DEBUG`: Detailed diagnostic information
- `INFO`: General operational information
- `WARNING`: Potential issues that don't prevent operation
- `ERROR`: Error conditions that may affect operation
- `CRITICAL`: Severe errors that may require intervention

Log files are rotated automatically:
- Maximum size: 50 MB per file
- Compression: gzip
- Retention: Configurable number of files

### Metrics (if prometheus-client installed)
When `metrics_enabled=true` in config:
- Endpoint: `http://localhost:9090/metrics`
- Metrics include:
  - Trading performance (win rate, P&L, Sharpe ratio)
  - Signal generation rates and quality
  - Order execution statistics
  - System resource usage (CPU, memory)
  - Error rates and failure counts

### Health Checks
The system provides several health check mechanisms:
1. **Built-in health checker**: `python -m core.health_checker`
2. **Web dashboard health endpoint** (if enabled): `GET /health`
3. **Startup validation**: Runs during application initialization
4. **Runtime monitoring**: Continuous checking of critical components

## Backup and Recovery

### What to Backup
1. **Configuration**: `config/` directory (excluding `.env`)
2. **Data**: `data/` directory (SQLite databases)
3. **Logs**: `logs/` directory (for audit trails)
4. **Custom files**: Any custom templates or scripts you've added

### Backup Procedure
```bash
# Create backup timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Backup configuration (exclude .env)
tar -czf config_backup_$TIMESTAMP.tar.gz config/ --exclude="*.env"

# Backup data directory
tar -czf data_backup_$TIMESTAMP.tar.gz data/

# Backup logs (optional, can be large)
tar -czf logs_backup_$TIMESTAMP.tar.gz logs/
```

### Recovery Procedure
1. Stop the application
2. Restore configuration files from backup
3. Restore data files from backup
4. Verify file permissions
5. Restart the application
6. Validate system functionality

## Troubleshooting

### Common Issues

#### 1. "ModuleNotFoundError" for dependencies
**Solution**: Install missing dependencies
```bash
pip install <missing-module>
# or
pip install -r requirements.txt
```

#### 2. Permission errors on files/directories
**Solution**: Fix file permissions
```bash
chmod 600 config.json
chmod 600 data/*.db
chmod 600 logs/*.log
```

#### 3. Broker connection failures
**Solutions**:
- Verify API keys and tokens in environment variables
- Check internet connectivity
- Verify broker service status
- Check for API rate limiting or bans
- Ensure correct broker driver is selected

#### 4. "Address already in use" for web dashboard
**Solutions**:
- Change `web_dashboard_port` in config
- Stop the process using the conflicting port
- Use `sudo lsof -i :<port>` to find conflicting process

#### 5. Poor performance or high latency
**Solutions**:
- Check system resource usage (top/htop)
- Verify sufficient RAM is available
- Check for disk I/O bottlenecks
- Consider reducing scan frequency
- Enable caching where available

### Diagnostic Commands
```bash
# Run system health check
python -m core.health_checker

# Run in self-test mode
python index_app/index_trader.py --selftest

# Validate configuration
python -m core.config_bootstrap --validate

# Check Python version compliance
python index_app/index_trader.py --check-python-version

# Get current configuration (secrets redacted)
python index_app/index_trader.py --print-config
```

## Performance Tuning

### For Low-Latency Requirements
1. **Reduce scan interval**: Decrease `SCAN_INTERVAL` in config (minimum recommended: 5 seconds)
2. **Enable caching**: Use built-in caching for technical indicators and market data
3. **Optimize data structures**: The refactored system uses efficient data structures
4. **Minimize logging in production**: Reduce log level to WARNING or ERROR in production
5. **Use asynchronous operations**: The system uses async patterns where beneficial

### For Resource-Constrained Environments
1. **Disable unused features**: Turn off ML, dashboard, notifications if not needed
2. **Reduce history limits**: Decrease the number of historical candles stored
3. **Limit concurrent operations**: Reduce the number of simultaneous scans
4. **Use lightweight database**: SQLite is already optimized for low resource usage
5. **Enable pagination**: For large data sets, use pagination in queries

## Upgrade Procedure

### From Previous Versions
1. **Backup current installation** (as described in Backup section)
2. **Review change logs**: Check `ARCHITECTURE_REFACOR_PLAN.md` and `REFCTORING_PROGRESS_SUMMARY.md`
3. **Install new dependencies**: `pip install -r requirements.txt`
4. **Migrate configuration**: Ensure `index_config.defaults.json` is present and valid
5. **Run tests**: Execute the test suite to verify functionality
6. **Start in paper mode**: Validate behavior before switching to live mode
7. **Monitor closely**: Watch logs and metrics for any anomalies

### Rollback Plan
If issues arise after upgrade:
1. Stop the new version
2. Restore configuration from backup
3. Restore data from backup
4. Restart the previous version
5. Investigate issues in isolation

## Development and Customization

### Adding New Features
1. **Follow the domain structure**: Add new functionality to appropriate domains
2. **Use dependency injection**: Depend on interfaces, not concrete implementations
3. **Add unit tests**: Ensure new functionality is testable
4. **Update documentation**: Keep API and user documentation current
5. **Follow coding standards**: Maintain consistency with existing code

### Contributing Guidelines
1. **Fork the repository**
2. **Create feature branches**
3. **Write tests first**
4. **Follow the existing code style**
5. **Update documentation**
6. **Submit pull requests with clear descriptions**

## Compliance and Validation

### Pre-Production Checklist
Before deploying to production with real capital:

1. [ ] Complete at least 30 days of successful paper trading
2. [ ] Validate all risk limits work correctly
3. [ ] Verify order execution accuracy with historical data
4. [ ] Test all notification channels
5. [ ] Verify backup and recovery procedures
6. [ ] Test disaster recovery scenarios
7. [ ] Validate all configuration options
8. [ ] Run full test suite: `python -m pytest tests/ -v`
9. [ ] Perform stress testing with simulated market data
10. [ ] Review all security considerations
11. [ ] Ensure monitoring and alerting are functional
12. [ ] Document all customizations and deviations from baseline

### Ongoing Validation
- Weekly: Run health checks and validate backups
- Monthly: Review performance metrics and adjust parameters
- Quarterly: Full system test and security review
- Annually: Complete system rebuild and validation

## Support and Resources

### Documentation
- `CLAUDE.md`: Comprehensive project documentation
- `SETUP_AND_TRADING_GUIDE.md`: User guide for setup and trading
- `ARCHITECTURE_REFACOR_PLAN.md`: Technical architecture details
- Individual module docstrings: API documentation

### Community
- Issues: Use GitHub issue tracker for bug reports and feature requests
- Discussions: Technical questions and usage discussions
- Wiki: Additional guides and tutorials (if available)

### Professional Support
For production deployments requiring SLAs or custom development:
- Consider engaging with experienced Python developers familiar with financial systems
- Ensure any third-party support understands the constraints of self-hosted, vendor-independent deployment
- Verify that any support maintains the open-source nature of the platform

## License and Distribution

This platform is provided under an open-source license. See the `LICENSE` file for specific terms.

**Remember**: You are responsible for ensuring compliance with all applicable financial regulations in your jurisdiction when using this platform for actual trading. This guide provides technical deployment instructions only - financial regulatory compliance is your responsibility.

---

*Last Updated: $(date)*  
*Version: Refactored Clean Architecture Release*