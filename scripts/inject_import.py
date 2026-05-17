for file_path in ['index_app/index_trader.py', 'STOCK_OPTION_BUYING_APP_1.0.py']:
    with open(file_path, encoding='utf-8') as f:
        text = f.read()

    # Prepend import
    if 'from core.feature_engine import FeatureEngine' not in text:
        text = 'from core.feature_engine import FeatureEngine\n' + text

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(text)

print("Injected FeatureEngine imports.")
