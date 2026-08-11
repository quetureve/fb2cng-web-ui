FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    unzip \
    && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
# Версия fb2cng, "прошиваемая" в образ по умолчанию. Дальше её можно обновлять
# прямо из интерфейса (кнопка "Обновить" в настройках) без пересборки образа —
# см. update_fbc в tasks.py. Этот ARG нужен только для первого запуска / отката.
ARG FBC_VERSION=v1.5.5
RUN case ${TARGETARCH} in \
      arm64) ARCH=arm64 ;; \
      amd64) ARCH=amd64 ;; \
      *) ARCH=amd64 ;; \
    esac && \
    echo "Building for architecture: ${ARCH}, fb2cng ${FBC_VERSION}" && \
    mkdir -p /opt/fbc/bin && \
    wget -q https://github.com/rupor-github/fb2cng/releases/download/${FBC_VERSION}/fbc-linux-${ARCH}.zip && \
    unzip fbc-linux-${ARCH}.zip -d /opt/fbc/bin/ && \
    rm fbc-linux-${ARCH}.zip && \
    chmod +x /opt/fbc/bin/fbc && \
    echo "${FBC_VERSION}" > /opt/fbc/bin/VERSION

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

# При старте копируем fbc и его версию в том вместе, одной операцией, и только
# если бинарника там ещё нет. Это важно при апгрейде существующего
# развёртывания: если fbc уже лежит в volume (например, старая v1.3.8), мы не
# должны писать VERSION=v1.5.5, иначе интерфейс покажет версию, которая не
# соответствует реально установленному бинарнику - в этом случае VERSION
# просто останется "неизвестна" до первого нажатия "Обновить".
CMD mkdir -p /app/data/fbc && \
    ( [ -f /app/data/fbc/fbc ] || ( cp /opt/fbc/bin/fbc /app/data/fbc/fbc && cp /opt/fbc/bin/VERSION /app/data/fbc/VERSION ) ) && \
    gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 app:app