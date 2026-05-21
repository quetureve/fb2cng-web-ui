FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Автоматически выбираем архитектуру
ARG TARGETARCH
RUN case ${TARGETARCH} in \
      arm64) ARCH=arm64 ;; \
      amd64) ARCH=amd64 ;; \
      *) ARCH=amd64 ;; \
    esac && \
    echo "Building for architecture: ${ARCH}" && \
    wget -q https://github.com/rupor-github/fb2cng/releases/download/v1.3.8/fbc-linux-${ARCH}.zip && \
    unzip fbc-linux-${ARCH}.zip -d /usr/local/bin/ && \
    rm fbc-linux-${ARCH}.zip && \
    chmod +x /usr/local/bin/fbc

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/bin/fbc /usr/local/bin/fbc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Запуск от root (для простоты монтирования volumes)
# Если хотите непривилегированного пользователя, раскомментируйте строки ниже
# RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
# USER appuser

VOLUME ["/app/data"]
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "app:app"]