#!/bin/bash
# Roda só na primeira inicialização do Postgres (volume vazio).
# Cria o usuário e o banco "bjj" e aplica o schema de sql/.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -v pw="$BJJ_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
	CREATE ROLE bjj LOGIN PASSWORD :'pw';
	CREATE DATABASE bjj OWNER bjj;
EOSQL

for f in /sql/*.sql; do
	echo "aplicando $f"
	psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname bjj -c "SET ROLE bjj" -f "$f"
done
