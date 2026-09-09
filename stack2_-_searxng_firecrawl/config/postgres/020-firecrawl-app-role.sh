#!/usr/bin/env bash
set -Eeuo pipefail

: "${FIRECRAWL_DB_USER:?FIRECRAWL_DB_USER is required}"
: "${FIRECRAWL_DB_PASSWORD:?FIRECRAWL_DB_PASSWORD is required}"
: "${FIRECRAWL_DB_NAME:?FIRECRAWL_DB_NAME is required}"

[[ "${POSTGRES_USER:-postgres}" == "postgres" ]] || {
  printf 'ERROR: Stack2 administrative PostgreSQL role must remain postgres\n' >&2
  return 1 2>/dev/null || exit 1
}

[[ "${FIRECRAWL_DB_NAME}" == "postgres" ]] || {
  printf 'ERROR: Firecrawl/NUQ requires FIRECRAWL_DB_NAME=postgres in this stack\n' >&2
  return 1 2>/dev/null || exit 1
}

psql --username postgres --dbname postgres --set=ON_ERROR_STOP=1 <<'EOSQL'
\getenv app_user FIRECRAWL_DB_USER
\getenv app_password FIRECRAWL_DB_PASSWORD

SELECT format(
  'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

SELECT format(
  'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
  :'app_user', :'app_password'
)
\gexec

SELECT format('GRANT CONNECT ON DATABASE postgres TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE ON SCHEMA nuq TO %I', :'app_user')
\gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nuq TO %I', :'app_user')
\gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nuq TO %I', :'app_user')
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA nuq GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
  :'app_user'
)
\gexec
SELECT format(
  'ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA nuq GRANT USAGE, SELECT ON SEQUENCES TO %I',
  :'app_user'
)
\gexec
EOSQL
