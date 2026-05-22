# 📚 FB2 Converter Web UI

> Веб-интерфейс для конвертации книг FB2 в EPUB2, EPUB3, KEPUB, KFX и AZW8 на базе [fb2cng](https://github.com/rupor-github/fb2cng).  
> Поддерживает ZIP-архивы, автообработку папки, отправку на email, загрузку собственных конфигов и CSS.

<img width="884" height="601" alt="image" src="https://github.com/user-attachments/assets/271f2020-7111-49e3-91d2-37edfdad3cfe" />


---

## ✨ Возможности

- Конвертация FB2 → EPUB2, EPUB3, KEPUB, KFX, AZW8
- **Автоматическая обработка папки** — положите FB2 в `data/auto_in`, и файл сконвертируется автоматически
- Пакетная обработка ZIP-архивов с несколькими FB2
- Асинхронная обработка через Redis + Celery
- Отправка результатов на email (SMTP с TLS)
- Загрузка YAML-конфигов, CSS
- Умное исправление путей в пользовательских конфигах
- Drag & Drop интерфейс
- Прогресс-бар с этапами обработки
- Сохранение настроек в браузере
- **Встроенные логи** с кнопками «Копировать», «Очистить» и автообновлением
- Docker-образ для **ARM64 и AMD64**
    - Raspberry Pi
    - Apple Silicon
    - Linux-серверов и обычных ПК

---

# 🚀 Быстрый старт

Проект можно запустить двумя способами:

- Локальная сборка из исходников
- Использование готового Docker-образа из Docker Hub

---

# 🛠 Вариант 1 — локальная сборка

## 1. Клонируйте репозиторий

```bash
git clone https://github.com/quetureve/fb2cng-web-ui.git
cd fb2cng-web-ui
```

## 2. Запустите через Docker Compose

```bash
docker compose up -d --build
```

## 3. Откройте браузер

```text
http://localhost:5000
```

---

# 🐳 Вариант 2 — запуск через готовый Docker-образ

Docker Hub:

https://hub.docker.com/r/quetureve/fb2cng-web-ui

## 1. Создайте файл `docker-compose.yaml`

```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly no
    volumes:
      - redis_data:/data

  web:
    image: quetureve/fb2cng-web-ui:latest
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    command: gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 app:app

  worker:
    image: quetureve/fb2cng-web-ui:latest
    restart: unless-stopped
    volumes:
      - ./data:/app/data
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    command: celery -A tasks worker --loglevel=info --concurrency=2

volumes:
  redis_data:
```

## 2. Запустите контейнеры

```bash
docker compose up -d
```

## 3. Откройте браузер

```text
http://localhost:5000
```

---

# 🛠 Использование

Интерфейс состоит из двух вкладок:

- **Конвертация** — ручная загрузка и конвертация файлов
- **Настройки** — SMTP, конфиги, автообработка и логи

---

# 🔄 Автоматическая обработка папки

1. Перейдите в:
    - **Настройки → Автообработка папки**

2. Выберите:
    - выходной формат
    - интервал сканирования
    - включите автообработку

3. Папки создаются автоматически:

```text
./data/auto_in
./data/auto_processed
./data/auto_results
```

4. Просто скопируйте FB2 или ZIP-файлы в:

```text
./data/auto_in
```

После обработки:

- исходники перемещаются в `auto_processed`
- готовые книги появляются в `auto_results`

---

# 📧 Настройка SMTP

В разделе **SMTP настройки** заполните:

- SMTP сервер (`smtp.gmail.com`)
- Порт (`587` для TLS или `465` для SSL)
- Имя пользователя (email/логин)
- Пароль (или пароль приложения Gmail)
- Email отправителя
- Email получателя
- Включите опцию:
    - **«Использовать TLS»**

---

# ⚙️ Конфиги, CSS и ресурсы

В разделе **Конфиги и ресурсы**:

1. Нажмите:
    - **«Загрузить файлы»**

2. Выберите один или несколько файлов:
    - YAML
    - CSS
    - JPG / PNG
    - шрифты и другие ресурсы

3. Все файлы сохраняются в:

```text
./data/configs
```

4. Первый загруженный YAML автоматически становится активным.

Доступные действия:

- Сделать конфиг активным
- Удалить ненужные файлы
- Использовать собственные CSS и изображения

📖 Документация по fb2cng:

[fb2cng guide](https://github.com/rupor-github/fb2cng)

---

# 📜 Логи

Раздел **Логи** отображает события:

- ручной конвертации
- автоматической обработки
- ошибок и системных сообщений

Доступные действия:

- **Копировать** — копирование логов в буфер обмена
- **Очистить** — очистка файла логов
- **Обновить** — принудительное обновление

Логи автоматически обновляются каждые 10 секунд.

---

# 🐳 Docker

## Сборка из исходников

```bash
docker build -t fb2cng-web .

docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  fb2cng-web
```

## Готовый образ из Docker Hub

```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  quetureve/fb2cng-web-ui:latest
```

---

# 📦 Требования

- Docker Engine 20.10+
- Docker Compose 2.0+

Поддерживаемые архитектуры:

- `linux/amd64`
- `linux/arm64`

---

# 📝 Лицензия

MIT

---

# 🙏 Благодарности

- [fb2cng](https://github.com/rupor-github/fb2cng)
- Flask
- Celery
- Redis