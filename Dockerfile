FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Актуальная версия для arm64 — zip архив
ARG FBC_VERSION=v1.3.8
RUN wget -q https://github.com/rupor-github/fb2cng/releases/download/${FBC_VERSION}/fbc-linux-arm64.zip \
    && unzip fbc-linux-arm64.zip -d /usr/local/bin/ \
    && rm fbc-linux-arm64.zip \
    && chmod +x /usr/local/bin/fbc

FROM python:3.11-slim-bookworm

# Установка runtime-зависимостей (минимально)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/fbc /usr/local/bin/fbc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]