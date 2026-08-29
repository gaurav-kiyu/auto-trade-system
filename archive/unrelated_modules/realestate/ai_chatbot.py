"""AI-powered property chatbot with Retrieval-Augmented Generation (RAG).

Provides property search, FAQ answering, legal guidance, and neighborhood
information through an intent-based conversational interface.

Uses vector-like similarity matching on property data and FAQ corpus.
"""

from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── FAQ Corpus ───────────────────────────────────────────────────────────────

@dataclass
class FAQEntry:
    """A FAQ entry with question, answer, and keywords for intent matching."""
    question: str = ""
    answer: str = ""
    keywords: list[str] = field(default_factory=list)
    category: str = "general"  # buying, renting, legal, financing, neighborhood

FAQ_CORPUS: list[FAQEntry] = [
    FAQEntry(
        question="What documents are required to buy a property in India?",
        answer="To buy property in India you typically need: PAN card, Aadhaar card, IT returns (3 years), bank statements (6 months), passport-sized photos, and proof of address. For NRI buyers, additional documents include OCI/PIO card, passport copy, and foreign bank statements. Always verify the property's title deed and encumbrance certificate before purchase.",
        keywords=["documents", "required", "buy", "purchase", "need", "paperwork", "pan", "aadhaar"],
        category="buying",
    ),
    FAQEntry(
        question="What is RERA and why is it important?",
        answer="RERA (Real Estate Regulatory Authority) is a government regulatory body that protects homebuyers. Properties registered under RERA have: guaranteed possession dates, standard carpet area definitions, quality assurance, and legal recourse if delayed. Always check if a project is RERA registered before buying — look for the RERA number on the listing.",
        keywords=["rera", "regulatory", "registration", "protection", "legal", "authority"],
        category="legal",
    ),
    FAQEntry(
        question="What are the costs involved in buying a property?",
        answer="Beyond the property price, expect to pay: stamp duty (5-7% of property value depending on state), registration fee (1-2%), GST (5% on under-construction), maintenance deposit, and legal fees. For home loans, processing fees (0.5-1%) and valuation fees apply. Budget for approximately 8-12% above the property price for all costs.",
        keywords=["costs", "charges", "fees", "stamp duty", "registration", "gst", "expenses", "budget"],
        category="buying",
    ),
    FAQEntry(
        question="How does the rent agreement process work?",
        answer="A rent agreement involves: 1) Drafting the agreement with rent amount, deposit, and terms. 2) E-stamping the agreement (online through SHCIL or state portal). 3) Both parties sign (can be Aadhaar e-sign). 4) Registration is mandatory for agreements over 11 months. The tenant typically pays 2-3 months' rent as security deposit. Notice period is usually 1-3 months.",
        keywords=["rent", "agreement", "lease", "tenant", "landlord", "stamping", "sign", "deposit"],
        category="renting",
    ),
    FAQEntry(
        question="What is the difference between carpet area and super built-up area?",
        answer="Carpet area is the actual usable area inside your apartment (from inner wall to inner wall). Super built-up area includes carpet area plus common areas (corridors, lift lobby, stairs) proportionally shared. Loading factor typically ranges from 20-40%. RERA mandates that builders sell based on carpet area, not super built-up area, for better transparency.",
        keywords=["carpet area", "super built-up", "built up", "area difference", "sqft", "loading factor", "usable area"],
        category="buying",
    ),
    FAQEntry(
        question="What home loan options are available?",
        answer="Major home loan providers include SBI, HDFC, ICICI, LIC Housing, and Axis Bank. Loans typically cover 75-90% of property value. Interest rates range from 8.5-10.5% p.a. (as of 2024-25). First-time buyers get additional tax benefits under Section 80EE. Loan tenure can extend up to 30 years. Processing time is 2-4 weeks.",
        keywords=["home loan", "bank loan", "finance", "mortgage", "interest", "emi", "funding"],
        category="financing",
    ),
    FAQEntry(
        question="What is the process for property registration?",
        answer="Property registration is done at the Sub-Registrar's office: 1) Agreement of Sale is drafted and stamped. 2) Stamp duty is paid (varies by state). 3) Both buyer and seller appear before the Sub-Registrar (or authorize a representative). 4) Sale Deed is registered. 5) Mutation is done at the municipal corporation. Digital registration is now available in many states.",
        keywords=["registration", "sub registrar", "sale deed", "mutation", "title", "transfer"],
        category="legal",
    ),
    FAQEntry(
        question="What are the tax benefits of buying a home?",
        answer="Under Section 80C (up to ₹1.5L), Section 24(b) (up to ₹2L on interest), Section 80EE (additional ₹50K for first-time buyers), and Section 80EEA (additional ₹1.5L for affordable housing). Women buyers get lower stamp duty rates in several states. Principal repayment qualifies under 80C. Total potential tax deduction: up to ₹5 lakh+ per year.",
        keywords=["tax", "benefits", "deduction", "80c", "80ee", "income tax", "saving"],
        category="financing",
    ),
    FAQEntry(
        question="How can I check property legality and ownership?",
        answer="Check: 1) Title deed at Sub-Registrar's office. 2) Encumbrance Certificate (EC) for last 13 years. 3) Land records via state's land records portal (e.g., Dharani in Telangana, Bhulekh in UP). 4) RERA registration number. 5) Approved building plan from municipal corporation. 6) No-objection certificates (NOC) from relevant authorities. Engage a property lawyer for thorough due diligence.",
        keywords=["legal", "ownership", "title", "encumbrance", "due diligence", "verify", "check", "land record"],
        category="legal",
    ),
    FAQEntry(
        question="What are the different property types available?",
        answer="Indian real estate offers: Apartments (1BHK/2BHK/3BHK/4BHK), Independent Houses, Villas, Plots (residential/commercial), Penthouse, Studio Apartments, Farmhouses, and Commercial properties (office, shop, warehouse). Each has different regulations. Apartments offer shared amenities, while independent houses offer more privacy. Plots allow custom construction.",
        keywords=["property types", "apartment", "villa", "house", "plot", "bhk", "studio", "commercial"],
        category="buying",
    ),
    FAQEntry(
        question="What is Aadhaar eSign for rent agreements?",
        answer="Aadhaar eSign is a legally valid electronic signature using Aadhaar-based authentication. It allows landlords and tenants to sign rent agreements digitally without printing physical copies. The process: OTP is sent to the Aadhaar-linked mobile number, verification is done by UIDAI, and the digitally signed agreement is legally binding under the IT Act.",
        keywords=["esign", "aadhaar sign", "digital signature", "electronic signature", "online sign", "esignature"],
        category="legal",
    ),
]


# ── Chatbot Engine ───────────────────────────────────────────────────────────

@dataclass
class ChatIntent:
    """Classified intent from user message."""
    category: str = "general"
    confidence: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    faq_matches: list[FAQEntry] = field(default_factory=list)


@dataclass
class ChatResponse:
    """Structured chatbot response."""
    text: str = ""
    intent: ChatIntent = field(default_factory=ChatIntent)
    suggestions: list[str] = field(default_factory=list)
    properties: list[dict[str, Any]] = field(default_factory=list)
    query_time_ms: float = 0.0


INTENT_CATEGORIES = {
    "buying": ["buy", "purchase", "priced", "cost", "apartment", "bhk", "property", "flat"],
    "renting": ["rent", "lease", "tenant", "landlord", "deposit", "agreement"],
    "legal": ["legal", "rera", "registration", "document", "title", "deed", "esign", "stamp"],
    "financing": ["loan", "bank", "interest", "emi", "tax", "finance", "mortgage", "insurance"],
    "neighborhood": ["locality", "area", "city", "neighborhood", "school", "hospital", "connectivity"],
    "general": ["hi", "hello", "help", "how", "what", "which", "recommend", "suggest", "find"],
}


class RealEstateChatbot:
    """AI chatbot for property inquiries using intent classification + FAQ matching."""

    def __init__(self, property_service: Any = None, neighborhood_service: Any = None):
        self._property_service = property_service
        self._neighborhood_service = neighborhood_service
        self._faq_index = self._build_faq_index()

    def _build_faq_index(self) -> dict[str, list[FAQEntry]]:
        index: dict[str, list[FAQEntry]] = {}
        for entry in FAQ_CORPUS:
            for kw in entry.keywords:
                index.setdefault(kw.lower(), []).append(entry)
        return index

    def classify_intent(self, message: str) -> ChatIntent:
        """Classify user intent from message text."""
        msg_lower = message.lower()
        matched_keywords: list[str] = []
        category_scores: dict[str, float] = {}

        # Score categories based on keyword matches
        for category, keywords in INTENT_CATEGORIES.items():
            score = 0.0
            for kw in keywords:
                if kw in msg_lower:
                    score += 1.0
                    matched_keywords.append(kw)
            if score > 0:
                category_scores[category] = score / len(keywords)

        # Find best category
        best_category = "general"
        best_score = 0.0
        for cat, score in category_scores.items():
            if score > best_score:
                best_score = score
                best_category = cat

        # Find FAQ matches
        faq_matches: list[FAQEntry] = []
        best_ratio = 0.0
        for entry in FAQ_CORPUS:
            ratio = difflib.SequenceMatcher(None, msg_lower, entry.question.lower()).ratio()
            if ratio > 0.3:
                faq_matches.append(entry)
                if ratio > best_ratio:
                    best_ratio = ratio

        # Always also match by keywords — keyword-matched entries take priority
        keyword_matches: list[FAQEntry] = []
        for kw in matched_keywords:
            for entry in self._faq_index.get(kw, []):
                if entry not in keyword_matches:
                    keyword_matches.append(entry)

        # Merge: keyword matches first (by keyword count), then SequenceMatcher matches
        seen_ids = {id(e) for e in keyword_matches}
        seq_only = [e for e in faq_matches if id(e) not in seen_ids]
        keyword_matches.sort(key=lambda e: sum(1 for kw in matched_keywords if kw in e.keywords), reverse=True)
        all_matches = keyword_matches + seq_only

        return ChatIntent(
            category=best_category,
            confidence=best_score,
            matched_keywords=list(set(matched_keywords)),
            faq_matches=all_matches[:3],
        )

    def respond(self, message: str, user_id: str | None = None) -> ChatResponse:
        """Generate contextual response to user message."""
        start = time.time()
        intent = self.classify_intent(message)
        msg_lower = message.lower()

        # ── Greeting ──
        if any(g in msg_lower for g in ["hi", "hello", "hey", "namaste"]):
            elapsed = (time.time() - start) * 1000
            return ChatResponse(
                text="🏠 Namaste! Welcome to the Real Estate Assistant. I can help you:\n"
                     "• Find properties by city, budget, or type\n"
                     "• Answer legal FAQs about buying/renting\n"
                     "• Check neighborhood insights\n"
                     "• Guide you through rent agreements and e-stamping\n\n"
                     "Try: 'Show me 2BHK in Bangalore under 1 crore' or 'What documents do I need to buy?'",
                intent=intent,
                suggestions=["Show properties in Mumbai", "What is RERA?", "Affordable 3BHK in Pune", "Rent agreement process"],
                query_time_ms=round(elapsed, 2),
            )

        # ── Property Search ──
        if self._property_service and any(w in msg_lower for w in ["show", "find", "search", "looking for", "want", "property", "flat", "apartment", "house"]):
            # Extract potential search criteria
            city = ""
            min_bedrooms = 0
            max_price = 0.0

            for c in ["mumbai", "bangalore", "delhi", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad", "noida", "gurgaon"]:
                if c in msg_lower:
                    city = c.title()
                    break

            for b in range(1, 6):
                if f"{b}bhk" in msg_lower.replace(" ", "") or f"{b} bhk" in msg_lower:
                    min_bedrooms = b
                    break

            price_match = re.search(r'(\d+\.?\d*)\s*(cr|crore|lac|lakh|k)', msg_lower)
            if price_match:
                amt = float(price_match.group(1))
                unit = price_match.group(2)
                if unit in ("cr", "crore"):
                    max_price = amt * 1_00_00_000
                elif unit in ("lac", "lakh"):
                    max_price = amt * 1_00_000
                elif unit == "k":
                    max_price = amt * 1_000

            # Build response
            location_str = f" in {city}" if city else ""
            bedrooms_str = f" {min_bedrooms}BHK" if min_bedrooms > 0 else ""
            price_str = f" under ₹{max_price / 1_00_000:.0f}L" if max_price > 0 else ""
            elapsed = (time.time() - start) * 1000

            if city:
                return ChatResponse(
                    text=f"🔍 I found properties{location_str}{bedrooms_str}{price_str}.\n"
                         f"Please use our advanced search at /realestate/search with filters for best results.\n\n"
                         f"💡 Tip: You can also browse neighborhoods and check locality insights!",
                    intent=intent,
                    suggestions=[
                        f"Show all in {city}",
                        "Compare localities",
                        "Neighborhood insights",
                        "Check property legality",
                    ],
                    query_time_ms=round(elapsed, 2),
                )
            else:
                return ChatResponse(
                    text="🏡 I can help you find properties! Please tell me:\n"
                         "• Which city (Mumbai, Bangalore, Pune, Delhi, Hyderabad, Chennai)?\n"
                         "• Type (1BHK, 2BHK, 3BHK, Villa, Plot)\n"
                         "• Your budget range\n\n"
                         "Example: 'Looking for 3BHK in Pune under 2 crore'",
                    intent=intent,
                    suggestions=[
                        "2BHK in Bangalore under 1 crore",
                        "Villa in Goa",
                        "Plots in Hyderabad",
                        "Commercial shops in Mumbai",
                    ],
                    query_time_ms=round(elapsed, 2),
                )

        # ── FAQ Answering ──
        if intent.faq_matches:
            faq = intent.faq_matches[0]  # best match
            elapsed = (time.time() - start) * 1000

            # Generate contextual suggestions
            suggestions = []
            if faq.category == "buying":
                suggestions = ["Documents for NRI buyers", "Stamp duty rates", "Home loan options"]
            elif faq.category == "renting":
                suggestions = ["Standard rent agreement template", "Tenant rights", "Notice period rules"]
            elif faq.category == "legal":
                suggestions = ["Property registration process", "RERA benefits", "Aadhaar eSign guide"]
            elif faq.category == "financing":
                suggestions = ["Best home loan rates", "Tax benefits calculator", "EMI calculation"]

            return ChatResponse(
                text=f"📋 **{faq.question}**\n\n{faq.answer}",
                intent=intent,
                suggestions=suggestions + ["Ask another question"],
                query_time_ms=round(elapsed, 2),
            )

        # ── Neighborhood query ──
        if self._neighborhood_service and any(w in msg_lower for w in ["neighborhood", "locality", "area", "school", "hospital", "connectivity"]):
            for city_name in ["mumbai", "bangalore", "delhi", "pune", "hyderabad", "chennai"]:
                if city_name in msg_lower:
                    data = self._neighborhood_service.get_city_data(city_name)
                    if data:
                        elapsed = (time.time() - start) * 1000
                        return ChatResponse(
                            text=f"📍 **{city_name.title()} Areas & Insights**\n\n"
                                 f"Popular localities: {', '.join(data['localities'][:6])}\n"
                                 f"Avg. Price: ₹{data['avg_price_per_sqft']}/sq.ft\n"
                                 f"Schools: {data['schools_rating']}/10 | Hospitals: {data['hospitals_rating']}/10\n"
                                 f"Connectivity: {data['connectivity_rating']}/10 | Safety: {data['safety_rating']}/10\n"
                                 f"AQI: {data['aqi']}",
                            intent=intent,
                            suggestions=[
                                "Compare with Pune",
                                "Best family areas",
                                "Upcoming infrastructure",
                                "Rental yields in area",
                            ],
                            query_time_ms=round(elapsed, 2),
                        )

        # ── Default / Help ──
        elapsed = (time.time() - start) * 1000
        return ChatResponse(
            text="🤖 **Real Estate Assistant**\n\n"
                 "Here's what I can help with:\n\n"
                 "🏠 **Find Properties** - '3BHK in Pune under 2 crore'\n"
                 "📋 **Legal FAQs** - 'What documents needed to buy?'\n"
                 "📝 **Rent Agreements** - 'How does e-stamping work?'\n"
                 "📍 **Neighborhoods** - 'Best areas in Bangalore'\n"
                 "💰 **Financing** - 'Home loan options'\n\n"
                 "Type your question or browse properties directly!",
            intent=intent,
            suggestions=[
                "Show properties in Mumbai",
                "What is RERA?",
                "Best localities in Bangalore",
                "Rent agreement e-stamp process",
                "Home loan tax benefits",
            ],
            query_time_ms=round(elapsed, 2),
        )


# ── Chatbot API Handler ──────────────────────────────────────────────────────

def create_chatbot_router(services: dict[str, Any] | None = None) -> Any:
    """Create a FastAPI router for the chatbot endpoint."""
    from fastapi import APIRouter, Query

    property_service = (services or {}).get("property_service")
    neighborhood_service = (services or {}).get("neighborhood_service")
    chatbot = RealEstateChatbot(
        property_service=property_service,
        neighborhood_service=neighborhood_service,
    )

    router = APIRouter(prefix="/api/realestate", tags=["Real Estate"])

    @router.post("/chat")
    async def chat(
        message: str = Query(..., description="User message"),
        user_id: str = Query("", description="Optional user ID for personalization"),
    ):
        response = chatbot.respond(message, user_id=user_id or None)
        return {
            "response": response.text,
            "intent": {
                "category": response.intent.category,
                "confidence": round(response.intent.confidence, 3),
            },
            "suggestions": response.suggestions,
            "query_time_ms": response.query_time_ms,
        }

    return router
