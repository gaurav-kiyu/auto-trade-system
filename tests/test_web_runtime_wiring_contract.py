"""Static contracts for browser wiring that is easy to regress silently."""
from pathlib import Path
import re
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates" / "enterprise"


class _IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a and a["id"]:
            self.ids.add(a["id"])
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        if tag == "button" and a.get("id"):
            self.buttons.append(a["id"])


def _template_texts():
    return {p: p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.html")}


def test_fragment_links_have_real_targets():
    texts = _template_texts()
    for path, text in texts.items():
        parser = _IdParser()
        parser.feed(text)
        for href in parser.links:
            if not href.startswith("#") or href == "#":
                continue
            target = href[1:]
            assert target in parser.ids, f"{path.name}: fragment #{target} has no target id"


def test_cspfix_buttons_have_click_wiring():
    """cspfix-* controls were introduced to replace inline handlers; keep them wired."""
    for path, text in _template_texts().items():
        ids = set(re.findall(r'id=[\"\'](cspfix-[^\"\']+)[\"\']', text))
        for element_id in ids:
            pattern = re.compile(
                rf"getElementById\(\s*['\"]{re.escape(element_id)}['\"]\s*\)\s*\?\.addEventListener\(\s*['\"]click['\"]",
                re.S,
            )
            assert pattern.search(text), f"{path.name}: {element_id} has no click listener"
