# FB2 Converter Web UI

Веб-интерфейс для конвертации FB2 книг в EPUB2, EPUB3, KEPUB, KFX, AZW8 с использованием [fb2cng](https://github.com/rupor-github/fb2cng).  
Поддерживает загрузку ZIP-архивов с FB2, настройку SMTP для отправки результатов по email, загрузку пользовательского конфига fb2cng.

## Запуск

```bash
git clone https://github.com/ВАШ_ЛОГИН/fb2cng-web-ui.git
cd fb2cng-web-ui
docker compose up -d --build
