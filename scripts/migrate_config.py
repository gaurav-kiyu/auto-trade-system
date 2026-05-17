import json

with open('config.json') as f:
    flat = json.load(f)

v2 = {
    'thresholds': {
        'early': 65,
        'strong': flat.get('STRONG_THRESHOLD', 75),
        'rsi_overbought': flat.get('RSI_OVERBOUGHT', 70),
        'rsi_oversold': flat.get('RSI_OVERSOLD', 30),
        'vol_ratio_min': flat.get('VOL_RATIO_MIN', 1.2),
        'ai_threshold': flat.get('AI_THRESHOLD', 70),
        'iv_spike_threshold': flat.get('IV_SPIKE_THRESHOLD', 60.0),
        'atr_min_threshold': flat.get('ATR_MIN_THRESHOLD', 0.5)
    },
    'risk': {
        'max_daily_loss': flat.get('MAX_DAILY_LOSS', -400),
        'max_drawdown': flat.get('MAX_DRAWDOWN', 0.3),
        'daily_target': flat.get('DAILY_TARGET', 400),
        'risk_mode': flat.get('RISK_MODE', 'FIXED'),
        'risk_fixed_amount': flat.get('RISK_FIXED_AMOUNT', 90),
        'risk_per_trade': flat.get('RISK_PER_TRADE', 0.03),
        'lot_pct': flat.get('MAX_LOT_CAPITAL_PCT', 0.6),
        'max_open': flat.get('MAX_OPEN', 1),
        'max_trades_day': flat.get('MAX_TRADES_DAY', 2),
        'brokerage_per_trade': flat.get('BROKERAGE_PER_TRADE', 40)
    },
    'features': {
        'enable_ai': False,
        'enable_auto': flat.get('EXECUTION_MODE', 'MANUAL') == 'AUTO',
        'execution_mode': flat.get('EXECUTION_MODE', 'MANUAL'),
        'manual_signals_only': flat.get('MANUAL_SIGNALS_ONLY', True),
        'data_cross_validate': flat.get('DATA_CROSS_VALIDATE', True)
    },
    'broker': {
        'name': flat.get('BROKER_NAME', 'My Broker'),
        'driver': flat.get('BROKER_DRIVER', 'GENERIC'),
        'api_enabled': flat.get('BROKER_API_ENABLED', False)
    },
    'timing': {
        'scan_interval': flat.get('SCAN_INTERVAL', 30),
        'cooldown': flat.get('COOLDOWN', 300),
        'signal_max_age': flat.get('SIGNAL_MAX_AGE', 65),
        'max_position_age': flat.get('MAX_POSITION_AGE', 120),
        'summary_interval': flat.get('SUMMARY_INTERVAL', 600)
    },
    'vix': {
        'halt_threshold': flat.get('VIX_HALT_THRESHOLD', 30.0),
        'block_threshold': flat.get('VIX_BLOCK_THRESHOLD', 40.0)
    },
    'legacy_flat': {k: v for k, v in flat.items() if k not in ['BOT_TOKEN', 'CHAT_ID'] and not isinstance(v, dict)}
}

# Preserve nested legacy dicts
v2['index_map'] = flat.get('INDEX_MAP', {})
v2['data_provider_enabled'] = flat.get('DATA_PROVIDER_ENABLED', {})
v2['broker_config'] = flat.get('BROKER_CONFIG', {})

with open('config_v2.json', 'w') as f:
    json.dump(v2, f, indent=2)

print('config_v2.json created successfully.')
