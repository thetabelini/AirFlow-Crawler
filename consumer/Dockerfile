FROM python:3.12-slim

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt \
    && useradd --create-home --uid 1000 consumer

# O código (consumer/, core/ e projects/) é montado em /app pelo docker-compose.
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
USER consumer
CMD ["python", "-m", "consumer.run"]
