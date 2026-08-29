import re

content = """
def get_open(df):
    try: return float(df['Open'].iloc[-1])
    except (IndexError, ValueError, TypeError, KeyError): return 0.0

def get_high(df):
    try: return float(df['High'].iloc[-1])
    except (IndexError, ValueError, TypeError, KeyError): return 0.0

def get_low(df):
    try: return float(df['Low'].iloc[-1])
    except (IndexError, ValueError, TypeError, KeyError): return 0.0

def get_ema_series(series, span):
    try: return series.ewm(span=span, adjust=False).mean()
    except (ValueError, TypeError): return series
"""

with open('signal_engine.py', encoding='utf-8') as f:
    text = f.read()

text = re.sub(r'get_open = FeatureEngine\.get_open\n?', '', text)
text = re.sub(r'get_high = FeatureEngine\.get_high\n?', '', text)
text = re.sub(r'get_low = FeatureEngine\.get_low\n?', '', text)
text = re.sub(r'get_ema_series = FeatureEngine\.get_ema_series\n?', '', text)

# Insert the functions below the other aliases
text = text.replace('price_delta = FeatureEngine.price_delta\n', 'price_delta = FeatureEngine.price_delta\n' + content)

with open('signal_engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Restored missing functions in signal_engine.py")
