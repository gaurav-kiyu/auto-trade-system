"""SEO Module — Sitemap generation, meta tags, canonical URLs for the real estate platform.

Provides:
  - Dynamic sitemap.xml generation for all property listings, localities, and static pages
  - Meta tag helpers for HTML templates
  - Canonical URL generation
  - Open Graph and Twitter Card metadata
"""

from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)


# ── Static Page Information ──────────────────────────────────────────────────

STATIC_PAGES: list[dict[str, Any]] = [
    {"path": "/realestate", "changefreq": "daily", "priority": "1.0"},
    {"path": "/realestate/search", "changefreq": "daily", "priority": "0.9"},
    {"path": "/realestate/search?city=Mumbai", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Bangalore", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Delhi", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Pune", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Hyderabad", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Chennai", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Kolkata", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Ahmedabad", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Noida", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/search?city=Gurgaon", "changefreq": "daily", "priority": "0.8"},
    {"path": "/realestate/compare", "changefreq": "weekly", "priority": "0.6"},
    {"path": "/realestate/analytics", "changefreq": "weekly", "priority": "0.5"},
    {"path": "/realestate/rera", "changefreq": "weekly", "priority": "0.7"},
    {"path": "/realestate/login", "changefreq": "monthly", "priority": "0.3"},
]

CITIES = [
    "Mumbai", "Bangalore", "Delhi", "Pune", "Hyderabad",
    "Chennai", "Kolkata", "Ahmedabad", "Noida", "Gurgaon",
]

ALL_LOCALITIES: dict[str, list[str]] = {
    "Mumbai": ["Andheri", "Bandra", "Powai", "Worli", "Juhu", "Malad", "Thane", "Navi Mumbai", "Goregaon", "Borivali"],
    "Bangalore": ["Whitefield", "Indiranagar", "Koramangala", "Jayanagar", "Marathahalli", "Electronic City", "HSR Layout", "JP Nagar", "BTM Layout", "Hebbal"],
    "Delhi": ["Dwarka", "Rohini", "Lajpat Nagar", "Karol Bagh", "Saket", "Vasant Kunj", "Hauz Khas", "Greater Kailash", "Pitampura", "Janakpuri"],
    "Pune": ["Hinjewadi", "Kharadi", "Baner", "Wakad", "Koregaon Park", "Viman Nagar", "Hadapsar", "Pimple Saudagar", "Aundh", "Bibvewadi"],
    "Hyderabad": ["Hitech City", "Gachibowli", "Kukatpally", "Madhapur", "Kondapur", "Secunderabad", "Banjara Hills", "Jubilee Hills", "Miyapur", "Nallagandla"],
    "Chennai": ["OMR", "Velachery", "Porur", "Tambaram", "Adyar", "Thoraipakkam", "Anna Nagar", "T Nagar", "Chromepet", "Guindy"],
    "Kolkata": ["Salt Lake", "New Town", "Rajhat", "Ballygunge", "Alipore", "Dum Dum", "Barrackpore", "Howrah", "Behala", "Garia"],
    "Ahmedabad": ["SG Highway", "Bopal", "Prahlad Nagar", "Gota", "Science City", "Vastrapur", "Thaltej", "Chandkheda", "Satellite", "Navrangpura"],
    "Noida": ["Sector 62", "Sector 44", "Sector 18", "Sector 128", "Sector 137", "Greater Noida", "Sector 150", "Sector 168", "Sector 15", "Sector 61"],
    "Gurgaon": ["Sector 56", "Golf Course Road", "DLF Phase 2", "Sohna Road", "Sector 14", "MG Road", "Sector 43", "Sector 57", "Sector 63A", "Sector 69"],
}


# ── Sitemap Generator ────────────────────────────────────────────────────────

class SitemapGenerator:
    """Generates XML sitemaps for the real estate platform.

    Includes:
      - Static pages (home, search, compare, analytics, RERA, login)
      - Dynamic property listing pages (by city)
      - Locality pages (by city + locality)
    """

    def __init__(self, base_url: str = "https://realestate.example.com",
                 property_service: Any = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._property_service = property_service
        self._lastmod = time.strftime("%Y-%m-%d")

    def generate_sitemap(self) -> str:
        """Generate the complete sitemap XML with all pages."""
        urls: list[dict[str, Any]] = []

        # Static pages
        for page in STATIC_PAGES:
            urls.append({
                "loc": f"{self._base_url}{page['path']}",
                "changefreq": page["changefreq"],
                "priority": page["priority"],
                "lastmod": self._lastmod,
            })

        # City search pages
        for city in CITIES:
            urls.append({
                "loc": f"{self._base_url}/realestate/search?city={city}",
                "changefreq": "daily",
                "priority": "0.8",
                "lastmod": self._lastmod,
            })

        # Locality pages
        for city, localities in ALL_LOCALITIES.items():
            for locality in localities:
                loc_url = f"{self._base_url}/realestate/search?city={city}&locality={locality}"
                urls.append({
                    "loc": loc_url,
                    "changefreq": "weekly",
                    "priority": "0.7",
                    "lastmod": self._lastmod,
                })

        # Property detail pages (from property service)
        if self._property_service:
            try:
                properties = self._property_service.list_all()
                for prop in properties:
                    pid = prop.property_id if hasattr(prop, "property_id") else getattr(prop, "id", "")
                    if pid:
                        urls.append({
                            "loc": f"{self._base_url}/realestate/property/{pid}",
                            "changefreq": "weekly",
                            "priority": "0.9",
                            "lastmod": self._lastmod,
                        })
            except Exception as exc:
                _log.debug("[SEO] Failed to add property URLs: %s", exc)

        # Build XML
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for url in urls:
            xml_parts.append("  <url>")
            xml_parts.append(f"    <loc>{url['loc']}</loc>")
            xml_parts.append(f"    <lastmod>{url['lastmod']}</lastmod>")
            xml_parts.append(f"    <changefreq>{url['changefreq']}</changefreq>")
            xml_parts.append(f"    <priority>{url['priority']}</priority>")
            xml_parts.append("  </url>")
        xml_parts.append("</urlset>")
        return "\n".join(xml_parts)


# ── Meta Tag Helper ──────────────────────────────────────────────────────────

def property_meta_tags(property_data: dict[str, Any] | None = None,
                       page_type: str = "website") -> dict[str, str]:
    """Generate Open Graph and Twitter Card meta tags for a property or page.

    Args:
        property_data: Optional property dict for detail pages.
        page_type: Open Graph page type (website, article, etc.).

    Returns:
        Dict of meta tag name -> content values suitable for Jinja2 template context.
    """
    default_title = "Real Estate Platform — Buy, Rent, Sell Properties in India"
    default_desc = ("Find the best properties for sale and rent across India. "
                    "Browse apartments, villas, plots, and commercial properties "
                    "with detailed insights, neighborhood data, and legal guidance.")

    if property_data:
        title = property_data.get("meta_title") or property_data.get("title", default_title)
        desc = property_data.get("meta_description") or (
            f"{property_data.get('title', 'Property')} — "
            f"₹{property_data.get('price', 0):,.0f} in "
            f"{property_data.get('location', {}).get('address', {}).get('city', 'India')}. "
            f"View photos, amenities, and neighborhood insights."
        )
        image = ""
        media = property_data.get("media", [])
        if media and isinstance(media, list) and len(media) > 0:
            image = media[0].get("url", "") if isinstance(media[0], dict) else ""
        url_slug = property_data.get("slug", "")
    else:
        title = default_title
        desc = default_desc
        image = ""
        url_slug = ""

    return {
        "og_title": title[:120],
        "og_description": desc[:320],
        "og_image": image,
        "og_type": page_type,
        "og_url": url_slug,
        "twitter_card": "summary_large_image",
        "twitter_title": title[:120],
        "twitter_description": desc[:200],
        "canonical_url": url_slug,
    }


def sanitize_for_url(text: str) -> str:
    """Convert text to a URL-friendly slug (for property URLs)."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


# ── API Router ───────────────────────────────────────────────────────────────

_sitemap_generator: SitemapGenerator | None = None


def get_sitemap_generator(base_url: str = "https://realestate.example.com",
                          property_service: Any = None) -> SitemapGenerator:
    global _sitemap_generator
    if _sitemap_generator is None:
        _sitemap_generator = SitemapGenerator(base_url=base_url, property_service=property_service)
    return _sitemap_generator


def create_seo_router(property_service: Any = None) -> Any:
    """Create a FastAPI router for SEO endpoints (sitemap.xml, robots.txt)."""
    from fastapi import APIRouter
    from fastapi.responses import PlainTextResponse

    router = APIRouter(tags=["Real Estate SEO"])

    gen = get_sitemap_generator(property_service=property_service)

    @router.get("/sitemap.xml", response_class=PlainTextResponse)
    async def sitemap_xml():
        """Generated sitemap for all real estate pages."""
        return PlainTextResponse(
            content=gen.generate_sitemap(),
            media_type="application/xml",
        )

    @router.get("/robots.txt", response_class=PlainTextResponse)
    async def robots_txt():
        """Robots.txt with sitemap reference."""
        return PlainTextResponse(
            content="User-agent: *\n"
                    "Allow: /\n"
                    "Disallow: /api/\n"
                    "Disallow: /realestate/admin\n"
                    "Disallow: /realestate/login\n"
                    "\n"
                    "Sitemap: https://realestate.example.com/sitemap.xml\n",
            media_type="text/plain",
        )

    return router
