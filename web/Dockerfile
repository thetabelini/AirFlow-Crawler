FROM python:3.12-slim

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt \
    && useradd --create-home --uid 1000 web

# O código (web/, core/ e projects/) é montado em /app pelo docker-compose.
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
USER web
EXPOSE 8000
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
