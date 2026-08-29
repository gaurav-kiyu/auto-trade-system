from pathlib import Path
from bs4 import BeautifulSoup
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates' / 'enterprise'
def test_all_enterprise_buttons_have_explicit_type():
    bad=[]
    for p in TEMPLATES.glob('*.html'):
        s=BeautifulSoup(p.read_text(errors='ignore'),'html.parser')
        for b in s.find_all('button'):
            if not b.get('type'): bad.append(f'{p.name}:{b.get("id")}')
    assert not bad, 'Implicit button types: ' + ', '.join(bad)
def test_no_real_anchor_placeholder_links():
    bad=[]
    for p in TEMPLATES.glob('*.html'):
        s=BeautifulSoup(p.read_text(errors='ignore'),'html.parser')
        for a in s.find_all('a'):
            if (a.get('href') or '').strip() == '#': bad.append(f'{p.name}:{a.get("id")}')
    assert not bad, 'Placeholder anchors: ' + ', '.join(bad)
