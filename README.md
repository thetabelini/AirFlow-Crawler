# AirFlow-Crawler

Plataforma para rodar crawlers com Airflow, numa única VM Always Free da Oracle Cloud (Ampere A1, 4 OCPU, 24 GB) com Docker Compose.

Cada assunto é um **projeto** em `projects/<nome>/`, com banco, pool e DAGs próprios. Hoje existe um:

| Projeto | O que coleta | Fontes |
| --- | --- | --- |
| `bjj` | Campeonatos de jiu-jitsu | Sou Competidor |

## Como os projetos ficam separados

| Onde | Como |
| --- | --- |
| Código | `projects/<nome>/` tem os parsers, a normalização, a gravação e o schema do projeto. O que é comum fica em `core/`. |
| Airflow | Uma DAG `<projeto>__<fonte>` por site, com a tag do projeto (filtre por ela na interface). |
| Concorrência | Um pool por projeto (2 vagas), criado pelo `airflow-init`: um projeto travado não ocupa as vagas dos outros. |
| Banco | Um banco e um usuário por projeto no mesmo Postgres. Um projeto não lê nem altera os dados de outro. |

## O que sobe

| Serviço | Função |
| --- | --- |
| `postgres` | PostgreSQL 16: banco `airflow` (metadados) e um banco por projeto |
| `db-init` | Cria o banco de cada projeto e aplica as migrações pendentes; roda a cada `up` e sai |
| `airflow-init` | Migra o banco do Airflow, cria o admin e um pool por projeto; roda e sai |
| `airflow-apiserver` | Interface web e API do Airflow (porta 8080, só em localhost) |
| `airflow-scheduler` | Agenda as DAGs e executa as tasks (LocalExecutor) |
| `airflow-dag-processor` | Lê `dags/` |
| `airflow-triggerer` | Tasks deferrable |
| `caddy` | HTTPS automático na frente da interface (portas 80 e 443) |

A imagem do Airflow é estendida no `Dockerfile` com `httpx`, `selectolax`, `psycopg` e Playwright + Chromium.

## Deploy na Oracle Cloud

Passo a passo em [docs/deploy-oracle.md](docs/deploy-oracle.md): criar a VM, abrir as portas, `scripts/setup-vm.sh`, subir e configurar o backup diário (`scripts/backup.sh`).

## Rodando localmente

Precisa de Docker com o plugin compose. Crie o `.env` (as senhas e chaves são geradas na hora):

```bash
cat > .env <<EOF
DOMAIN=localhost
AIRFLOW_ADMIN_USER=admin
AIRFLOW_ADMIN_PASSWORD=$(openssl rand -hex 12)
AIRFLOW_DB_PASSWORD=$(openssl rand -hex 16)
BJJ_DB_PASSWORD=$(openssl rand -hex 16)
AIRFLOW_FERNET_KEY=$(openssl rand -base64 32 | tr '+/' '-_')
AIRFLOW_JWT_SECRET=$(openssl rand -hex 32)
EOF
```

Suba tudo:

```bash
docker compose up -d --build
```

O primeiro build demora alguns minutos (baixa o Chromium). Depois:

- `https://localhost` (ou o seu `DOMAIN`): interface do Airflow, login com `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`
- `http://127.0.0.1:8080`: acesso direto, sem o Caddy

As DAGs nascem pausadas: ative na interface e use "Trigger" para rodar na hora.

Com `DOMAIN=localhost` o Caddy usa um certificado local, então o navegador avisa que não é confiável. Em produção, com um domínio apontando para a VM, ele emite um certificado válido sozinho.

Para consultar os dados de um projeto:

```bash
docker compose exec postgres psql -U bjj -d bjj -c 'select count(*) from bjj.events'
```

## Pipeline de cada DAG

1. `fetch_listing`: um request na URL fixa da fonte (httpx, ou Playwright se `js: true`)
2. `parse`: o parser da fonte extrai todos os itens da página; se não achar nenhum, a task falha (o layout do site provavelmente mudou)
3. `normalize`: `projects/<nome>/pipeline.py` limpa e completa cada item
4. `upsert_notify`: `pipeline.store()` grava no banco do projeto, a execução vai para `<projeto>.crawl_runs` e os itens novos aparecem no log

## Adicionando um projeto

1. Crie `projects/<nome>/` (letras minúsculas, números e `_`) com:
   - `sources.yaml`: um bloco por site (`name`, `url`, `parser`, `schedule`, `js`)
   - `parsers/<parser>.py`: `parse(html) -> list[dict]`
   - `pipeline.py`: `normalize(source, raw) -> dict` e `store(conn, items) -> list[dict]` (devolve os novos)
   - `sql/001_init.sql`: as tabelas, no schema `<nome>`
   - `tests/`: testes com um recorte real da página em `tests/fixtures/`
2. Adicione `<NOME>_DB_PASSWORD` ao `.env`.
3. `docker compose up -d`: o `db-init` cria o banco e o `airflow-init` cria o pool. As DAGs aparecem sozinhas.

`projects/bjj/` serve de modelo.

## Adicionando uma fonte a um projeto existente

Um bloco no `sources.yaml` do projeto e um módulo em `parsers/`, mais um teste.

## Migrações

O `db-init` aplica, em ordem, `core/sql/*.sql` (tabelas comuns, como `crawl_runs`) e `projects/<nome>/sql/*.sql` em cada banco, e anota o que já rodou em `public.schema_migrations`. Para mudar um schema, crie um arquivo novo (`002_...sql`); não edite um que já foi aplicado.

## Testes

O código de `core/` e `projects/` não depende do Airflow, então os testes rodam sem subir nada:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Os testes de banco só rodam com o banco do projeto disponível:

```bash
BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj .venv/bin/pytest
```

## Estrutura

```
docker-compose.yml, Dockerfile, Caddyfile, .env.example   plataforma
requirements.txt, requirements-dev.txt, pytest.ini
scripts/db-init.sh     cria os bancos dos projetos e aplica as migrações
scripts/setup-vm.sh    prepara a VM da Oracle (firewall, swap, Docker)
scripts/backup.sh      backup diário dos bancos (local e, opcional, Object Storage)
docs/                  deploy na Oracle
dags/dag_factory.py    uma DAG por fonte de cada projeto
core/                  fetch, leitura dos projetos, banco, funções de texto
core/sql/              migrações aplicadas em todo projeto (crawl_runs)
tests/                 testes do core
projects/
└─ bjj/
   ├─ sources.yaml
   ├─ parsers/soucompetidor.py
   ├─ normalize.py, store.py, pipeline.py
   ├─ sql/001_init.sql
   └─ tests/
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

Para uma VM de 1 OCPU e 4 GB existe o perfil `docker-compose.small.yml` (ative com `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml` no `.env`): 1 processo na API, paralelismo 2, sem triggerer e limites menores. Medido com a DAG do BJJ rodando, a stack usa cerca de 1,3 GB.
