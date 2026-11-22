FROM python:3.12-slim

LABEL org.opencontainers.image.title="cryptopay-bot" \
      org.opencontainers.image.description="Self-hosted crypto checkout driven from Telegram" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/vaproh/cryptopay-bot"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY web ./web

RUN useradd -u 10001 -m app && mkdir -p /data && chown app /data
USER app

EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=2).status==200 else 1)"

CMD ["python", "-m", "app.main"]
