"""Link no menu do Airflow para a tela de dados (serviço web)."""

import os

from airflow.plugins_manager import AirflowPlugin

DOMAIN = os.environ.get("DOMAIN", "localhost")


class LinksPlugin(AirflowPlugin):
    name = "links"
    external_views = [
        {
            "name": "Dados",
            "href": f"https://dados.{DOMAIN}/",
            "destination": "nav",
        }
    ]
