# 📚 FB2 Converter Web UI

> Веб-интерфейс для конвертации книг FB2 в EPUB2, EPUB3, KEPUB, KFX и AZW8 с использованием [fb2cng](https://github.com/rupor-github/fb2cng).  
> Поддерживает загрузку ZIP-архивов, отправку результатов по email и загрузку собственного конфига fb2cng.
<img width="873" height="472" alt="image" src="https://github.com/user-attachments/assets/23be4ec4-f73a-4042-92a7-f0a45ea916f1" />

---

## ✨ Возможности

- Конвертация FB2 → EPUB2, EPUB3, KEPUB, KFX, AZW8
- Пакетная обработка — загружайте ZIP-архив с несколькими FB2
- Асинхронная обработка через Redis
- Отправка результатов на email (SMTP с TLS)
- Загрузка пользовательского YAML-конфига для fb2cng
- Drag & Drop загрузка файлов
- Прогресс-бар с реальными этапами
- Сохранение SMTP-настроек в браузере
- Docker-образ для ARM64 и AMD64

---

## 🚀 Быстрый старт

Проект можно запустить двумя способами:

- Локальная сборка из исходников
- Использование готового Docker-образа из Docker Hub

---

# 🛠 Вариант 1 — локальная сборка

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/quetureve/fb2cng-web-ui.git
cd fb2cng-web-ui
```

### 2. Запустите через Docker Compose

```bash
docker compose up -d --build
```

### 3. Откройте браузер

```text
http://localhost:5000
```

---

# 🐳 Вариант 2 — запуск через готовый Docker-образ

Docker Hub:  
https://hub.docker.com/r/quetureve/fb2cng-web-ui

### 1. Создайте файл `docker-compose.yaml`

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

### 2. Запустите контейнеры

```bash
docker compose up -d
```

### 3. Откройте браузер

```text
http://localhost:5000
```

---

## 🛠 Использование

### Основной экран

1. Перетащите FB2 или ZIP-файл (или нажмите для выбора).
2. Выберите выходной формат.
3. При необходимости включите:
   - **«Автоматически отправлять результат на email»**
4. Адрес получателя настраивается во вкладке **SMTP**.
5. Нажмите **«Конвертировать»**.

---

## 📧 Настройка SMTP

Перейдите на вкладку **SMTP настройки** и заполните:

- SMTP сервер (например, `smtp.gmail.com`)
- Порт (`587` для TLS или `465` для SSL)
- Имя пользователя (ваш email/логин)
- Пароль (или пароль приложения для Gmail)
- Email отправителя
- Email получателя (для автоотправки)
- Включите опцию **«Использовать TLS»**

---

## ⚙️ Загрузка конфига fb2cng

На вкладке **Конфиг fb2cng** загрузите YAML-файл с настройками.

Можно использовать собственный конфиг или скачать пример.

📖 Документация:  
[fb2cng guide](https://github.com/rupor-github/fb2cng)

---

## 🐳 Docker образ

### Сборка

```bash
docker build -t fb2cng-web .
```

### Запуск

```bash
docker run -d \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  fb2cng-web
```

---

## 📦 Требования

- Docker Engine 20.10+
- Docker Compose 2.0+
- Архитектуры:
  - `linux/arm64`
  - `linux/amd64`

---

## 📝 Лицензия

MIT

---

## 🙏 Благодарности

- [fb2cng](https://github.com/rupor-github/fb2cng)
- Flask
- Celery
- Redis
