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

Clique em **Create**. Se aparecer **Out of capacity**, veja [Sem capacidade para A1](#sem-capacidade-para-a1).

Quando ficar *Running*, anote o **Public IP address**.

### Limite gratuito do A1

O Always Free cobre **4 OCPU e 24 GB de A1 no total**, somando todas as instâncias A1 que não foram terminadas, inclusive as paradas. Numa conta Pay As You Go, o que passar disso é cobrado. Se já existe outra instância A1 (em **Compute → Instances**, coluna *Shape*), termine-a se não for usar, ou peça só o que sobra.

### Sem capacidade para A1

"Out of capacity" quer dizer que a Oracle não tem máquinas A1 livres na região naquele momento; trocar o tamanho do disco não muda nada. Em regiões com um só availability domain, como São Paulo, o caminho é tentar até conseguir. O `scripts/oci-retry-launch.sh` faz isso do seu computador, a cada 2 minutos, e para quando a VM é criada. Ele também confere o limite gratuito antes de começar.

1. Instale e configure o OCI CLI:
   ```bash
   sudo apt install -y pipx && pipx install oci-cli && pipx ensurepath   # abra um terminal novo depois
   oci setup config
   ```
   O `oci setup config` pede o OCID do usuário (console → ícone de perfil → **My profile**), o OCID da tenancy (ícone de perfil → **Tenancy**) e a região (`sa-saopaulo-1`). Aceite gerar a chave de API e depois cadastre a pública: **My profile → API keys → Add API key → Paste a public key**, com o conteúdo de `~/.oci/oci_api_key_public.pem`. Teste com `oci iam region list`.
2. Descubra a subnet pública. As tentativas pelo console costumam deixar uma VCN criada:
   ```bash
   oci network subnet list -c <OCID-da-tenancy> --query 'data[].{nome:"display-name",id:id}' --output table
   ```
   Se não houver nenhuma, crie em **Networking → Virtual cloud networks → Start VCN Wizard → Create VCN with Internet Connectivity**.
3. Rode e deixe trabalhando (de madrugada, por exemplo):
   ```bash
   COMPARTMENT_ID=<OCID-da-tenancy> SUBNET_ID=<OCID-da-subnet-pública> bash scripts/oci-retry-launch.sh
   ```
   Para pedir menos: `OCPUS=2 MEMORY_GB=12`. A VM pode ser aumentada depois em **Instance → Edit → Shape** (ela reinicia).

Quando o script terminar, ele mostra o IP público. Siga para o passo 2.

## 2. Abrir as portas 80 e 443

Na página da instância → link da **Subnet** → **Security** (ou *Security Lists*) → a security list padrão → **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port Range |
| --- | --- | --- |
| `0.0.0.0/0` | TCP | `80,443` |

A porta 22 já vem aberta. Opcional: trocar a origem da regra do SSH para o seu IP (`<seu-ip>/32`); se o seu IP mudar, você perde o acesso até atualizar a regra.

## 3. Preparar a VM

```bash
ssh ubuntu@<IP>

git clone https://github.com/thetabelini/AirFlow-Crawler.git
cd AirFlow-Crawler
bash scripts/setup-vm.sh
exit
```

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
WEB_DB_PASSWORD=$(openssl rand -hex 16)
WEB_USERS=felipe:$(openssl rand -hex 8)
EOF
chmod 600 .env
cat .env      # anote DOMAIN e AIRFLOW_ADMIN_PASSWORD

docker compose up -d --build
```

**VM pequena (1 OCPU e 4 GB):** antes do `up`, ative o perfil reduzido (1 processo na API, paralelismo 2, sem triggerer e limites de memória menores):

```bash
echo "COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml" >> .env
```

Medido com a DAG do BJJ rodando, a stack usa cerca de 1,3 GB. Quando a VM crescer, apague essa linha do `.env` e rode `docker compose up -d`.

O primeiro build leva alguns minutos (numa VM de 1 OCPU, uns 15 a 20). Acompanhe com `docker compose ps` até todos ficarem `healthy` (o `db-init` e o `airflow-init` aparecem como `exited (0)`, o que é o esperado).

**Domínio:** `<ip-com-traços>.sslip.io` é um endereço gratuito que aponta para o IP da VM, e o Caddy consegue emitir um certificado HTTPS válido para ele. Se tiver um domínio próprio, crie um registro `A` apontando para o IP e use-o no `DOMAIN`.

## 5. Acessar

Abra `https://<DOMAIN>` e entre com `admin` e a `AIRFLOW_ADMIN_PASSWORD`.
A tela de dados fica em `https://dados.<DOMAIN>` (no Airflow: menu **Plugins → Dados coletados**), com o usuário e a senha de `WEB_USERS`.
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

O `db-init` aplica as migrações novas e o `airflow-init` cria os pools de projetos novos. O Caddy recarrega o `caddy/Caddyfile` sozinho quando ele muda.

> Vindo de uma versão anterior, em que o `Caddyfile` ficava na raiz do repositório? Depois do `git pull`, recrie o Caddy uma vez: `docker compose up -d --force-recreate caddy`. Se um projeto novo foi adicionado, coloque a `<NOME>_DB_PASSWORD` dele no `.env` antes.
