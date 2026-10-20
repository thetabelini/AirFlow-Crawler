#!/bin/bash
# Chaves de API da tela e API de dados (https://dados.<DOMAIN>). Rode na pasta do projeto, com a stack no ar.
#   bash scripts/api-keys.sh criar <nome>     cria a chave e mostra uma única vez
#   bash scripts/api-keys.sh listar           chaves, situação, último uso e requisições
#   bash scripts/api-keys.sh revogar <nome>   corta o acesso na hora
# Quem recebe usa o cabeçalho:  X-API-Key: <chave>
set -euo pipefail
cd "$(dirname "$0")/.."

psql_web() {
	docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U airflow -d web "$@"
}

uso() {
	sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
	exit 1
}

case "${1:-}" in
criar)
	name=${2:-}
	[[ "$name" =~ ^[A-Za-z0-9._@-]{1,64}$ ]] || { echo "informe um nome (letras, números, . _ @ -)" >&2; exit 1; }
	active=$(psql_web -tAq -v name="$name" <<-'EOSQL'
		SELECT count(*) FROM web.api_keys WHERE name = :'name' AND revoked_at IS NULL;
	EOSQL
	)
	if [ "$active" != "0" ]; then
		echo "já existe uma chave ativa para $name; revogue antes de criar outra" >&2
		exit 1
	fi
	key="afc_$(openssl rand -hex 20)"
	psql_web -q -v name="$name" -v key="$key" <<-'EOSQL'
		INSERT INTO web.api_keys (name, key_hash, key_prefix)
		VALUES (:'name', encode(sha256(convert_to(:'key', 'UTF8')), 'hex'), left(:'key', 8));
	EOSQL
	echo "Chave de $name (guarde agora: ela não é mostrada de novo):"
	echo
	echo "  $key"
	echo
	echo "Uso: curl -H \"X-API-Key: $key\" https://dados.<DOMAIN>/bjj/api/eventos"
	;;
listar)
	psql_web -c "
		SELECT name AS nome, key_prefix || '…' AS chave, created_at::date AS criada,
		       CASE WHEN revoked_at IS NULL THEN 'ativa' ELSE 'revogada ' || revoked_at::date END AS situacao,
		       to_char(last_used_at, 'YYYY-MM-DD HH24:MI') AS ultimo_uso, requests AS requisicoes
		FROM web.api_keys ORDER BY id"
	;;
revogar)
	name=${2:-}
	[ -n "$name" ] || uso
	revoked=$(psql_web -tAq -v name="$name" <<-'EOSQL'
		UPDATE web.api_keys SET revoked_at = now()
		WHERE name = :'name' AND revoked_at IS NULL RETURNING name;
	EOSQL
	)
	if [ -n "$revoked" ]; then
		echo "chave de $name revogada"
	else
		echo "nenhuma chave ativa para $name" >&2
		exit 1
	fi
	;;
*)
	uso
	;;
esac
