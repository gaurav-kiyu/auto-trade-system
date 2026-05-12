import re

def refactor_file(file_path, funcs_to_replace):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Ensure FeatureEngine is imported
    if 'FeatureEngine' not in content:
        import_stmt = 'from core.feature_engine import FeatureEngine\n'
        # Add it after 'import time' or similar
        content = re.sub(r'(import time\n)', r'\1' + import_stmt, content)

    for func in funcs_to_replace:
        # Regex to match the function definition and its body
        # This matches 'def func_name(' until the next 'def ' at the same or lesser indentation
        # Actually, simpler: replace the whole function block with the alias
        pattern = re.compile(rf'^def {func}\b.*?(?=\n(?:def |# ═|class |[A-Z_]+ =|$))', re.MULTILINE | re.DOTALL)
        
        # In signal_engine.py, it's mostly top level. 
        # In index_trader.py, it's also top level.
        match = pattern.search(content)
        if match:
            alias = f"{func} = FeatureEngine.{func}\n"
            content = content[:match.start()] + alias + content[match.end():]
            print(f"Replaced {func} in {file_path}")

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

# signal_engine.py
funcs_se = ['get_price', 'get_open', 'get_high', 'get_low', 'get_vwap', 'get_ema', 'get_ema_series', 'ema_trend', 'get_rsi', 'get_macd', 'get_atr', 'get_vol_ratio', 'price_delta']
refactor_file('signal_engine.py', funcs_se)

# index_trader.py
funcs_it = ['get_price', 'get_vwap', 'ema_trend', 'get_atr', 'get_vol_ratio', 'price_delta']
refactor_file('index_app/index_trader.py', funcs_it)

# STOCK_OPTION_BUYING_APP_1.0.py
funcs_so = ['get_price', 'get_vwap', 'ema_trend', 'get_atr', 'get_vol_ratio', 'price_delta', 'get_rsi']
refactor_file('STOCK_OPTION_BUYING_APP_1.0.py', funcs_so)

print("Refactoring complete.")
