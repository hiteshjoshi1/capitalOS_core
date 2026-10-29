-- Read-only login role for the capitalos-postgres MCP server (make db-create-mcp-role).
-- Idempotent: safe to re-run, e.g. after adding tables or rotating the password.
-- The password arrives through the MCP_DB_PASSWORD environment variable, never argv.
\set ON_ERROR_STOP on
\getenv mcp_password MCP_DB_PASSWORD

SELECT 'CREATE ROLE capitalos_mcp_ro LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'capitalos_mcp_ro')
\gexec

ALTER ROLE capitalos_mcp_ro WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 5 PASSWORD :'mcp_password';

-- Read-only at the database level, so it holds whatever the MCP server does.
ALTER ROLE capitalos_mcp_ro SET default_transaction_read_only = on;
ALTER ROLE capitalos_mcp_ro SET statement_timeout = '30s';
ALTER ROLE capitalos_mcp_ro SET idle_in_transaction_session_timeout = '60s';

GRANT CONNECT ON DATABASE capitalos TO capitalos_mcp_ro;
GRANT USAGE ON SCHEMA public TO capitalos_mcp_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO capitalos_mcp_ro;
-- Tables created later by migrations (run as capitalos) are readable too...
ALTER DEFAULT PRIVILEGES FOR ROLE capitalos IN SCHEMA public GRANT SELECT ON TABLES TO capitalos_mcp_ro;
-- ...except credential material, which the assistant never needs.
REVOKE ALL ON TABLE user_credentials, auth_sessions FROM capitalos_mcp_ro;

-- Monitoring views used by Toolbox's diagnostics (pg_stat_activity, locks, settings). Read-only.
GRANT pg_monitor TO capitalos_mcp_ro;
