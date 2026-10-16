# Deploy na Oracle Cloud (Always Free)

Do zero até o Airflow no ar em `https://<seu-endereço>`, com backup diário.
Os menus do console da Oracle mudam de nome de vez em quando: se algum não bater, procure pelo nome do recurso na busca do topo do console.

## 0. Antes de começar

- Uma conta na Oracle Cloud. **Recomendado:** converter para *Pay As You Go* (Billing → Upgrade). Os recursos Always Free continuam gratuitos, a Oracle para de recuperar VMs que ficam ociosas por 7 dias, e fica mais fácil conseguir uma VM A1. Coloque um alerta de orçamento (Billing → Budgets) de R$ 1 para ser avisado de qualquer cobrança.
- Uma chave SSH no seu computador. Se não tiver: `ssh-keygen -t ed25519`. A chave pública fica em `~/.ssh/id_ed25519.pub`.

## 1. Criar a VM

Console → **Compute → Instances → Create instance**:

| Campo | Valor |
| --- | --- |
| Name | `airflow-crawler` |
| Image | **Change image** → Ubuntu → *Canonical Ubuntu 24.04* |
| Shape | **Change shape** → Ampere → `VM.Standard.A1.Flex`, **4 OCPU, 24 GB** |
| Networking | *Create new virtual cloud network* + *public subnet*, com **Assign a public IPv4 address** marcado |
| SSH keys | *Upload public key files* → `~/.ssh/id_ed25519.pub` |
| Boot volume | *Specify a custom boot volume size* → **100 GB** |

Clique em **Create**. Se aparecer **Out of capacity**, tente outro *Availability domain* na mesma tela, ou tente de novo mais tarde.

Quando ficar *Running*, anote o **Public IP address**.

## 2. Abrir as portas 80 e 443

Na página da instância → link da **Subnet** → **Security** (ou *Security Lists*) → a security list padrão → **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port Range |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80,443` |

A porta 22 já vem aberta. Opcional: trocar a origem da regra do SSH para o seu IP (`<seu-ip>/32`); se o seu IP mudar, você perde o acesso até atualizar a regra.

## 3. Preparar a VM

```bash
ssh ubuntu@<IP>

git clone -b claude/serene-lovelace-s4ony2 https://github.com/thetabelini/AirFlow-Crawler.git
cd AirFlow-Crawler
bash scripts/setup-vm.sh
exit
```

> Quando o branch for mesclado no `main`, clone sem o `-b claude/serene-lovelace-s4ony2`.

O `setup-vm.sh` libera 80/443 no firewall do próprio Ubuntu (a imagem da Oracle bloqueia tudo além do SSH, mesmo com a security list aberta), cria 4 GB de swap e instala o Docker. Saia e entre de novo para o grupo `docker` valer.

## 4. Configurar e subir

```bash
ssh ubuntu@<IP>
cd AirFlow-Crawler

IP_DASHES=$(curl -s https://ifconfig.me | tr . -)
cat > .env <<EOF
DOMAIN=${IP_DASHES}.sslip.io
AIRFLOW_ADMIN_USER=admin
AIRFLOW_ADMIN_PASSWORD=$(openssl rand -hex 12)
AIRFLOW_DB_PASSWORD=$(openssl rand -hex 16)
BJJ_DB_PASSWORD=$(openssl rand -hex 16)
AIRFLOW_FERNET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
AIRFLOW_JWT_SECRET=$(openssl rand -hex 32)
EOF
chmod 600 .env
cat .env      # anote DOMAIN e AIRFLOW_ADMIN_PASSWORD

docker compose up -d --build
```

O primeiro build leva alguns minutos. Acompanhe com `docker compose ps` até todos ficarem `healthy` (o `db-init` e o `airflow-init` aparecem como `exited (0)`, o que é o esperado).

**Domínio:** `<ip-com-traços>.sslip.io` é um endereço gratuito que aponta para o IP da VM, e o Caddy consegue emitir um certificado HTTPS válido para ele. Se tiver um domínio próprio, crie um registro `A` apontando para o IP e use-o no `DOMAIN`.

## 5. Acessar

Abra `https://<DOMAIN>` e entre com `admin` e a `AIRFLOW_ADMIN_PASSWORD`.
Ative a DAG `bjj__soucompetidor` e clique em **Trigger** para a primeira coleta. Depois disso ela roda sozinha uma vez por dia.

Conferir os dados:

```bash
docker compose exec postgres psql -U bjj -d bjj -c 'select count(*) from bjj.events'
```

Se o HTTPS não abrir, veja `docker compose logs caddy`: o certificado só sai com as portas 80 e 443 abertas na security list (passo 2) e no Ubuntu (passo 3).

## 6. Backup diário

```bash
crontab -e
```

Adicione a linha (backup às 03:15, guarda 7 dias em `~/backups`):

```
15 3 * * * /home/ubuntu/AirFlow-Crawler/scripts/backup.sh >> /home/ubuntu/backup.log 2>&1
```

Teste na hora com `bash scripts/backup.sh`.

### Opcional: cópia no Object Storage

O backup em `~/backups` some se a VM for apagada. Para mandar uma cópia ao Object Storage (20 GB grátis):

1. **Storage → Buckets → Create bucket**: `airflow-crawler-backups`. Em *Lifecycle Policy Rules*, crie uma regra para apagar objetos com mais de 30 dias.
2. **Identity & Security → Domains → Default → Dynamic groups → Create**: nome `airflow-crawler-vm`, regra `instance.id = '<OCID da instância>'` (o OCID está na página da instância).
3. **Identity & Security → Policies → Create policy** (no compartimento da VM), com a regra:
   ```
   Allow dynamic-group 'Default'/'airflow-crawler-vm' to manage objects in compartment <nome-do-compartimento> where target.bucket.name = 'airflow-crawler-backups'
   ```
4. Na VM, instale o OCI CLI e teste:
   ```bash
   sudo apt-get install -y pipx && pipx install oci-cli && pipx ensurepath
   ~/.local/bin/oci os object list --auth instance_principal --bucket-name airflow-crawler-backups
   ```
5. Troque a linha do cron por:
   ```
   15 3 * * * OCI_BUCKET=airflow-crawler-backups OCI_CLI=/home/ubuntu/.local/bin/oci /home/ubuntu/AirFlow-Crawler/scripts/backup.sh >> /home/ubuntu/backup.log 2>&1
   ```

### Restaurar

```bash
docker compose exec -T postgres pg_restore -U airflow -d bjj --clean --if-exists < ~/backups/bjj_<data>.dump
```

## Atualizar depois

```bash
cd ~/AirFlow-Crawler
git pull
docker compose up -d --build
```

O `db-init` aplica as migrações novas e o `airflow-init` cria os pools de projetos novos. Se um projeto novo foi adicionado, coloque a `<NOME>_DB_PASSWORD` dele no `.env` antes.
