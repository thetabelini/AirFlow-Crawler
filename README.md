# BJJ Crawler

Coleta campeonatos de jiu-jitsu de sites de eventos e guarda tudo num Postgres.
Cada site é uma DAG do Airflow que busca uma URL fixa de listagem, faz o parse e grava os eventos.

Roda inteiro numa VM Always Free da Oracle Cloud (Ampere A1, 4 OCPU, 24 GB), com Docker Compose.

## O que sobe

| Serviço | Função |
| --- | --- |
| `postgres` | PostgreSQL 16 com dois bancos: `airflow` (metadados) e `bjj` (eventos) |
| `airflow-init` | Migra o banco do Airflow e cria o usuário admin; roda uma vez e sai |
| `airflow-apiserver` | Interface web e API do Airflow (porta 8080, só em localhost) |
| `airflow-scheduler` | Agenda as DAGs e executa as tasks (LocalExecutor) |
| `airflow-dag-processor` | Lê os arquivos de `dags/` |
| `airflow-triggerer` | Tasks deferrable |
| `caddy` | HTTPS automático na frente da interface (portas 80 e 443) |

A imagem do Airflow é estendida no `Dockerfile` com `httpx`, `selectolax`, `psycopg` e Playwright + Chromium.

## Rodando

Precisa de Docker com o plugin compose.

```bash
cp .env.example .env
```

Preencha o `.env`. As chaves podem ser geradas assim:

```bash
openssl rand -base64 32 | tr '+/' '-_'   # AIRFLOW_FERNET_KEY
openssl rand -hex 32                     # AIRFLOW_JWT_SECRET
```

Suba tudo:

```bash
docker compose up -d --build
```

O primeiro build demora alguns minutos (baixa o Chromium). Depois:

- `https://localhost` (ou o seu `DOMAIN`): interface do Airflow, login com `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`
- `http://127.0.0.1:8080`: acesso direto, sem o Caddy

Com `DOMAIN=localhost` o Caddy usa um certificado local, então o navegador vai avisar que não é confiável. Em produção, com um domínio apontando para a VM, ele emite um certificado válido sozinho.

Para conferir o banco de eventos:

```bash
docker compose exec postgres psql -U bjj -d bjj -c '\dt bjj.*'
```

## Banco `bjj`

Criado na primeira vez que o Postgres sobe, por `postgres/initdb/01-create-bjj.sh`, que aplica os arquivos de `sql/` em ordem.

- `bjj.events`: um registro por campeonato por fonte, único em `(source, source_event_id)`. O `fingerprint` (nome + data + cidade normalizados) liga o mesmo evento vindo de fontes diferentes.
- `bjj.crawl_runs`: uma linha por execução de DAG, com contagens e erros.

Os scripts de `initdb` só rodam com o volume vazio. Para recriar o banco do zero em desenvolvimento: `docker compose down -v`.

## Estrutura

```
docker-compose.yml
Dockerfile
requirements.txt
Caddyfile
.env.example
postgres/initdb/     criação do banco bjj
sql/                 schema
dags/                DAGs do Airflow
crawler/             código do crawler (fetch, parsers, normalização, gravação)
config/              sources.yaml: um bloco por site
```

## Memória (VM de 24 GB)

| Container | Limite |
| --- | --- |
| airflow-scheduler (inclui as tasks e o Chromium) | 8 GB |
| airflow-apiserver | 2 GB |
| postgres | 2 GB |
| airflow-dag-processor | 1 GB |
| airflow-triggerer | 512 MB |
| caddy | 256 MB |

Sobram uns 10 GB para o sistema e para aumentar o paralelismo (`AIRFLOW__CORE__PARALLELISM`, hoje 4).
