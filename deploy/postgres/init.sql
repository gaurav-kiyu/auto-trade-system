-- OPB PostgreSQL Initialization Script
-- Creates all databases, schemas, roles needed for production deployment
-- Compatible with the migration script: scripts/migrate_to_postgresql.py
--
-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  WARNING: This script creates databases and roles but does NOT     ║
-- ║  grant schema-level permissions. After first init, you MUST run:   ║
-- ║                                                                    ║
-- ║  For each database (opb_trades, opb_journal, ... opb_replay):      ║
-- ║    \c <database>                                                   ║
-- ║    GRANT USAGE ON SCHEMA public TO opb_app;                        ║
-- ║    GRANT ALL ON ALL TABLES IN SCHEMA public TO opb_app;            ║
-- ║    GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO opb_app;         ║
-- ║    ALTER DEFAULT PRIVILEGES IN SCHEMA public                       ║
-- ║      GRANT ALL ON TABLES TO opb_app;                               ║
-- ║    ALTER DEFAULT PRIVILEGES IN SCHEMA public                       ║
-- ║      GRANT ALL ON SEQUENCES TO opb_app;                            ║
-- ║                                                                    ║
-- ║  Failure to run these will cause 'permission denied for schema      ║
-- ║  public' errors when opb_app tries to access tables.                ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ── Application Roles ─────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'opb_app') THEN
        CREATE ROLE opb_app WITH LOGIN PASSWORD 'changeme!' CONNECTION LIMIT 50;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'opb_monitor') THEN
        CREATE ROLE opb_monitor WITH LOGIN PASSWORD 'changeme!' CONNECTION LIMIT 5;
    END IF;
END
$$;

-- ── Database Creation ─────────────────────────────────────────────────────
-- 16 databases matching the SQLite migration destinations

SELECT 'CREATE DATABASE opb_trades'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_trades')\gexec

SELECT 'CREATE DATABASE opb_journal'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_journal')\gexec

SELECT 'CREATE DATABASE opb_ml'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_ml')\gexec

SELECT 'CREATE DATABASE opb_oi'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_oi')\gexec

SELECT 'CREATE DATABASE opb_signals'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_signals')\gexec

SELECT 'CREATE DATABASE opb_lineage'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_lineage')\gexec

SELECT 'CREATE DATABASE opb_events'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_events')\gexec

SELECT 'CREATE DATABASE opb_execution'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_execution')\gexec

SELECT 'CREATE DATABASE opb_features'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_features')\gexec

SELECT 'CREATE DATABASE opb_shadow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_shadow')\gexec

SELECT 'CREATE DATABASE opb_strategy_perf'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_strategy_perf')\gexec

SELECT 'CREATE DATABASE opb_strategy_ver'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_strategy_ver')\gexec

SELECT 'CREATE DATABASE opb_order_state'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_order_state')\gexec

SELECT 'CREATE DATABASE opb_regime'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_regime')\gexec

SELECT 'CREATE DATABASE opb_fundamentals'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_fundamentals')\gexec

SELECT 'CREATE DATABASE opb_replay'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'opb_replay')\gexec

-- ── Grant Privileges (per database) ────────────────────────────────────────
DO $$
DECLARE
    db_name text;
    databases text[] := ARRAY[
        'opb_trades', 'opb_journal', 'opb_ml', 'opb_oi', 'opb_signals',
        'opb_lineage', 'opb_events', 'opb_execution', 'opb_features',
        'opb_shadow', 'opb_strategy_perf', 'opb_strategy_ver',
        'opb_order_state', 'opb_regime', 'opb_fundamentals', 'opb_replay'
    ];
BEGIN
    FOREACH db_name IN ARRAY databases
    LOOP
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO opb_app', db_name);
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO opb_monitor', db_name);
    END LOOP;
END
$$;

-- ── Schema and Table Permissions (applied after databases exist) ──────────
-- These must be run against EACH database after creation.
-- The application user needs schema-level access in addition to CONNECT.
--
-- Run against each database (replace opb_trades with each DB name):
--
--   \c opb_trades
--   GRANT USAGE ON SCHEMA public TO opb_app;
--   GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO opb_app;
--   GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO opb_app;
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO opb_app;
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO opb_app;
--
-- Post-migration script (scripts/migrate_to_postgresql.py) handles
-- granting these permissions automatically during migration.

-- ── Extensions (per database, optional) ────────────────────────────────────
-- Run against individual databases as needed:
--   CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
--   CREATE EXTENSION IF NOT EXISTS pgcrypto;
