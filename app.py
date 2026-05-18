import os
import uuid
import yaml
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_file
from celery.result import AsyncResult
from tasks import convert_book

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path('/app/data')
UPLOAD_FOLDER = BASE_DIR / 'uploads'
RESULT_FOLDER = BASE_DIR / 'results'
CONFIG_FOLDER = BASE_DIR / 'configs'
SMTP_CONFIG_FILE = CONFIG_FOLDER / 'smtp.yaml'
FBC_CONFIG_FILE = CONFIG_FOLDER / 'fb2cng.yaml'

for folder in [UPLOAD_FOLDER, RESULT_FOLDER, CONFIG_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['RESULT_FOLDER'] = RESULT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

def load_smtp_config():
    if SMTP_CONFIG_FILE.exists():
        with open(SMTP_CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def save_smtp_config(config):
    with open(SMTP_CONFIG_FILE, 'w') as f:
        yaml.dump(config, f)

def load_fbc_config():
    if FBC_CONFIG_FILE.exists():
        return str(FBC_CONFIG_FILE)
    return None

@app.route('/')
def index():
    smtp = load_smtp_config()
    has_fbc_config = FBC_CONFIG_FILE.exists()
    return render_template('index.html', smtp=smtp, has_fbc_config=has_fbc_config)

@app.route('/upload', methods=['POST'])
def upload():
    # Очищаем папку с результатами перед новой конвертацией
    for f in RESULT_FOLDER.iterdir():
        if f.is_file():
            f.unlink()

    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Пустое имя файла'}), 400
    if not (file.filename.lower().endswith('.fb2') or file.filename.lower().endswith('.zip')):
        return jsonify({'error': 'Поддерживаются только FB2 или ZIP файлы'}), 400

    task_id = str(uuid.uuid4())
    input_path = UPLOAD_FOLDER / f"{task_id}{Path(file.filename).suffix}"
    file.save(input_path)

    output_format = request.form.get('format', 'epub2')
    send_email = request.form.get('send_email') == 'true'

    fbc_config_path = load_fbc_config()

    result = convert_book.delay(
        task_id=task_id,
        input_path=str(input_path),
        output_format=output_format,
        send_email=send_email,
        fbc_config_path=fbc_config_path
    )

    return jsonify({'task_id': result.id, 'status': 'pending'})

@app.route('/status/<task_id>')
def task_status(task_id):
    task = AsyncResult(task_id, app=app.celery_app)
    response = {
        'task_id': task_id,
        'status': task.status,
    }
    if task.successful():
        result = task.result
        response['result'] = result
        if 'download_urls' in result:
            response['download_urls'] = result['download_urls']
        elif 'download_url' in result:
            response['download_url'] = result['download_url']
    elif task.failed():
        response['error'] = str(task.info)
    return jsonify(response)

@app.route('/download/<path:filename>')
def download_result(filename):
    filepath = RESULT_FOLDER / filename
    if not filepath.exists():
        return "Файл не найден", 404
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route('/upload_fbc_config', methods=['POST'])
def upload_fbc_config():
    if 'config' not in request.files:
        return jsonify({'error': 'Файл конфигурации не загружен'}), 400
    file = request.files['config']
    if file.filename == '':
        return jsonify({'error': 'Пустой файл'}), 400
    if not file.filename.endswith(('.yaml', '.yml')):
        return jsonify({'error': 'Требуется YAML файл'}), 400

    file.save(str(FBC_CONFIG_FILE))
    return jsonify({'status': 'ok', 'message': 'Конфигурация fb2cng обновлена'})

@app.route('/delete_fbc_config', methods=['POST'])
def delete_fbc_config():
    if FBC_CONFIG_FILE.exists():
        FBC_CONFIG_FILE.unlink()
    return jsonify({'status': 'ok', 'message': 'Конфигурация удалена, используются стандартные настройки'})

@app.route('/smtp_settings', methods=['POST'])
def smtp_settings():
    data = request.get_json()
    required = ['server', 'port', 'username', 'password', 'sender']
    if not all(k in data for k in required):
        return jsonify({'error': 'Заполните все обязательные поля SMTP'}), 400

    save_smtp_config({
        'server': data['server'],
        'port': int(data['port']),
        'username': data['username'],
        'password': data['password'],
        'sender': data['sender'],
        'recipient_email': data.get('recipient_email', ''),
        'use_tls': data.get('use_tls', True)
    })
    return jsonify({'status': 'ok', 'message': 'SMTP настройки сохранены'})

def make_celery(app):
    from celery import Celery
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)
    return celery

app.config.update(
    CELERY_BROKER_URL=os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    CELERY_RESULT_BACKEND=os.getenv('REDIS_URL', 'redis://localhost:6379/0')
)
app.celery_app = make_celery(app)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)