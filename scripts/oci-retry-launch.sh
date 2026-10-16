#!/bin/bash
# Tenta criar a VM A1 até a Oracle ter capacidade. Roda no SEU computador, não na VM.
# Precisa do OCI CLI configurado (oci setup config); veja docs/deploy-oracle.md, "Sem capacidade para A1".
#
# Uso:
#   COMPARTMENT_ID=ocid1.tenancy... SUBNET_ID=ocid1.subnet... bash scripts/oci-retry-launch.sh
#
# Opcionais: OCPUS (4), MEMORY_GB (24), BOOT_GB (100), INTERVAL em segundos (120),
#            SSH_KEY (~/.ssh/id_rsa.pub), NAME (airflow-crawler), AD e IMAGE_ID (descobertos sozinhos).
set -uo pipefail

: "${COMPARTMENT_ID:?defina COMPARTMENT_ID (para a conta toda, é o OCID da tenancy)}"
: "${SUBNET_ID:?defina SUBNET_ID (OCID da subnet pública)}"
OCPUS=${OCPUS:-4}
MEMORY_GB=${MEMORY_GB:-24}
BOOT_GB=${BOOT_GB:-100}
INTERVAL=${INTERVAL:-120}
SSH_KEY=${SSH_KEY:-$HOME/.ssh/id_rsa.pub}
NAME=${NAME:-airflow-crawler}
SHAPE=VM.Standard.A1.Flex

[ -f "$SSH_KEY" ] || { echo "chave pública não encontrada: $SSH_KEY" >&2; exit 1; }

# O Always Free cobre 4 OCPU e 24 GB de A1 somando TODAS as instâncias A1 que não foram
# terminadas (paradas também contam). Numa conta Pay As You Go, o que passar disso é cobrado.
a1_usage() {
	oci compute instance list --compartment-id "$COMPARTMENT_ID" --all --raw-output \
		--query "sum(data[?shape=='$SHAPE' && \"lifecycle-state\"!='TERMINATED' && \"lifecycle-state\"!='TERMINATING'].\"shape-config\".\"$1\")"
}
used_ocpus=$(a1_usage ocpus); used_ocpus=${used_ocpus:-0}
used_memory=$(a1_usage memory-in-gbs); used_memory=${used_memory:-0}
echo "A1 já em uso (inclui instâncias paradas): $used_ocpus OCPU, $used_memory GB"
if awk -v u="$used_ocpus" -v n="$OCPUS" -v um="$used_memory" -v nm="$MEMORY_GB" \
	'BEGIN { exit !((u + n > 4) || (um + nm > 24)) }'; then
	echo "pedir $OCPUS OCPU e $MEMORY_GB GB passaria do limite gratuito (4 OCPU, 24 GB)." >&2
	echo "Termine a instância A1 que não usa, ou reduza OCPUS/MEMORY_GB." >&2
	exit 1
fi

AD=${AD:-$(oci iam availability-domain list --compartment-id "$COMPARTMENT_ID" \
	--query 'data[0].name' --raw-output)} || exit 1
IMAGE_ID=${IMAGE_ID:-$(oci compute image list --compartment-id "$COMPARTMENT_ID" \
	--operating-system "Canonical Ubuntu" --operating-system-version "24.04" --shape "$SHAPE" \
	--sort-by TIMECREATED --sort-order DESC --query 'data[0].id' --raw-output)} || exit 1
[ -n "$IMAGE_ID" ] && [ "$IMAGE_ID" != "null" ] || { echo "imagem Ubuntu 24.04 para $SHAPE não encontrada" >&2; exit 1; }

echo "AD: $AD"
echo "imagem: $IMAGE_ID"
echo "shape: $SHAPE, $OCPUS OCPU, $MEMORY_GB GB, disco $BOOT_GB GB; tentando a cada ${INTERVAL}s (Ctrl+C para parar)"

attempt=0
while true; do
	attempt=$((attempt + 1))
	if output=$(oci compute instance launch \
		--compartment-id "$COMPARTMENT_ID" \
		--availability-domain "$AD" \
		--display-name "$NAME" \
		--shape "$SHAPE" \
		--shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
		--image-id "$IMAGE_ID" \
		--subnet-id "$SUBNET_ID" \
		--assign-public-ip true \
		--boot-volume-size-in-gbs "$BOOT_GB" \
		--ssh-authorized-keys-file "$SSH_KEY" \
		--wait-for-state RUNNING \
		--query 'data.id' --raw-output 2>&1); then
		instance_id=$(echo "$output" | grep -o 'ocid1\.instance[^" ]*' | tail -1)
		echo "$(date '+%F %T') criada na tentativa $attempt: $instance_id"
		ip=$(oci compute instance list-vnics --instance-id "$instance_id" \
			--query 'data[0]."public-ip"' --raw-output)
		echo "IP público: $ip"
		echo "Teste: ssh ubuntu@$ip"
		exit 0
	fi

	if echo "$output" | grep -qi "capacity"; then
		echo "$(date '+%F %T') tentativa $attempt: sem capacidade; nova tentativa em ${INTERVAL}s"
		sleep "$INTERVAL"
	elif echo "$output" | grep -qi "TooManyRequests"; then
		echo "$(date '+%F %T') tentativa $attempt: muitas requisições; esperando $((INTERVAL * 3))s"
		sleep $((INTERVAL * 3))
	else
		echo "$(date '+%F %T') erro inesperado, parando:" >&2
		echo "$output" >&2
		exit 1
	fi
done
