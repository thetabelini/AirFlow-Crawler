# Kafka

Cada coleta publica os itens no Kafka, e um consumidor os grava no banco. A ideia é separar quem **coleta** (a DAG) de quem **usa** os dados (consumidores), e ter um registro de tudo o que saiu de cada coleta que pode ser lido de novo do zero.

```
DAG <projeto>__<fonte>
  fetch_listing → parse → normalize ─┬─ upsert_notify → banco (enquanto CRAWLER_WRITE_DB=true)
                                      └─ publish       → Kafka → consumer → banco
```

Os dois caminhos gravam a mesma coisa e podem rodar juntos: o consumidor reconhece o que já está no banco (veja [Repetidas](#repetidas)). Depois de conferir que o consumidor está gravando, `CRAWLER_WRITE_DB=false` no `.env` tira a `upsert_notify` da DAG e ele passa a ser o único a gravar.

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
| `consumer` | Lê os tópicos e grava no banco de cada projeto (`consumer/run.py`), no grupo `store` |
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
| `bjj.events.dlq` | 1 | a da mensagem rejeitada | O que o consumidor não conseguiu gravar (*dead letter queue*), com o motivo |

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

- **Pelo menos uma vez.** Se a task `publish` falhar no meio (Kafka fora do ar, por exemplo), o Airflow tenta de novo e publica a coleta inteira outra vez. E se o consumidor cair entre gravar no banco e fazer o commit do offset, ele relê a mensagem. O mesmo item pode chegar mais de uma vez: o consumidor precisa reconhecer o que já gravou.
- **Ordem por evento**, não global: itens de eventos diferentes podem chegar em qualquer ordem, e `bjj.runs` pode ser lido antes ou depois dos itens da mesma coleta.
- A task `publish` só termina com sucesso quando o Kafka confirmou todas as mensagens; senão falha e entra nas tentativas da DAG.

## Para olhar o que está acontecendo

Na interface (`https://kafka.<DOMAIN>`):

- **Topics → bjj.events.raw → Messages**: as mensagens com chave, partição e offset
- **Topics → bjj.events.raw → Statistics**: clique em **Start Analysis** para ler o tópico inteiro e ver tamanhos e distribuição por partição (antes disso a aba avisa que não há análise, um 404)
- **Consumers**: cada grupo e quanto falta ele ler (*lag*)
- **Brokers → 1 → Metrics**: as métricas do broker, que o Kafka UI lê por JMX na porta 9101 (só na rede interna dos containers)

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

## O consumidor

`consumer/run.py` é o laço comum a todos os projetos; o que fazer com cada mensagem fica em `projects/<nome>/consumer.py` (`handle_item` e `handle_run`). Projeto sem esse arquivo não é consumido.

Para cada mensagem, na ordem:

1. Confere o envelope (`schema_version`, `type`, `project`) e os campos do item (obrigatórios, datas, status).
2. Grava numa transação do banco.
3. Só depois do `COMMIT` no banco, faz o commit do offset no Kafka. Se o processo cair entre os dois, a mensagem volta e é reconhecida como repetida.

Quando algo dá errado:

| Problema | O que acontece |
| --- | --- |
| Mensagem que nunca vai poder ser gravada (não é JSON, versão desconhecida, campo obrigatório vazio, status inválido, o banco recusou os dados) | Vai para `bjj.events.dlq` com o motivo, a posição original (tópico, partição, offset) e o texto da mensagem. O consumidor segue para a próxima |
| Banco ou Kafka fora do ar | O processo cai **sem** o commit do offset; o Docker o reinicia (a cada poucos segundos) até o banco voltar, e a mensagem é lida de novo. Nada se perde |

### Repetidas

Antes de gravar um item, o consumidor compara com o que está no banco:

| Resultado no log | Quando | O que grava |
| --- | --- | --- |
| `novo` | O evento não existe | O evento, e uma linha `created` no histórico |
| `alterado (status, start_date)` | Algum campo mudou (lista quais) | O evento; o histórico registra cada campo |
| `voltou ao site` | Estava marcado como removido | O evento, com `removed_at` limpo |
| `igual` | Mensagem nova, mas nenhum campo mudou (o caso comum: a coleta diária republica tudo) | Só `last_seen_at`; nada no histórico |
| `repetida` | O `produced_at` da mensagem é igual ou anterior ao da última mensagem aplicada ao evento (coluna `last_produced_at`) | Nada |

O `repetida` cobre dois casos: o Kafka entregou a mesma mensagem de novo, e o consumidor está relendo o tópico do zero. No segundo, sem essa verificação, versões antigas de um evento sobrescreveriam a atual.

Para `bjj.runs`, a coleta é `repetida` se o `run_id` já está em `bjj.crawl_runs`, e `antiga` se já há uma coleta mais nova da mesma fonte; nos dois casos nada muda. Senão, marca como removidos os eventos da fonte que não estão em `keys` e registra a coleta em `bjj.crawl_runs`. Uma coleta com `keys` vazia vai para a DLQ, em vez de marcar tudo como removido.

O `new_items` registrado conta os eventos criados por aquela coleta que o consumidor já tinha gravado ao ler o fim dela. Como os itens e o fim da coleta estão em tópicos diferentes, um item que chegue depois não entra na conta (na prática eles chegam antes).

### Acompanhando

```bash
docker compose logs -f consumer                    # uma linha por mensagem: tópico[partição]@offset chave: resultado
docker compose logs consumer | grep -c ": igual"   # quantas vieram sem mudança
$K/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic bjj.events.dlq --from-beginning
```

No Kafka UI, **Consumers → store** mostra o lag: quanto falta o consumidor ler. Parado em 0 é o normal.

### Mais exercícios

6. Rode a DAG duas vezes e veja no log do consumidor: 67 `novo` (ou `igual`, se a DAG também gravou) e depois 67 `igual`.
7. Releia tudo do zero e veja cada mensagem cair em `repetida`, sem mudar nada no banco:
   ```bash
   docker compose stop consumer
   $K/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --group store --all-topics --reset-offsets --to-earliest --execute
   docker compose start consumer && docker compose logs -f consumer
   ```
   O grupo precisa estar parado para o reset: por isso o `stop`.
8. Mande uma mensagem quebrada e encontre-a na DLQ:
   ```bash
   echo 'soucompetidor:X1|isso nao e json' | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
     --bootstrap-server localhost:9092 --topic bjj.events.raw --reader-property parse.key=true --reader-property 'key.separator=|'
   ```
9. Pare o banco (`docker compose stop postgres`), rode a DAG e veja o consumidor reiniciando em `docker compose ps`. Suba o banco: ele grava o que ficou pendente.

Para escrever outro consumidor (um que mande alerta de evento novo, por exemplo), use outro `group.id`: ele lê tudo de forma independente do `store`, no seu ritmo. Do seu computador, com o túnel SSH, `localhost:9094`:

```python
from confluent_kafka import Consumer

consumer = Consumer({
    "bootstrap.servers": "localhost:9094",
    "group.id": "meu-teste",
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
| consumer | 256 MB |

No perfil `docker-compose.small.yml` os quatro serviços do Kafka só sobem com `--profile kafka`, e a DAG não cria a task `publish`.
