FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
RUN case ${TARGETARCH} in \
      arm64) ARCH=arm64 ;; \
      amd64) ARCH=amd64 ;; \
      *) ARCH=amd64 ;; \
    esac && \
    echo "Building for architecture: ${ARCH}" && \
    mkdir -p /opt/fbc/bin && \
    wget -q https://github.com/rupor-github/fb2cng/releases/download/v1.3.8/fbc-linux-${ARCH}.zip && \
    unzip fbc-linux-${ARCH}.zip -d /opt/fbc/bin/ && \
    rm fbc-linux-${ARCH}.zip && \
    chmod +x /opt/fbc/bin/fbc

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/fbc /opt/fbc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]
EXPOSE 5000

# При старте копируем fbc в том (если его там нет)
CMD mkdir -p /app/data/fbc && \
    ( [ -f /app/data/fbc/fbc ] || cp /opt/fbc/bin/fbc /app/data/fbc/fbc ) && \
    gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 app:app