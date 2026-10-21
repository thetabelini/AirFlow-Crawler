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
| `web` | Tela e API de leitura dos dados (`https://dados.<DOMAIN>`), com usuário só de leitura no banco |
| `kafka` | Apache Kafka (KRaft, um nó): cada coleta também é publicada aqui ([docs/kafka.md](docs/kafka.md)) |
| `kafka-init` | Cria os tópicos de cada projeto; roda a cada `up` e sai |
| `kafka-ui` | Interface do Kafka (`https://kafka.<DOMAIN>`), com login |
| `caddy` | HTTPS automático na frente da interface, da tela de dados e do Kafka UI (portas 80 e 443) |

A imagem do Airflow é estendida no `Dockerfile` com `httpx`, `selectolax`, `psycopg`, `confluent-kafka` e Playwright + Chromium.

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
WEB_DB_PASSWORD=$(openssl rand -hex 16)
WEB_USERS=felipe:$(openssl rand -hex 8)
KAFKA_UI_PASSWORD=$(openssl rand -hex 12)
EOF
```

Suba tudo:

```bash
docker compose up -d --build
```

O primeiro build demora alguns minutos (baixa o Chromium). Depois:

- `https://localhost` (ou o seu `DOMAIN`): interface do Airflow, login com `AIRFLOW_ADMIN_USER` / `AIRFLOW_ADMIN_PASSWORD`
- `http://127.0.0.1:8080`: acesso direto, sem o Caddy
- `https://kafka.localhost`: Kafka UI, login `admin` / `KAFKA_UI_PASSWORD`

As DAGs nascem pausadas: ative na interface e use "Trigger" para rodar na hora.

Com `DOMAIN=localhost` o Caddy usa um certificado local, então o navegador avisa que não é confiável. Em produção, com um domínio apontando para a VM, ele emite um certificado válido sozinho.

Para consultar os dados de um projeto:

```bash
docker compose exec postgres psql -U bjj -d bjj -c 'select count(*) from bjj.events'
```

## Tela e API de dados

O serviço `web` mostra os dados coletados em `https://dados.<DOMAIN>` (no Airflow: menu **Plugins → Dados coletados** e **API de dados**):

- `/bjj/`: tabela de campeonatos com filtros por nome, estado, inscrição e período, mais totais por estado; o nome de cada evento abre a página de detalhe
- `/bjj/eventos/<id>`: todos os campos do evento e o histórico de mudanças
- `/bjj/api/eventos` e `/bjj/api/estatisticas`: os mesmos dados em JSON, com os filtros como parâmetros (`removidos=true` inclui os que sumiram do site)
- `/bjj/api/eventos/<id>`: um evento com todos os campos e o histórico
- `/bjj/api/mudancas?desde=<data-hora>&campo=<campo>`: todas as mudanças em ordem, para sincronizar só o que mudou
- `/docs`: documentação da API

Há duas formas de acesso:

**Chave de API**, para quem vai consumir os dados. Cada pessoa recebe a sua, e você revoga quando quiser. Na VM, na pasta do projeto:

```bash
bash scripts/api-keys.sh criar joao      # mostra a chave uma única vez: envie para a pessoa
bash scripts/api-keys.sh listar          # situação, último uso e requisições hoje e no total
bash scripts/api-keys.sh revogar joao    # corta o acesso na hora
```

A pessoa usa o cabeçalho `X-API-Key` (em `/docs`, botão **Authorize**):

```bash
curl -H "X-API-Key: afc_..." "https://dados.<DOMAIN>/bjj/api/eventos?uf=SP&status=open"
```

O banco guarda só o hash (SHA-256) da chave, no banco `web` da plataforma.

Cada chave tem limite de **60 requisições por minuto** e **5.000 por dia** (ajustáveis no `.env` com `WEB_RATE_LIMIT_PER_MINUTE` e `WEB_RATE_LIMIT_PER_DAY`, seguido de `docker compose up -d web`). As respostas trazem o que resta em `X-RateLimit-Remaining-Minute` e `X-RateLimit-Remaining-Day`; passando do limite, a resposta é **429** com `Retry-After` (segundos até a próxima janela). Usuário e senha (`WEB_USERS`) não têm limite.

**Usuário e senha** (HTTP Basic), para você usar a tela no navegador, definidos no `.env`:

```
WEB_USERS=felipe:senha1
```

Depois de mudar, rode `docker compose up -d web`. Com `WEB_PUBLIC=true`, a tela e a API ficam abertas para qualquer pessoa.

O serviço lê o banco com o usuário `web_reader`, criado pelo `db-init`: só leitura (`SELECT`) nos schemas dos projetos e, no banco `web`, leitura das chaves e atualização dos contadores de uso.

Um projeto ganha tela própria com um `projects/<nome>/web.py` que expõe um `router` do FastAPI; ele aparece em `/<nome>/`.

## Histórico de mudanças (BJJ)

Cada gravação em `bjj.events` passa por um trigger que registra em `bjj.event_changes`:

- `created`: o evento apareceu pela primeira vez
- `updated`: um campo mudou, com o valor antigo (`old_value`) e o novo (`new_value`)

Cada linha traz quando (`changed_at`) e qual execução da DAG fez a mudança (`run_id`). Quando um evento some do site, a coleta preenche `removed_at` (e isso entra no histórico); se ele voltar, `removed_at` é limpo. Por padrão, a tela e a API escondem os removidos.

Exemplo: quando as inscrições de cada evento fecharam.

```sql
SELECT e.name, c.changed_at
FROM bjj.event_changes c JOIN bjj.events e ON e.id = c.event_id
WHERE c.field = 'status' AND c.new_value = 'closed';
```

## Pipeline de cada DAG

1. `fetch_listing`: um request na URL fixa da fonte (httpx, ou Playwright se `js: true`)
2. `parse`: o parser da fonte extrai todos os itens da página; se não achar nenhum, a task falha (o layout do site provavelmente mudou)
3. `normalize`: `projects/<nome>/pipeline.py` limpa e completa cada item
4. Em paralelo:
   - `upsert_notify`: `pipeline.store()` grava no banco do projeto, a execução vai para `<projeto>.crawl_runs` e os itens novos aparecem no log
   - `publish`: publica cada item em `<projeto>.events.raw` e o fim da coleta em `<projeto>.runs`, no Kafka

## Kafka

Cada coleta também vai para o Kafka, para ser lida por consumidores independentes da DAG. Tópicos, formato das mensagens, comandos para observar, exercícios e o que o consumidor precisa fazer estão em [docs/kafka.md](docs/kafka.md).

Por enquanto a DAG continua gravando no banco. Quando existir um consumidor que grave, `CRAWLER_WRITE_DB=false` no `.env` tira essa gravação da DAG.

## Adicionando um projeto

1. Crie `projects/<nome>/` (letras minúsculas, números e `_`) com:
   - `sources.yaml`: um bloco por site (`name`, `url`, `parser`, `schedule`, `js`)
   - `parsers/<parser>.py`: `parse(html) -> list[dict]`
   - `pipeline.py`: `normalize(source, raw) -> dict` e `store(conn, items) -> list[dict]` (devolve os novos)
   - `sql/001_init.sql`: as tabelas, no schema `<nome>`
   - `tests/`: testes com um recorte real da página em `tests/fixtures/`
2. Adicione `<NOME>_DB_PASSWORD` ao `.env`.
3. `docker compose up -d`: o `db-init` cria o banco, o `airflow-init` cria o pool e o `kafka-init` cria os tópicos. As DAGs aparecem sozinhas.

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
docker-compose.yml, Dockerfile, .env.example   plataforma
caddy/Caddyfile        HTTPS e roteamento (recarrega sozinho quando muda)
requirements.txt, requirements-dev.txt, pytest.ini
scripts/db-init.sh     cria os bancos dos projetos e aplica as migrações
scripts/setup-vm.sh    prepara a VM da Oracle (firewall, swap, Docker)
scripts/backup.sh      backup diário dos bancos (local e, opcional, Object Storage)
scripts/api-keys.sh    cria, lista e revoga chaves de API
scripts/kafka-init.sh  cria os tópicos do Kafka de cada projeto
docs/                  deploy na Oracle e Kafka
dags/dag_factory.py    uma DAG por fonte de cada projeto
plugins/links.py       links para a tela, a API e o Kafka UI no menu Plugins do Airflow
web/                   tela e API de leitura (FastAPI), container próprio; web/sql/ é o banco das chaves
core/                  fetch, leitura dos projetos, banco, Kafka (stream.py), funções de texto
core/sql/              migrações aplicadas em todo projeto (crawl_runs)
tests/                 testes do core
projects/
└─ bjj/
   ├─ sources.yaml
   ├─ parsers/soucompetidor.py
   ├─ normalize.py, store.py, pipeline.py
   ├─ web.py, templates/   tela e API do projeto
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
| kafka | 1 GB |
| kafka-ui | 768 MB |
| airflow-triggerer | 512 MB |
| web | 256 MB |
| caddy | 256 MB |

Sobram uns 8 GB para o sistema e para aumentar o paralelismo (`AIRFLOW__CORE__PARALLELISM`, hoje 4).

Para uma VM de 1 OCPU e 4 GB existe o perfil `docker-compose.small.yml` (ative com `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml` no `.env`): 1 processo na API, paralelismo 2, sem triggerer, sem Kafka (sobe com `--profile kafka`) e limites menores. Medido com a DAG do BJJ rodando, a stack usa cerca de 1,3 GB.
