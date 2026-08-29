"""Tests for the real estate SEO module — sitemap, meta tags, robots."""

from __future__ import annotations

from realestate.seo import (
    ALL_LOCALITIES,
    CITIES,
    STATIC_PAGES,
    SitemapGenerator,
    property_meta_tags,
    sanitize_for_url,
)


class TestSitemapGenerator:
    def setup_method(self):
        self.gen = SitemapGenerator(base_url="https://example.com")

    def test_sitemap_starts_with_xml_declaration(self):
        xml = self.gen.generate_sitemap()
        assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_sitemap_contains_urlset(self):
        xml = self.gen.generate_sitemap()
        assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in xml
        assert "</urlset>" in xml

    def test_sitemap_contains_static_pages(self):
        xml = self.gen.generate_sitemap()
        for page in STATIC_PAGES:
            path = page["path"]
            assert path in xml, f"Missing static page: {path}"

    def test_sitemap_contains_all_cities(self):
        xml = self.gen.generate_sitemap()
        for city in CITIES:
            assert f"city={city}" in xml, f"Missing city: {city}"

    def test_sitemap_contains_localities(self):
        xml = self.gen.generate_sitemap()
        for city, localities in ALL_LOCALITIES.items():
            for loc in localities[:3]:  # Check first 3 per city
                assert loc in xml, f"Missing locality: {loc} in {city}"

    def test_sitemap_count(self):
        """Should have at least static pages + cities + localities."""
        xml = self.gen.generate_sitemap()
        url_count = xml.count("<url>")
        expected_min = len(STATIC_PAGES) + len(CITIES) + 10  # at least 10 localities
        assert url_count >= expected_min, f"Expected >= {expected_min} URLs, got {url_count}"

    def test_sitemap_with_property_service(self):
        """Should not crash with None property service."""
        gen = SitemapGenerator(base_url="https://test.com", property_service=None)
        xml = gen.generate_sitemap()
        assert "</urlset>" in xml

    def test_sitemap_urls_have_priority(self):
        xml = self.gen.generate_sitemap()
        # Home page should have highest priority
        assert "<priority>1.0</priority>" in xml

    def test_sitemap_urls_have_changefreq(self):
        xml = self.gen.generate_sitemap()
        assert "<changefreq>" in xml
        assert "daily" in xml
        assert "weekly" in xml

    def test_sitemap_base_url(self):
        gen = SitemapGenerator(base_url="https://myproperty.in")
        xml = gen.generate_sitemap()
        assert "https://myproperty.in" in xml
        assert "example.com" not in xml


class TestMetaTags:
    def test_default_title(self):
        tags = property_meta_tags()
        assert "Real Estate Platform" in tags["og_title"]

    def test_default_description(self):
        tags = property_meta_tags()
        assert len(tags["og_description"]) > 50

    def test_og_type_default(self):
        tags = property_meta_tags()
        assert tags["og_type"] == "website"

    def test_property_meta_tags(self):
        prop = {
            "title": "Luxury 3BHK in Bandra",
            "price": 25000000,
            "location": {"address": {"city": "Mumbai"}},
            "slug": "/realestate/property/RE-2026-ABC123",
        }
        tags = property_meta_tags(property_data=prop, page_type="article")
        assert "Luxury 3BHK" in tags["og_title"]
        assert "25,000,000" in tags["og_description"] or "25000000" in tags["og_description"]
        assert tags["og_type"] == "article"

    def test_property_meta_with_media(self):
        prop = {
            "title": "Test Property",
            "price": 5000000,
            "location": {"address": {"city": "Pune"}},
            "media": [{"url": "https://example.com/photo1.jpg"}],
        }
        tags = property_meta_tags(property_data=prop)
        assert "https://example.com/photo1.jpg" in tags["og_image"]

    def test_twitter_card(self):
        tags = property_meta_tags()
        assert tags["twitter_card"] == "summary_large_image"

    def test_meta_truncation(self):
        """Long titles should be truncated at 120 chars."""
        long_title = "Luxury " + "Very " * 30 + "Apartment"
        prop = {
            "title": long_title,
            "price": 10000000,
            "location": {"address": {"city": "Delhi"}},
        }
        tags = property_meta_tags(property_data=prop)
        assert len(tags["og_title"]) <= 120

    def test_canonical_meta(self):
        prop = {"slug": "/realestate/property/RE-001", "price": 0, "location": {"address": {}}}
        tags = property_meta_tags(property_data=prop)
        assert tags["canonical_url"] == "/realestate/property/RE-001"


class TestSanitizeURL:
    def test_basic_slug(self):
        assert sanitize_for_url("Luxury Apartment in Bandra") == "luxury-apartment-in-bandra"

    def test_strip_special_chars(self):
        assert sanitize_for_url("2BHK @ Worli! (Mumbai)") == "2bhk-worli-mumbai"

    def test_collapse_spaces(self):
        assert sanitize_for_url("  Premium   Villa   ") == "premium-villa"

    def test_collapse_hyphens(self):
        assert sanitize_for_url("Luxury---Villa") == "luxury-villa"

    def test_empty_string(self):
        assert sanitize_for_url("") == ""

    def test_already_clean(self):
        assert sanitize_for_url("hello-world") == "hello-world"


class TestConstants:
    def test_all_cities_list(self):
        assert len(CITIES) == 10
        assert "Mumbai" in CITIES
        assert "Bangalore" in CITIES

    def test_all_localities(self):
        assert len(ALL_LOCALITIES) == 10
        assert "Mumbai" in ALL_LOCALITIES
        assert len(ALL_LOCALITIES["Mumbai"]) == 10
        assert len(ALL_LOCALITIES["Bangalore"]) == 10

    def test_static_pages_home(self):
        home = [p for p in STATIC_PAGES if p["path"] == "/realestate"]
        assert len(home) == 1
        assert home[0]["priority"] == "1.0"
        assert home[0]["changefreq"] == "daily"
