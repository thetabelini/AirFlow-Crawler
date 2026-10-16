#!/bin/bash
# Prepara uma VM Ubuntu da Oracle Cloud para rodar o AirFlow-Crawler.
# Rode uma vez, como o usuário ubuntu:  bash scripts/setup-vm.sh
# Pode rodar de novo sem problema: cada passo verifica se já foi feito.
set -euo pipefail

echo "== 1/3 firewall: liberando 80/tcp, 443/tcp e 443/udp"
# A imagem Ubuntu da Oracle tem regras de iptables que rejeitam tudo além do SSH.
# As novas regras entram antes do primeiro REJECT da chain INPUT.
allow() {
	local proto=$1 port=$2
	if sudo iptables -C INPUT -p "$proto" --dport "$port" -j ACCEPT 2>/dev/null; then
		return
	fi
	local line
	line=$(sudo iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" {print $1; exit}')
	if [ -n "$line" ]; then
		sudo iptables -I INPUT "$line" -p "$proto" --dport "$port" -j ACCEPT
	else
		sudo iptables -A INPUT -p "$proto" --dport "$port" -j ACCEPT
	fi
}
allow tcp 80
allow tcp 443
allow udp 443
if command -v netfilter-persistent >/dev/null; then
	sudo netfilter-persistent save
else
	echo "aviso: netfilter-persistent não encontrado; as regras valem até o próximo reboot"
fi

echo "== 2/3 swap de 4 GB"
if ! swapon --show | grep -q /swapfile; then
	sudo fallocate -l 4G /swapfile
	sudo chmod 600 /swapfile
	sudo mkswap /swapfile
	sudo swapon /swapfile
	grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== 3/3 Docker"
if ! command -v docker >/dev/null; then
	curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"

echo
echo "Pronto. Saia e entre de novo no SSH para usar o docker sem sudo."
