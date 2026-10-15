ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12

FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

USER root
RUN mkdir -p ${PLAYWRIGHT_BROWSERS_PATH} && chown airflow:0 ${PLAYWRIGHT_BROWSERS_PATH}

USER airflow
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements.txt

# Bibliotecas de sistema do Chromium (precisa de root) e depois o próprio navegador.
USER root
RUN PYTHONUSERBASE=/home/airflow/.local playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

USER airflow
RUN playwright install chromium
