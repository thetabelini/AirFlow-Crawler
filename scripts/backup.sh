#!/bin/bash
# Backup dos bancos do Postgres (airflow e um por projeto), um arquivo pg_dump por banco.
# Rode da VM, com a stack no ar. No cron (crontab -e), todo dia às 03:15:
#   15 3 * * * /home/ubuntu/AirFlow-Crawler/scripts/backup.sh >> /home/ubuntu/backup.log 2>&1
#
# Variáveis opcionais:
#   BACKUP_DIR        onde salvar (padrão: ~/backups)
#   BACKUP_KEEP_DAYS  quantos dias manter localmente (padrão: 7)
#   OCI_BUCKET        se definida, envia cada arquivo para esse bucket do Object Storage
#                     (precisa do OCI CLI com instance principal; veja docs/deploy-oracle.md)
set -euo pipefail

cd "$(dirname "$0")/.."
BACKUP_DIR=${BACKUP_DIR:-$HOME/backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-7}
OCI=${OCI_CLI:-oci}
stamp=$(date +%F)
mkdir -p "$BACKUP_DIR"

databases=$(docker compose exec -T postgres psql -U airflow -d postgres -tAc \
	"SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1")

for db in $databases; do
	file="$BACKUP_DIR/${db}_${stamp}.dump"
	docker compose exec -T postgres pg_dump -U airflow -Fc "$db" > "$file.tmp"
	mv "$file.tmp" "$file"
	echo "$(date -Is) backup $db: $(du -h "$file" | cut -f1)"
	if [ -n "${OCI_BUCKET:-}" ]; then
		"$OCI" os object put --auth instance_principal --bucket-name "$OCI_BUCKET" \
			--file "$file" --name "$(basename "$file")" --force >/dev/null
		echo "$(date -Is) enviado para o bucket $OCI_BUCKET"
	fi
done

find "$BACKUP_DIR" -name '*.dump' -mtime +"$KEEP_DAYS" -delete
