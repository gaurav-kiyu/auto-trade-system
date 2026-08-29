#!/usr/bin/env python3
"""Seed the real estate platform with sample property data for demo/testing.

Creates 60+ realistic Indian properties across 10 major cities with:
  - Accurate coordinates (lat/lng) for map visualization
  - Realistic pricing based on city averages
  - Indian property types (1BHK through 4BHK, villa, penthouse, etc.)
  - Amenities, furnishings, images, and features

Usage:
    python scripts/seed_realestate_data.py              # Seed 60 properties
    python scripts/seed_realestate_data.py --count 20   # Seed 20 properties
    python scripts/seed_realestate_data.py --reset      # Clear first
"""

from __future__ import annotations

import argparse
import logging
import random
import time
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_log = logging.getLogger("seed")

# ── City Data ────────────────────────────────────────────────────────────────

CITIES = {
    "Mumbai": {
        "localities": ["Andheri West", "Bandra West", "Powai", "Worli", "Malad West",
                       "Goregaon West", "Juhu", "Colaba", "Lower Parel", "Dadar"],
        "coords": [19.0760, 72.8777],
        "price_per_sqft": 15000,
    },
    "Bangalore": {
        "localities": ["Whitefield", "Electronic City", "Indiranagar", "Koramangala",
                       "HSR Layout", "JP Nagar", "Marathahalli", "Yelahanka", "Jayanagar", "Sadashivanagar"],
        "coords": [12.9716, 77.5946],
        "price_per_sqft": 9500,
    },
    "Delhi": {
        "localities": ["Dwarka Sector 22", "Rohini Sector 9", "Lajpat Nagar",
                       "Greater Kailash I", "Saket", "Vasant Kunj", "Hauz Khas",
                       "Pitampura", "Karol Bagh", "Mayur Vihar"],
        "coords": [28.7041, 77.1025],
        "price_per_sqft": 12000,
    },
    "Pune": {
        "localities": ["Hinjewadi Phase 1", "Kharadi", "Baner", "Wakad", "Kothrud",
                       "Viman Nagar", "Hadapsar", "Bibwewadi", "Aundh", "Magarpatta"],
        "coords": [18.5204, 73.8567],
        "price_per_sqft": 8000,
    },
    "Hyderabad": {
        "localities": ["HITEC City", "Gachibowli", "Kondapur", "Madhapur",
                       "Jubilee Hills", "Banjara Hills", "Kukatpally", "Miyapur",
                       "Shamshabad", "Uppal"],
        "coords": [17.3850, 78.4867],
        "price_per_sqft": 7500,
    },
    "Chennai": {
        "localities": ["OMR Thoraipakkam", "Velachery", "Adyar", "Tambaram",
                       "Porur", "Thiruvanmiyur", "Guindy", "Sholinganallur",
                       "Chromepet", "Nungambakkam"],
        "coords": [13.0827, 80.2707],
        "price_per_sqft": 7000,
    },
    "Kolkata": {
        "localities": ["Salt Lake Sector V", "New Town", "Rajarbagh", "Dum Dum",
                       "New Alipore", "Behala", "Baranagar", "Lake Town",
                       "Tollygunge", "Ballygunge"],
        "coords": [22.5726, 88.3639],
        "price_per_sqft": 5500,
    },
    "Ahmedabad": {
        "localities": ["SG Highway", "Prahlad Nagar", "Bodakdev", "Vastrapur",
                       "Satellite", "Thaltej", "Bopal", "Chandkheda", "Naranpura", "Maninagar"],
        "coords": [23.0225, 72.5714],
        "price_per_sqft": 5000,
    },
    "Noida": {
        "localities": ["Sector 62", "Sector 44", "Sector 15", "Sector 128",
                       "Sector 137", "Greater Noida West", "Sector 168",
                       "Sector 45", "Sector 22", "Sector 70"],
        "coords": [28.5355, 77.3910],
        "price_per_sqft": 6500,
    },
    "Gurgaon": {
        "localities": ["DLF Phase 1", "Sector 56", "Sohna Road", "Gurgaon South",
                       "Dwarka Expressway", "Golf Course Road", "MG Road",
                       "Sector 14", "Sector 43", "Sector 57"],
        "coords": [28.4595, 77.0266],
        "price_per_sqft": 11000,
    },
}

PROPERTY_TYPES = ["apartment", "house", "villa", "penthouse", "studio", "commercial_office"]
FURNISHING = ["furnished", "semi_furnished", "unfurnished"]
AMENITIES_POOL = [
    "Swimming Pool", "Gym", "Club House", "Children's Play Area", "Jogging Track",
    "Landscaped Gardens", "24x7 Security", "Power Backup", "Rainwater Harvesting",
    "Car Parking", "Visitor Parking", "CCTV Surveillance", "Elevator", "Intercom",
    "Gas Pipeline", "Solar Panels", "Tennis Court", "Badminton Court", "Yoga Deck",
    "Party Hall", "Library", "Indoor Games Room", "Spa", "Steam Room", "Jacuzzi",
]

TITLES = [
    "Modern {bhk}BHK {type} in {locality}",
    "Spacious {bhk}BHK {type} with {view} View",
    "Luxury {bhk}BHK {type} in Prime Location",
    "Affordable {bhk}BHK {type} for Family",
    "Premium {type} with Modern Amenities in {locality}",
    "Brand New {bhk}BHK {type} Ready to Move",
    "Stunning {bhk}BHK {type} Near IT Hub",
    "Well-Designed {bhk}BHK {type} in Gated Community",
    "Executive {bhk}BHK {type} with Premium Finishes",
    "Elegant {bhk}BHK {type} in {locality}",
]

VIEWS = ["Garden", "City", "Pool", "Park", "Lake", "Mountain", "Sea", "Valley"]

DESCRIPTIONS = [
    "This beautifully designed home offers spacious rooms, modern finishes, and excellent natural light throughout.",
    "Located in a prime residential area with easy access to schools, hospitals, and shopping centers.",
    "A perfect family home with all modern amenities, 24/7 security, and well-maintained common areas.",
    "Premium property with high-quality construction, Vastu-compliant layout, and excellent ventilation.",
    "Ready-to-move-in property with modern kitchen, stylish bathrooms, and ample storage space.",
    "Gated community property with lush green surroundings, clubhouse, and premium amenities.",
    "Excellent investment opportunity in a rapidly developing area with great appreciation potential.",
    "Corner property with extra windows providing panoramic views and excellent cross-ventilation.",
]


def _generate_locality_offset(base_coords: list[float]) -> list[float]:
    """Generate coordinates offset for a locality within a city."""
    lat_offset = random.uniform(-0.05, 0.05)
    lng_offset = random.uniform(-0.05, 0.05)
    return [base_coords[0] + lat_offset, base_coords[1] + lng_offset]


def _pick_random(pool: list[str], n: int = 1) -> list[str]:
    return random.sample(pool, min(n, len(pool)))


def _build_title(bhk: int, ptype: str, locality: str) -> str:
    template = random.choice(TITLES)
    view = random.choice(VIEWS)
    title = template.format(bhk=bhk, type=ptype.replace("_", " "), locality=locality, view=view)
    return title[:80]


def seed_properties(
    count: int = 60,
    owner_id: str = "demo-admin",
    api_base: str = "http://localhost:8766",
    reset_first: bool = False,
) -> int:
    """Seed properties into the real estate platform.

    Args:
        count: Number of properties to create.
        owner_id: Owner user ID for all properties.
        api_base: Base URL of the running real estate API.
        reset_first: If True, delete all existing properties first.

    Returns:
        Number of properties successfully created.
    """
    import httpx

    cities_list = list(CITIES.keys())
    created = 0

    # Optional: clear existing
    if reset_first:
        try:
            existing = httpx.get(f"{api_base}/api/realestate/properties", params={"page_size": 200}, timeout=10)
            if existing.status_code == 200:
                for p in existing.json().get("properties", []):
                    httpx.delete(f"{api_base}/api/realestate/properties/{p['property_id']}", timeout=10)
                _log.info("Cleared existing properties")
        except Exception as exc:
            _log.warning("Could not clear existing: %s", exc)

    for i in range(count):
        city_name = random.choice(cities_list)
        city = CITIES[city_name]
        locality = random.choice(city["localities"])
        bhk = random.choices([1, 2, 3, 4, 5], weights=[10, 35, 30, 15, 10])[0]
        ptype = random.choice(PROPERTY_TYPES)
        furnishing = random.choice(FURNISHING)
        area = random.randint(int(bhk * 350), int(bhk * 800)) if ptype == "studio" else \
               random.randint(int(bhk * 450), int(bhk * 1200) + bhk * 200)
        price_per_sqft = city["price_per_sqft"] * random.uniform(0.7, 1.3)
        price = int(area * price_per_sqft)
        # Round to nearest lakh
        price = round(price / 100000) * 100000
        locality_coords = _generate_locality_offset(city["coords"])
        bathrooms = random.randint(bhk, bhk + 2)
        balconies = random.randint(0, 2)

        title = _build_title(bhk, ptype, locality)
        description = random.choice(DESCRIPTIONS)

        params: dict[str, Any] = {
            "title": title,
            "description": description,
            "property_type": ptype,
            "price": price,
            "city": city_name,
            "locality": locality,
            "bedrooms": bhk,
            "bathrooms": bathrooms,
            "balconies": balconies,
            "carpet_area_sqft": area,
            "furnishing": furnishing,
            "owner_id": owner_id,
            "latitude": locality_coords[0],
            "longitude": locality_coords[1],
        }

        try:
            resp = httpx.post(f"{api_base}/api/realestate/properties", params=params, timeout=10)
            if resp.status_code == 200:
                created += 1
                if created % 10 == 0:
                    _log.info("  Created %d properties...", created)
            else:
                _log.warning("  Failed (%d): %s", resp.status_code, resp.text[:100])
        except httpx.RequestError as exc:
            _log.warning("  Request failed: %s", exc)

    _log.info("Seeded %d/%d properties across %d cities", created, count, len(cities_list))
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed real estate demo data")
    parser.add_argument("--count", type=int, default=60, help="Number of properties (default: 60)")
    parser.add_argument("--api", type=str, default="http://localhost:8766", help="API base URL")
    parser.add_argument("--owner", type=str, default="demo-admin", help="Owner user ID")
    parser.add_argument("--reset", action="store_true", help="Delete all existing properties first")
    args = parser.parse_args()

    _log.info("Seeding %d properties to %s ...", args.count, args.api)
    start = time.time()
    created = seed_properties(
        count=args.count,
        owner_id=args.owner,
        api_base=args.api,
        reset_first=args.reset,
    )
    elapsed = time.time() - start
    _log.info("Done! %d properties created in %.1f seconds", created, elapsed)


if __name__ == "__main__":
    main()
