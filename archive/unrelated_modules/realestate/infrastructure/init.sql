-- Real Estate Platform — PostgreSQL Initialization Script
-- Runs on first container startup to create schema

-- ── Migration Tracking Table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Migration V1: Core Tables ────────────────────────────────────────────
INSERT INTO re_migrations (version) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS re_properties (
    property_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    property_type VARCHAR(32) DEFAULT 'apartment',
    listing_type VARCHAR(16) DEFAULT 'sell',
    transaction_type VARCHAR(8) DEFAULT 'sale',
    price NUMERIC(15, 2) DEFAULT 0,
    price_per_sqft NUMERIC(10, 2) DEFAULT 0,
    city VARCHAR(64),
    locality VARCHAR(128),
    state VARCHAR(64),
    pincode VARCHAR(10),
    latitude DOUBLE PRECISION DEFAULT 0,
    longitude DOUBLE PRECISION DEFAULT 0,
    bedrooms INTEGER DEFAULT 0,
    bathrooms INTEGER DEFAULT 0,
    carpet_area_sqft NUMERIC(10, 2) DEFAULT 0,
    furnishing VARCHAR(20) DEFAULT 'unfurnished',
    owner_id VARCHAR(64) DEFAULT '',
    broker_id VARCHAR(64) DEFAULT '',
    developer_id VARCHAR(64) DEFAULT '',
    rera_number VARCHAR(64) DEFAULT '',
    is_active BOOLEAN DEFAULT TRUE,
    is_featured BOOLEAN DEFAULT FALSE,
    is_verified BOOLEAN DEFAULT FALSE,
    views INTEGER DEFAULT 0,
    enquiries INTEGER DEFAULT 0,
    favourites INTEGER DEFAULT 0,
    listed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_property_city ON re_properties(city);
CREATE INDEX IF NOT EXISTS idx_property_type ON re_properties(property_type);
CREATE INDEX IF NOT EXISTS idx_property_price ON re_properties(price);
CREATE INDEX IF NOT EXISTS idx_property_bedrooms ON re_properties(bedrooms);
CREATE INDEX IF NOT EXISTS idx_property_owner ON re_properties(owner_id);
CREATE INDEX IF NOT EXISTS idx_property_active ON re_properties(is_active);
CREATE INDEX IF NOT EXISTS idx_property_city_type ON re_properties(city, property_type);
CREATE INDEX IF NOT EXISTS idx_property_price_city ON re_properties(price, city);

-- ── Leads/CRM Table ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_leads (
    lead_id VARCHAR(64) PRIMARY KEY,
    property_id VARCHAR(64) REFERENCES re_properties(property_id),
    buyer_id VARCHAR(64) DEFAULT '',
    broker_id VARCHAR(64) DEFAULT '',
    status VARCHAR(32) DEFAULT 'new',
    buyer_name VARCHAR(128) DEFAULT '',
    buyer_phone VARCHAR(20) DEFAULT '',
    buyer_email VARCHAR(128) DEFAULT '',
    budget NUMERIC(15, 2) DEFAULT 0,
    notes TEXT,
    source VARCHAR(32) DEFAULT '',
    assigned_to VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_lead_property ON re_leads(property_id);
CREATE INDEX IF NOT EXISTS idx_lead_status ON re_leads(status);
CREATE INDEX IF NOT EXISTS idx_lead_assigned ON re_leads(assigned_to);

-- ── Users Table ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_users (
    email VARCHAR(255) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    picture VARCHAR(512) DEFAULT '',
    role VARCHAR(32) DEFAULT 'buyer',
    is_admin BOOLEAN DEFAULT FALSE,
    phone VARCHAR(20) DEFAULT '',
    language VARCHAR(8) DEFAULT 'en',
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_role ON re_users(role);

-- ── Enquiries Table ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_enquiries (
    enquiry_id VARCHAR(64) PRIMARY KEY,
    property_id VARCHAR(64) REFERENCES re_properties(property_id),
    user_id VARCHAR(64) DEFAULT '',
    name VARCHAR(128) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(20),
    message TEXT,
    enquirer_type VARCHAR(32) DEFAULT 'buyer',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Rent Agreements Table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_rent_agreements (
    agreement_id VARCHAR(64) PRIMARY KEY,
    property_id VARCHAR(64) REFERENCES re_properties(property_id),
    landlord_id VARCHAR(64),
    tenant_id VARCHAR(64),
    rent_amount NUMERIC(12, 2) DEFAULT 0,
    security_deposit NUMERIC(12, 2) DEFAULT 0,
    lease_start DATE,
    lease_end DATE,
    status VARCHAR(32) DEFAULT 'draft',
    e_stamp_paper_number VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Builder Projects Table ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS re_builder_projects (
    project_id VARCHAR(64) PRIMARY KEY,
    developer_id VARCHAR(64),
    name VARCHAR(255) NOT NULL,
    rera_registration VARCHAR(64) DEFAULT '',
    city VARCHAR(64),
    total_units INTEGER DEFAULT 0,
    available_units INTEGER DEFAULT 0,
    status VARCHAR(32) DEFAULT 'ongoing',
    possession_date VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
