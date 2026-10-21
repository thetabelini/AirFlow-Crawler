#!/bin/bash
# Cria os tópicos de cada projeto em projects/<nome>/ (os que têm sources.yaml).
# Roda a cada "docker compose up": quem já existe fica como está.
set -euo pipefail

BOOTSTRAP=${KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}
# 90 dias: dá para reprocessar qualquer coleta desse período do zero.
RETENTION_MS=$((90 * 24 * 60 * 60 * 1000))

create() {
  local topic=$1 partitions=$2
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --create --if-not-exists \
    --topic "$topic" --partitions "$partitions" --replication-factor 1 \
    --config retention.ms="$RETENTION_MS"
}

for dir in /projects/*/; do
  [ -f "${dir}sources.yaml" ] || continue
  project=$(basename "$dir")
  # Os itens são distribuídos pela chave "<fonte>:<id>": o mesmo evento cai sempre na
  # mesma partição, então as versões dele chegam ao consumidor na ordem em que saíram.
  create "$project.events.raw" 3
  create "$project.runs" 1
  create "$project.events.dlq" 1
done

/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --list
