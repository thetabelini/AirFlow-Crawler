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

## Fontes e DAGs

Cada bloco de `config/sources.yaml` vira uma DAG `crawl_<name>` (gerada por `dags/dag_factory.py`) com 4 tasks:

1. `fetch_listing`: um request na URL fixa da fonte (httpx, ou Playwright se `js: true`)
2. `parse`: o parser da fonte (`crawler/parsers/<parser>.py`) extrai todos os eventos da página; se não achar nenhum, a task falha (o layout do site provavelmente mudou)
3. `normalize`: limpa os textos, converte país para código ISO, detecta gi/no-gi pelo nome e calcula o `fingerprint`
4. `upsert_notify`: grava em `bjj.events`, registra a execução em `bjj.crawl_runs` e lista no log os eventos novos

Fontes configuradas:

| Fonte | URL | Parser |
| --- | --- | --- |
| Sou Competidor | https://soucompetidor.com.br/pt-br/ | `soucompetidor` |

Para adicionar um site: um bloco no `sources.yaml` e um módulo em `crawler/parsers/` com uma função `parse(html) -> list[dict]`, mais um teste com um recorte real da página em `tests/fixtures/`.

## Testes

O código de `crawler/` não depende do Airflow, então os testes rodam sem subir nada:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Os testes de banco (`tests/test_db.py`) só rodam com um Postgres com o schema aplicado:

```bash
BJJ_TEST_DATABASE_URL=postgresql://bjj:<senha>@localhost:5432/bjj .venv/bin/pytest
```

## Estrutura

```
docker-compose.yml
Dockerfile
requirements.txt
requirements-dev.txt
Caddyfile
.env.example
postgres/initdb/     criação do banco bjj
sql/                 schema
dags/                dag_factory.py: uma DAG por fonte
crawler/             fetch, parsers, normalização e gravação (não depende do Airflow)
config/              sources.yaml: um bloco por site
tests/               testes e recortes reais das páginas
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
