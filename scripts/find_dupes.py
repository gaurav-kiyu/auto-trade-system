import ast

for file_path in ['index_app/index_trader.py', 'STOCK_OPTION_BUYING_APP_1.0.py']:
    print(f"--- {file_path} ---")
    with open(file_path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in ['get_price', 'get_open', 'get_high', 'get_low', 'get_vwap', 'get_ema', 'get_ema_series', 'ema_trend', 'get_rsi', 'get_macd', 'get_atr', 'get_vol_ratio', 'price_delta']:
            print(f"{node.name} (line {node.lineno})")
