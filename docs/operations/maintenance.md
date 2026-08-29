# Weekly Maintenance Procedure

## Schedule
- **Day**: Every Sunday
- **Time**: 15:30 IST (after market close)
- **Duration**: ~30 minutes

## Maintenance Tasks

### 1. Database Maintenance
```bash
# Vacuum trades database
sqlite3 db/trades.db "VACUUM;"
sqlite3 db/trades.db "PRAGMA integrity_check;"

# Vacuum event store
sqlite3 db/event_store.db "VACUUM;"
sqlite3 db/event_store.db "PRAGMA integrity_check;"

# Vacuum ML tracker
sqlite3 db/ml_tracker.db "VACUUM;"
sqlite3 db/ml_tracker.db "PRAGMA integrity_check;"
```

### 2. Log Rotation
```bash
# Archive old logs
tar -czf logs/archive/trading_$(date +%Y%m%d).tar.gz logs/trading.log.*
rm logs/trading.log.*
```

### 3. Backup
```bash
# Run backup script
python scripts/backup.py --all
```
Verify backup files in `backups/` directory.

### 4. Config Validation
```bash
# Validate current config
python -m core.config_validator

# Generate schema report
python scripts/generate_config_schemas.py
```

### 5. Performance Review
```bash
# Run health check
python -m core.health_checker

# Check ML model accuracy
python -m core.ml_performance_tracker --report

# Run sensitivity analysis
python -m core.sensitivity_analyzer --days 30
```

### 6. Update System
```bash
# Pull latest changes
git pull

# Install dependency updates
pip install -r requirements.txt --upgrade

# Run test suite
python -m pytest tests/ -q --tb=short
```

## Maintenance Checklist
- [ ] Database integrity verified
- [ ] Logs rotated and archived
- [ ] Backups completed
- [ ] Config validated
- [ ] ML model accuracy checked
- [ ] Performance reviewed
- [ ] System updated
- [ ] Tests pass
