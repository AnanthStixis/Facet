-- ---------------------------------------------------------------------------
-- Facet - one-time database bootstrap for a local PostgreSQL instance.
--
-- Run once, as a superuser, against your actual working database:
--
--   psql -U postgres -h localhost -d <your-database-name> -f infra/bootstrap.sql
--
-- Creates the extensions and the non-owner application role. Everything after
-- this point is managed by Alembic migrations.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS "vector";

-- The API connects as this role. It is deliberately neither a superuser nor
-- the owner of any table, because Postgres row level security is bypassed by
-- both. Migrations connect as the owner instead.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'facet_app') THEN
        CREATE ROLE facet_app LOGIN PASSWORD 'facet_app_local_password';
    END IF;
END
$$;

-- Grants the current database, whatever it is actually named, rather than
-- assuming a fixed name — a mismatch here silently leaves facet_app with no
-- real access even though the role itself was created successfully.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO facet_app', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO facet_app;

-- Applies to tables created later by migrations.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO facet_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO facet_app;

SELECT
    current_database()                                        AS database,
    (SELECT count(*) FROM pg_extension
      WHERE extname IN ('pgcrypto','pg_trgm','btree_gin','vector')) AS extensions_ready,
    (SELECT count(*) FROM pg_roles WHERE rolname = 'facet_app')     AS app_role_ready;