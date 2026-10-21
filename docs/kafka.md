# Kafka

Cada coleta, além de gravar no banco, publica os itens no Kafka. A ideia é separar quem **coleta** (a DAG) de quem **usa** os dados (consumidores), e ter um registro de tudo o que saiu de cada coleta que pode ser lido de novo do zero.

```
DAG <projeto>__<fonte>
  fetch_listing → parse → normalize ─┬─ upsert_notify → banco (como antes)
                                      └─ publish       → Kafka → consumidor (a escrever)
```

Enquanto não houver consumidor, a gravação no banco continua na DAG. Quando ele existir, `CRAWLER_WRITE_DB=false` no `.env` tira a `upsert_notify` da DAG e o consumidor passa a ser o único a gravar.

## Conceitos em 1 minuto

| Termo | O que é aqui |
| --- | --- |
| Tópico | Um log só de acréscimo, com nome. Ex.: `bjj.events.raw`. Ler não apaga nada: a mensagem fica lá até vencer a retenção (90 dias). |
| Partição | O tópico é dividido em partes que podem ser lidas em paralelo. A ordem só é garantida **dentro** de uma partição. |
| Chave | Decide a partição: mesma chave, mesma partição. Usamos `<fonte>:<id do evento>`, então as versões de um evento chegam em ordem. |
| Offset | A posição de cada mensagem na partição (0, 1, 2...). |
| Grupo de consumidores | Consumidores com o mesmo `group.id` dividem as partições entre si, e o Kafka guarda até que offset o grupo já leu (o *commit*). Grupos diferentes leem tudo, cada um no seu ritmo. |
| Produtor idempotente | Com `acks=all` e `enable.idempotence`, uma mensagem só conta como entregue depois de gravada, e uma nova tentativa do próprio produtor não a duplica. |

## O que sobe

| Serviço | Função |
| --- | --- |
| `kafka` | Broker Apache Kafka 4 em modo KRaft (sem ZooKeeper), um nó só. Dados no volume `kafka-data` |
| `kafka-init` | Cria os tópicos de cada projeto (`scripts/kafka-init.sh`); roda a cada `up` e sai |
| `kafka-ui` | Interface em `https://kafka.<DOMAIN>` (login com `KAFKA_UI_USER` / `KAFKA_UI_PASSWORD`); no Airflow, menu **Plugins → Kafka UI** |

Endereços do broker:

- `kafka:9092`: para os containers (é o que o Airflow usa)
- `localhost:9094`: para programas rodando na própria VM; do seu computador, abra um túnel com `ssh -L 9094:localhost:9094 ubuntu@<ip-da-vm>` e use `localhost:9094`

A porta 9094 só escuta em `127.0.0.1` da VM, sem senha: não abra no firewall.

## Tópicos

Criados por projeto (para o `bjj`):

| Tópico | Partições | Chave | Conteúdo |
| --- | --- | --- | --- |
| `bjj.events.raw` | 3 | `<fonte>:<source_event_id>` | Um item normalizado por mensagem |
| `bjj.runs` | 1 | `<fonte>` | Uma mensagem por coleta, publicada depois dos itens, com todas as chaves vistas |
| `bjj.events.dlq` | 1 | a do item | Para o consumidor guardar o que rejeitou (*dead letter queue*); a DAG não escreve aqui |

A criação automática de tópicos está desligada: produzir num nome errado dá erro em vez de criar um tópico novo.

## Formato das mensagens

Todas em JSON (UTF-8), com `schema_version`. Se o formato mudar de um jeito incompatível, a versão sobe e o consumidor decide o que fazer com cada uma.

Item (`bjj.events.raw`):

```json
{
  "schema_version": 1,
  "type": "item",
  "project": "bjj",
  "source": "soucompetidor",
  "run_id": "scheduled__2026-10-21T00:00:00+00:00",
  "produced_at": "2026-10-21T00:00:07.356931+00:00",
  "item": {
    "source": "soucompetidor",
    "source_event_id": "P2775",
    "fingerprint": "f4bc4ab8339276df",
    "name": "COPA PRIME #10 ETAPA",
    "edition": "2026 - ANO",
    "start_date": "2026-10-18",
    "end_date": "2026-10-18",
    "city": "FARROUPILHA",
    "state": "RS",
    "country": "BR",
    "status": "closed",
    "modality": [],
    "event_url": "https://soucompetidor.com.br/pt-br/eventos/...",
    "venue": null, "organizer": null, "registration_url": null, "registration_deadline": null
  }
}
```

`item` é exatamente o que `pipeline.normalize()` devolve, o mesmo que a DAG grava com `pipeline.store()`.

Fim de coleta (`bjj.runs`):

```json
{
  "schema_version": 1,
  "type": "run_finished",
  "project": "bjj",
  "source": "soucompetidor",
  "run_id": "scheduled__2026-10-21T00:00:00+00:00",
  "started_at": "2026-10-21T00:00:00.120000+00:00",
  "finished_at": "2026-10-21T00:00:07.358942+00:00",
  "items": 67,
  "keys": ["soucompetidor:P2775", "soucompetidor:P2832", "..."]
}
```

A lista `keys` é o que permite ao consumidor saber quais eventos **sumiram** do site (os que estão no banco com essa fonte e não estão na lista), sem depender da ordem entre os dois tópicos.

## Garantias (e o que elas exigem do consumidor)

- **Pelo menos uma vez.** Se a task `publish` falhar no meio (Kafka fora do ar, por exemplo), o Airflow tenta de novo e publica a coleta inteira outra vez. O mesmo item pode aparecer duas vezes: gravar precisa ser idempotente (o `UPSERT` por `(source, source_event_id)` de `projects/bjj/store.py` já é).
- **Ordem por evento**, não global: itens de eventos diferentes podem chegar em qualquer ordem, e `bjj.runs` pode ser lido antes ou depois dos itens da mesma coleta.
- A task `publish` só termina com sucesso quando o Kafka confirmou todas as mensagens; senão falha e entra nas tentativas da DAG.

## Para olhar o que está acontecendo

Na interface (`https://kafka.<DOMAIN>`): **Topics → bjj.events.raw → Messages** mostra as mensagens com chave, partição e offset; **Consumers** mostra cada grupo e quanto falta ele ler (*lag*).

Pela linha de comando, na VM, na pasta do projeto:

```bash
K="docker compose exec kafka /opt/kafka/bin"

# tópicos e partições
$K/kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic bjj.events.raw

# quantas mensagens há em cada partição (o último offset)
$K/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic bjj.events.raw

# ler desde o começo, mostrando chave e partição (Ctrl+C para sair)
$K/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic bjj.events.raw \
  --from-beginning --formatter-property print.key=true --formatter-property print.partition=true

# só as coletas
$K/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic bjj.runs --from-beginning

# grupos de consumidores e o lag de cada um
$K/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --all-groups
```

## Exercícios

1. Rode a DAG duas vezes e conte as mensagens em `bjj.events.raw`: cada coleta publica tudo de novo (o tópico é um log, não uma tabela).
2. Leia o tópico com `kafka-console-consumer.sh --group exercicio`. Rode de novo: ele não mostra nada, porque o grupo já fez commit. Veja o offset em `kafka-consumer-groups.sh --describe --group exercicio`.
3. Volte o grupo para o início e leia tudo outra vez:
   `$K/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group exercicio --topic bjj.events.raw --reset-offsets --to-earliest --execute`
4. Procure a mesma chave (ex.: `soucompetidor:P2775`) em coletas diferentes: ela está sempre na mesma partição.
5. Pare o Kafka (`docker compose stop kafka`), rode a DAG e veja a `publish` falhar e entrar em nova tentativa, enquanto a `upsert_notify` grava normalmente. Suba de novo (`docker compose start kafka`).

## O consumidor (próximo passo)

Ainda não existe: fica para você escrever. O que ele precisa fazer, para substituir a gravação da DAG:

1. Ler `bjj.events.raw` e `bjj.runs` num grupo próprio (ex.: `bjj-store`), com `enable.auto.commit=false`.
2. Para cada item: validar (`schema_version` conhecida, campos obrigatórios) e gravar com o mesmo `upsert` de `projects/bjj/store.py`, chamando antes `core.db.set_run_id(conn, run_id)` para o histórico registrar a coleta. Item inválido vai para `bjj.events.dlq`, com o motivo, em vez de travar o consumidor.
3. Para cada `run_finished`: marcar como removidos os eventos da fonte que não estão em `keys` e registrar a execução em `bjj.crawl_runs`.
4. Fazer o commit do offset **depois** do `COMMIT` no banco. Se cair entre os dois, a mensagem é lida de novo e o upsert absorve a repetição.
5. Rodar como mais um serviço no `docker-compose.yml`, conectando em `kafka:9092`.

Com ele rodando e conferido, `CRAWLER_WRITE_DB=false` no `.env` e `docker compose up -d`.

Uma biblioteca boa para Python é a mesma que a DAG usa, `confluent-kafka`. Um começo:

```python
from confluent_kafka import Consumer

consumer = Consumer({
    "bootstrap.servers": "localhost:9094",
    "group.id": "bjj-store",
    "auto.offset.reset": "earliest",
    "enable.auto.commit": False,
})
consumer.subscribe(["bjj.events.raw", "bjj.runs"])
while True:
    msg = consumer.poll(1.0)
    if msg is None or msg.error():
        continue
    print(msg.topic(), msg.partition(), msg.offset(), msg.key())
    consumer.commit(message=msg)
```

## Memória

| Container | Limite |
| --- | --- |
| kafka | 1 GB (heap de 512 MB) |
| kafka-ui | 768 MB |

No perfil `docker-compose.small.yml` os três serviços do Kafka só sobem com `--profile kafka`, e a DAG não cria a task `publish`.
