-- Initialise les deux rôles PostgreSQL attendus par Marinade (voir README, « Démarrage rapide »).
--   marinade_owner : propriétaire de la base, exécute les migrations Alembic.
--   marinade_app   : utilisé par l'API. Ni superutilisateur, ni propriétaire des tables, ni BYPASSRLS.
--
-- Idempotent : peut être rejoué sans erreur (crée les rôles s'ils manquent, réaffecte les mots de passe).
--
-- Usage (connexion en administrateur à la base cible) :
--   psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -v owner_password="$OWNER_PASSWORD" -v app_password="$APP_PASSWORD" \
--        -f scripts/db/bootstrap_roles.sql

\set ON_ERROR_STOP on

-- Rôles
SELECT format('CREATE ROLE marinade_owner LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'owner_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marinade_owner') \gexec
SELECT format('ALTER ROLE marinade_owner LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'owner_password') \gexec

SELECT format('CREATE ROLE marinade_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marinade_app') \gexec
SELECT format('ALTER ROLE marinade_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', :'app_password') \gexec

-- Propriété de la base : le propriétaire applicatif exécute les migrations
SELECT format('ALTER DATABASE %I OWNER TO marinade_owner', current_database()) \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO marinade_app', current_database()) \gexec

-- Droits du rôle applicatif sur le schéma public, y compris pour les tables créées plus tard
GRANT USAGE ON SCHEMA public TO marinade_app;
ALTER DEFAULT PRIVILEGES FOR ROLE marinade_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marinade_app;
ALTER DEFAULT PRIVILEGES FOR ROLE marinade_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO marinade_app;
