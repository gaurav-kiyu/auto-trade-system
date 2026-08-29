"""Enhanced Seed Data — Realistic Indian property listings for demo and E2E testing.

Creates 30+ properties across all 10 Indian cities with varied types,
price ranges, and realistic descriptions for a compelling demo experience.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# ── Realistic Indian Property Listings ──────────────────────────────────────

SEED_PROPERTIES: list[dict[str, Any]] = [
    # ── Mumbai ────────────────────────────────────────────────────────────
    {"title": "Luxury 3BHK Sea-Facing Apartment in Bandra West", "property_type": "apartment", "price": 45000000, "city": "Mumbai", "locality": "Bandra West", "bedrooms": 3, "bathrooms": 3, "carpet_area_sqft": 1650, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Premium sea-facing 3BHK in Bandra's most sought-after building. Floor-to-ceiling windows with unobstructed Arabian Sea views. Italian marble flooring, modular kitchen, and imported fixtures."},
    {"title": "Affordable 1BHK Studio for Rent in Andheri East", "property_type": "studio", "price": 1800000, "city": "Mumbai", "locality": "Andheri East", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 420, "is_featured": False, "is_verified": True, "furnishing": "semi_furnished", "description": "Compact and affordable studio apartment near Andheri Metro. Walking distance to WEH. Perfect for young professionals. Gym and pool access included."},
    {"title": "4BHK Duplex Penthouse in Worli Sea Face", "property_type": "penthouse", "price": 120000000, "city": "Mumbai", "locality": "Worli", "bedrooms": 4, "bathrooms": 5, "carpet_area_sqft": 2800, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Ultra-luxury duplex penthouse with private terrace and infinity pool overlooking the sea. Smart home automation, Italian kitchen, 24x7 concierge. Truly a landmark property."},
    {"title": "Residential Plot in Thane West — 1200 sqft", "property_type": "plot", "price": 3500000, "city": "Mumbai", "locality": "Thane West", "bedrooms": 0, "bathrooms": 0, "carpet_area_sqft": 1200, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Corner plot in developing Thane West locality. All amenities nearby. Easy access to Eastern Express Highway. Suitable for independent house construction."},

    # ── Bangalore ──────────────────────────────────────────────────────────
    {"title": "Spacious 2BHK with Garden in Whitefield", "property_type": "apartment", "price": 8500000, "city": "Bangalore", "locality": "Whitefield", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 1100, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Beautiful 2BHK in a gated community with lush gardens. Clubhouse, swimming pool, and 24/7 security. Close to ITPL and proposed metro station. Vaastu compliant."},
    {"title": "3BHK Villa with Private Pool in Koramangala", "property_type": "villa", "price": 25000000, "city": "Bangalore", "locality": "Koramangala", "bedrooms": 3, "bathrooms": 3, "carpet_area_sqft": 2200, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Standalone villa in Koramangala's posh 1st Block. Private swimming pool, landscaped garden, rooftop terrace. Walking distance to restaurants and cafes."},
    {"title": "Budget-Friendly 1BHK in Electronic City", "property_type": "apartment", "price": 2800000, "city": "Bangalore", "locality": "Electronic City", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 520, "is_featured": False, "is_verified": True, "furnishing": "unfurnished", "description": "Affordable 1BHK near Wipro and Infosys campuses. Perfect for IT professionals. Well-ventilated with power backup and water supply. Easy connectivity to NICE Road."},
    {"title": "Commercial Office Space in HSR Layout — 1500 sqft", "property_type": "commercial_office", "price": 18000000, "city": "Bangalore", "locality": "HSR Layout", "bedrooms": 0, "bathrooms": 2, "carpet_area_sqft": 1500, "is_featured": False, "is_verified": False, "furnishing": "semi_furnished", "description": "Prime commercial office space on HSR Layout main road. High footfall area. Open plan with cabin space. Covered parking for 4 cars."},

    # ── Delhi ──────────────────────────────────────────────────────────────
    {"title": "3BHK Independent House in Dwarka Sector 14", "property_type": "house", "price": 16000000, "city": "Delhi", "locality": "Dwarka", "bedrooms": 3, "bathrooms": 2, "carpet_area_sqft": 1450, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Corner house in well-developed Dwarka Sector 14. Close to Metro station, schools, and hospitals. 3 bedrooms with attached bathrooms. Modular kitchen and servant room."},
    {"title": "Luxury Apartment in Saket with City View", "property_type": "apartment", "price": 35000000, "city": "Delhi", "locality": "Saket", "bedrooms": 3, "bathrooms": 3, "carpet_area_sqft": 1800, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Premium apartment overlooking Saket Citywalk Mall. Floor-to-ceiling glass facade with panoramic Delhi views. German kitchen, imported sanitaryware, and smart lighting."},
    {"title": "Commercial Shop in Karol Bagh Market", "property_type": "commercial_shop", "price": 7500000, "city": "Delhi", "locality": "Karol Bagh", "bedrooms": 0, "bathrooms": 1, "carpet_area_sqft": 350, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Prime retail shop in Karol Bagh market. High footfall location on main road. Suitable for apparel, electronics, or food business. 10x15 ft carpet area."},
    {"title": "Studio Apartment in Rohini Sector 18", "property_type": "studio", "price": 2200000, "city": "Delhi", "locality": "Rohini", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 380, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Compact studio apartment. Close to Rohini West Metro. Ideal for students or working professionals. Ready to move."},

    # ── Pune ────────────────────────────────────────────────────────────────
    {"title": "2BHK in Hinjewadi Phase 3 — Near IT Park", "property_type": "apartment", "price": 4200000, "city": "Pune", "locality": "Hinjewadi", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 780, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Well-ventilated 2BHK near Hinjewadi IT Park. Gated society with clubhouse, pool, and gym. Walking distance to Phase 3. Low maintenance. Great for IT professionals."},
    {"title": "4BHK Farmhouse on Pune-Nashik Highway", "property_type": "farmhouse", "price": 6500000, "city": "Pune", "locality": "Baner", "bedrooms": 4, "bathrooms": 3, "carpet_area_sqft": 3500, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Weekend farmhouse with half-acre land. Mango and chikoo trees. Borewell with good water. Independent gate access. Perfect for weekend getaways."},
    {"title": "Luxury 3BHK Penthouse in Koregaon Park", "property_type": "penthouse", "price": 28000000, "city": "Pune", "locality": "Koregaon Park", "bedrooms": 3, "bathrooms": 3, "carpet_area_sqft": 2100, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Exclusive penthouse with private terrace garden. Open plan living with floor-to-ceiling glass. Italian marble flooring. Close to Osho Garden and MG Road."},

    # ── Hyderabad ───────────────────────────────────────────────────────────
    {"title": "3BHK Luxury Apartment in Banjara Hills Road 12", "property_type": "apartment", "price": 20000000, "city": "Hyderabad", "locality": "Banjara Hills", "bedrooms": 3, "bathrooms": 3, "carpet_area_sqft": 1850, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Opulent 3BHK in Banjara Hills elite neighborhood. Japanese garden, infinity pool, and state-of-the-art gym. 24x7 security. Close to GVK One Mall."},
    {"title": "Affordable 2BHK in Gachibowli — Near Financial District", "property_type": "apartment", "price": 5500000, "city": "Hyderabad", "locality": "Gachibowli", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 920, "is_featured": False, "is_verified": True, "furnishing": "semi_furnished", "description": "Budget-friendly 2BHK in Gachibowli's fast-growing locality. Near Microsoft, Google, and Amazon campuses. Gated community with pool, gym, and park. Vaastu compliant."},
    {"title": "Residential Plot in Kokapet — 240 sq yds", "property_type": "plot", "price": 8500000, "city": "Hyderabad", "locality": "Kokapet", "bedrooms": 0, "bathrooms": 0, "carpet_area_sqft": 2160, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Premium residential plot in Kokapet, the next IT corridor. HMDA approved layout with all amenities. Good appreciation potential. Near proposed ORR exit."},

    # ── Chennai ─────────────────────────────────────────────────────────────
    {"title": "2BHK in OMR — Walking Distance to Beach", "property_type": "apartment", "price": 6500000, "city": "Chennai", "locality": "OMR", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 950, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Beautiful 2BHK apartment on OMR with sea breeze. Close to Covelong Beach. IT corridor connectivity. Excellent apartment with ventilation and natural light."},
    {"title": "Independent House in Velachery — 3BHK", "property_type": "house", "price": 9500000, "city": "Chennai", "locality": "Velachery", "bedrooms": 3, "bathrooms": 2, "carpet_area_sqft": 1300, "is_featured": False, "is_verified": True, "furnishing": "unfurnished", "description": "Corner plot independent house in Velachery. Walking distance to Phoenix Mall and Velachery Railway Station. 3 bedrooms with hall and kitchen. Ready to occupy."},
    {"title": "Studio Apartment Near Tidel Park", "property_type": "studio", "price": 1500000, "city": "Chennai", "locality": "Adyar", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 350, "is_featured": False, "is_verified": False, "furnishing": "furnished", "description": "Compact studio near Tidel Park. Ideal for IT professionals. Walking distance to Adyar Depot. Fully furnished with AC and Wi-Fi ready."},

    # ── Kolkata ─────────────────────────────────────────────────────────────
    {"title": "3BHK Apartment in Salt Lake Sector 5", "property_type": "apartment", "price": 7200000, "city": "Kolkata", "locality": "Salt Lake", "bedrooms": 3, "bathrooms": 2, "carpet_area_sqft": 1200, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Spacious 3BHK in Salt Lake's prime Sector 5. IT hub vicinity. Clubhouse, gym, and landscaped gardens. Power backup and 24x7 security. Excellent connectivity."},
    {"title": "2BHK in New Town — Affordable Luxury", "property_type": "apartment", "price": 3800000, "city": "Kolkata", "locality": "New Town", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 780, "is_featured": False, "is_verified": True, "furnishing": "unfurnished", "description": "Newly constructed 2BHK in New Town Action Area 1. Close to Eco Park. Well-ventilated with modern amenities. Nearby schools and hospitals. Great for families."},

    # ── Ahmedabad ────────────────────────────────────────────────────────────
    {"title": "4BHK Villa in SG Highway — Premium Living", "property_type": "villa", "price": 18000000, "city": "Ahmedabad", "locality": "SG Highway", "bedrooms": 4, "bathrooms": 4, "carpet_area_sqft": 2500, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Luxurious 4BHK villa on SG Highway premium stretch. Private garden, swimming pool, and rooftop terrace. Italian marble and modular kitchen. Vaastu compliant."},
    {"title": "Commercial Shop in Bopal — High Footfall", "property_type": "commercial_shop", "price": 4500000, "city": "Ahmedabad", "locality": "Bopal", "bedrooms": 0, "bathrooms": 1, "carpet_area_sqft": 400, "is_featured": False, "is_verified": False, "furnishing": "unfurnished", "description": "Prime commercial shop in Bopal junction. 20 ft road facing. Suitable for medical store, salon, or general store. 10x40 carpet area."},

    # ── Noida ────────────────────────────────────────────────────────────────
    {"title": "3BHK in Noida Sector 62 — River View", "property_type": "apartment", "price": 8500000, "city": "Noida", "locality": "Sector 62", "bedrooms": 3, "bathrooms": 2, "carpet_area_sqft": 1350, "is_featured": True, "is_verified": True, "furnishing": "semi_furnished", "description": "Premium 3BHK overlooking Hindon River. Close to Noida Electronic City and Metro. Spacious rooms with attached balconies. Covered parking."},
    {"title": "Studio Apartment in Noida Sector 18 Market", "property_type": "studio", "price": 1800000, "city": "Noida", "locality": "Sector 18", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 320, "is_featured": False, "is_verified": False, "furnishing": "furnished", "description": "Compact studio in the heart of Noida Sector 18. Walking distance to metro and shopping. Fully furnished with AC. Ideal for singles."},

    # ── Gurgaon ──────────────────────────────────────────────────────────────
    {"title": "4BHK Farmhouse in Gurgaon — 1 Acre", "property_type": "farmhouse", "price": 32000000, "city": "Gurgaon", "locality": "Golf Course Road", "bedrooms": 4, "bathrooms": 4, "carpet_area_sqft": 4500, "is_featured": True, "is_verified": True, "furnishing": "furnished", "description": "Premium farmhouse on Golf Course Road extension. 1-acre plot with landscaped garden, pool, and party lawn. Modern architecture with floor-to-ceiling glass. Staff quarters."},
    {"title": "2BHK Apartment in Sector 56 — Affordable", "property_type": "apartment", "price": 4500000, "city": "Gurgaon", "locality": "Sector 56", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 850, "is_featured": False, "is_verified": True, "furnishing": "semi_furnished", "description": "Well-maintained 2BHK in Sector 56. Close to IFFCO Chowk and Metro. Park-facing with good ventilation. Gated society with pool and gym."},

    # ── Rental Properties ────────────────────────────────────────────────────
    {"title": "2BHK for Rent in Whitefield — Near ITPL", "property_type": "apartment", "price": 22000, "city": "Bangalore", "locality": "Whitefield", "bedrooms": 2, "bathrooms": 2, "carpet_area_sqft": 900, "is_featured": False, "is_verified": True, "furnishing": "furnished", "listing_type": "rent", "description": "Fully furnished 2BHK for rent. Walking distance to ITPL. Modular kitchen, AC in all rooms, geyser. Society with clubhouse."},
    {"title": "1BHK for Rent in Andheri West — Near Station", "property_type": "apartment", "price": 15000, "city": "Mumbai", "locality": "Andheri West", "bedrooms": 1, "bathrooms": 1, "carpet_area_sqft": 350, "is_featured": False, "is_verified": False, "furnishing": "semi_furnished", "listing_type": "rent", "description": "Affordable 1BHK near Andheri station. Semi-furnished with beds, wardrobe, and kitchen cabinets. Society with 24hr security."},
    {"title": "3BHK for Rent in Gachibowli — IT Corridor", "property_type": "apartment", "price": 35000, "city": "Hyderabad", "locality": "Gachibowli", "bedrooms": 3, "bathrooms": 2, "carpet_area_sqft": 1350, "is_featured": False, "is_verified": True, "furnishing": "furnished", "listing_type": "rent", "description": "Spacious 3BHK for rent in Gachibowli. Near all major IT companies. Fully furnished with AC. Gated community. Immediate possession."},
]

# ── Seed Function ───────────────────────────────────────────────────────────

def seed_properties(property_service: Any) -> int:
    """Seed the property service with realistic Indian property listings.

    Args:
        property_service: PropertyService instance with create_property method.

    Returns:
        Number of properties seeded.
    """
    count = 0
    for prop_data in SEED_PROPERTIES:
        try:
            property_service.create_property(
                title=prop_data.get("title", "Untitled"),
                description=prop_data.get("description", ""),
                property_type=prop_data.get("property_type", "apartment"),
                price=prop_data.get("price", 0.0),
                city=prop_data.get("city", ""),
                locality=prop_data.get("locality", ""),
                owner_id=prop_data.get("owner_id", "system"),
                bedrooms=prop_data.get("bedrooms", 0),
                bathrooms=prop_data.get("bathrooms", 0),
                carpet_area_sqft=prop_data.get("carpet_area_sqft", 0.0),
            )
            count += 1
        except Exception as exc:
            _log.warning(
                "[SEED] Skipping property %r: %s", prop_data.get("title", "?"), exc
            )
    _log.info("[SEED] Seeded %d/%d properties", count, len(SEED_PROPERTIES))
    return count
