-- Usado pelo consumidor do Kafka (projects/bjj/consumer.py) para reconhecer mensagens repetidas:
-- o produced_at da última mensagem aplicada a cada evento. Uma mensagem com produced_at igual ou
-- anterior a esse já foi aplicada (o Kafka entregou de novo) ou é mais velha do que o que está
-- gravado (o consumidor está relendo o tópico), e é ignorada.
-- Fica vazio nos eventos gravados direto pela DAG.
ALTER TABLE bjj.events ADD COLUMN last_produced_at timestamptz;
