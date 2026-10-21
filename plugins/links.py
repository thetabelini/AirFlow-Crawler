"""Links no menu do Airflow para a tela e a API de dados (serviço web) e para o Kafka UI."""

import os

from airflow.plugins_manager import AirflowPlugin

DOMAIN = os.environ.get("DOMAIN", "localhost")


class LinksPlugin(AirflowPlugin):
    name = "links"
    # São dois links de propósito: com um item só, o Airflow 3.3 o desenha como um
    # botão solto no menu lateral que não abre nada. Com dois, eles aparecem dentro
    # do menu "Plugins" como links normais, que abrem em nova aba.
    external_views = [
        {"name": "Dados coletados", "href": f"https://dados.{DOMAIN}/", "destination": "nav"},
        {"name": "API de dados", "href": f"https://dados.{DOMAIN}/docs", "destination": "nav"},
        {"name": "Kafka UI", "href": f"https://kafka.{DOMAIN}/", "destination": "nav"},
    ]
