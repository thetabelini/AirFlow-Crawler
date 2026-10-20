#!/bin/bash
# Roda a cada "docker compose up" (serviço db-init). Para cada projects/<nome>/ com sql/:
#   1. cria (ou atualiza a senha de) o usuário <nome> e o banco <nome>
#   2. aplica as migrações que ainda não rodaram: primeiro core/sql/, depois projects/<nome>/sql/
#   3. com WEB_DB_PASSWORD definida, dá ao usuário web_reader leitura no schema <nome>
# Também mantém o banco "web" da própria plataforma (chaves de API, migrações em web/sql/).
# As migrações aplicadas ficam em public.schema_migrations de cada banco.
set -euo pipefail

CORE_SQL=/core-sql
PROJECTS=/projects
WEB_SQL=/web-sql

apply_migrations() {
	local project=$1 prefix=$2 dir=$3
	for file in "$dir"/*.sql; do
		[ -e "$file" ] || continue
		local key applied
		key="$prefix/$(basename "$file")"
		applied=$(psql -d "$project" -tAc "SELECT 1 FROM public.schema_migrations WHERE filename = '$key'")
		[ "$applied" = "1" ] && continue
		echo "  aplicando $key"
		psql -v ON_ERROR_STOP=1 --single-transaction -d "$project" -v schema="$project" \
			-c "SET ROLE $project" \
			-f "$file" \
			-c "INSERT INTO public.schema_migrations (filename) VALUES ('$key')"
	done
}

# Usuário só de leitura do serviço web (tela e API).
if [ -n "${WEB_DB_PASSWORD:-}" ]; then
	psql -v ON_ERROR_STOP=1 -d postgres -v pw="$WEB_DB_PASSWORD" <<-'EOSQL'
		SELECT 'CREATE ROLE web_reader LOGIN'
		WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'web_reader') \gexec
		SELECT format('ALTER ROLE web_reader PASSWORD %L', :'pw') \gexec
	EOSQL
fi

# Banco da plataforma: dono "web" (sem login), schema "web".
echo "plataforma (banco web)"
psql -v ON_ERROR_STOP=1 -d postgres <<-'EOSQL'
	SELECT 'CREATE ROLE web NOLOGIN'
	WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'web') \gexec
	SELECT 'CREATE DATABASE web OWNER web'
	WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'web') \gexec
EOSQL
psql -v ON_ERROR_STOP=1 -d web -c "SET ROLE web" -c "
	CREATE TABLE IF NOT EXISTS public.schema_migrations (
		filename   text PRIMARY KEY,
		applied_at timestamptz NOT NULL DEFAULT now()
	)"
apply_migrations web web "$WEB_SQL"
if [ -n "${WEB_DB_PASSWORD:-}" ]; then
	# Lê as chaves, atualiza só os contadores de uso e mantém a contagem do limite.
	psql -v ON_ERROR_STOP=1 -d web <<-'EOSQL'
		GRANT CONNECT ON DATABASE web TO web_reader;
		GRANT USAGE ON SCHEMA web TO web_reader;
		GRANT SELECT, UPDATE (last_used_at, requests) ON web.api_keys TO web_reader;
		GRANT SELECT, INSERT, UPDATE, DELETE ON web.api_key_usage TO web_reader;
	EOSQL
fi

for dir in "$PROJECTS"/*/; do
	project=$(basename "$dir")
	[ -d "$dir/sql" ] || continue
	if [[ ! "$project" =~ ^[a-z][a-z0-9_]*$ ]] || [ "$project" = "web" ]; then
		echo "nome de projeto inválido: $project" >&2
		exit 1
	fi
	var="${project^^}_DB_PASSWORD"
	password="${!var:-}"
	if [ -z "$password" ]; then
		echo "defina $var no .env" >&2
		exit 1
	fi

	echo "projeto $project"
	psql -v ON_ERROR_STOP=1 -d postgres -v project="$project" -v pw="$password" <<-'EOSQL'
		SELECT format('CREATE ROLE %I LOGIN', :'project')
		WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'project') \gexec
		SELECT format('ALTER ROLE %I PASSWORD %L', :'project', :'pw') \gexec
		SELECT format('CREATE DATABASE %I OWNER %I', :'project', :'project')
		WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'project') \gexec
	EOSQL

	psql -v ON_ERROR_STOP=1 -d "$project" -c "SET ROLE $project" -c "
		CREATE TABLE IF NOT EXISTS public.schema_migrations (
			filename   text PRIMARY KEY,
			applied_at timestamptz NOT NULL DEFAULT now()
		)"

	apply_migrations "$project" core "$CORE_SQL"
	apply_migrations "$project" "$project" "$dir/sql"

	if [ -n "${WEB_DB_PASSWORD:-}" ]; then
		psql -v ON_ERROR_STOP=1 -d "$project" -v project="$project" <<-'EOSQL'
			SELECT format('GRANT CONNECT ON DATABASE %I TO web_reader', :'project') \gexec
			SELECT format('GRANT USAGE ON SCHEMA %I TO web_reader', :'project') \gexec
			SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO web_reader', :'project') \gexec
			SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I GRANT SELECT ON TABLES TO web_reader', :'project', :'project') \gexec
		EOSQL
	fi
done
