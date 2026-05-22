import os
import uuid
import yaml
import threading
import io
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_file
from celery.result import AsyncResult
from tasks import convert_book
import auto_scan

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path('/app/data')
UPLOAD_FOLDER = BASE_DIR / 'uploads'
RESULT_FOLDER = BASE_DIR / 'results'
CONFIG_FOLDER = BASE_DIR / 'configs'
SMTP_CONFIG_FILE = CONFIG_FOLDER / 'smtp.yaml'
SCAN_CONFIG_FILE = CONFIG_FOLDER / 'scan.yaml'
ACTIVE_CONFIG_FILE = CONFIG_FOLDER / 'active_config.txt'
LOG_FILE = BASE_DIR / 'logs/converter.log'

for folder in [UPLOAD_FOLDER, RESULT_FOLDER, CONFIG_FOLDER, BASE_DIR / 'logs']:
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

def load_scan_config():
    if SCAN_CONFIG_FILE.exists():
        with open(SCAN_CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def save_scan_config(config):
    with open(SCAN_CONFIG_FILE, 'w') as f:
        yaml.dump(config, f)

def get_active_config():
    if ACTIVE_CONFIG_FILE.exists():
        return ACTIVE_CONFIG_FILE.read_text().strip()
    return None

def set_active_config(filename):
    ACTIVE_CONFIG_FILE.write_text(filename)

def list_configs():
    return [f.name for f in CONFIG_FOLDER.glob('*.yaml') if f.name not in ('smtp.yaml', 'scan.yaml')]

@app.route('/')
def index():
    smtp = load_smtp_config()
    active_config = get_active_config()
    configs = list_configs()
    scan_cfg = load_scan_config()
    scan_running = auto_scan.scan_thread is not None and auto_scan.scan_thread.is_alive()
    return render_template('index.html',
                           smtp=smtp,
                           active_config=active_config,
                           configs=configs,
                           scan_cfg=scan_cfg,
                           scan_running=scan_running)

@app.route('/upload', methods=['POST'])
def upload():
    for f in RESULT_FOLDER.iterdir():
        if f.is_file():
            f.unlink()
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Пустое имя файла'}), 400
    if not (file.filename.lower().endswith('.fb2') or file.filename.lower().endswith('.zip')):
        return jsonify({'error': 'Поддерживаются только FB2 или ZIP'}), 400

    task_id = str(uuid.uuid4())
    input_path = UPLOAD_FOLDER / f"{task_id}{Path(file.filename).suffix}"
    file.save(input_path)

    output_format = request.form.get('format', 'epub2')
    send_email = request.form.get('send_email') == 'true'

    active = get_active_config()
    fbc_config_path = str(CONFIG_FOLDER / active) if active else None

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
    response = {'task_id': task_id, 'status': task.status}
    if task.successful():
        result = task.result
        response['result'] = result
        if 'download_urls' in result:
            response['download_urls'] = result['download_urls']
    elif task.failed():
        response['error'] = str(task.info)
    return jsonify(response)

@app.route('/download/<path:filename>')
def download_result(filename):
    filepath = RESULT_FOLDER / filename
    if not filepath.exists():
        auto_results = BASE_DIR / 'auto_results'
        filepath = auto_results / filename
    if not filepath.exists():
        return "Файл не найден", 404
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route('/upload_resources', methods=['POST'])
def upload_resources():
    if 'files' not in request.files:
        return jsonify({'error': 'Файлы не загружены'}), 400
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'Пустые файлы'}), 400
    uploaded_yaml = []
    for file in files:
        if file.filename:
            save_path = CONFIG_FOLDER / file.filename
            file.save(str(save_path))
            if file.filename.endswith(('.yaml', '.yml')):
                uploaded_yaml.append(file.filename)
    if uploaded_yaml:
        set_active_config(uploaded_yaml[0])
        return jsonify({'status': 'ok', 'message': f'Загружено {len(uploaded_yaml)} конфиг(ов). Активным стал {uploaded_yaml[0]}', 'active': uploaded_yaml[0]})
    return jsonify({'status': 'ok', 'message': 'Файлы загружены (конфиги не найдены)'})

@app.route('/delete_config', methods=['POST'])
def delete_config():
    data = request.get_json()
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'Не указано имя'}), 400
    filepath = CONFIG_FOLDER / filename
    if filepath.exists():
        filepath.unlink()
        if get_active_config() == filename:
            ACTIVE_CONFIG_FILE.unlink()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Файл не найден'}), 404

@app.route('/set_active_config', methods=['POST'])
def set_active_config_route():
    data = request.get_json()
    filename = data.get('filename')
    if not filename:
        return jsonify({'error': 'Не указано имя'}), 400
    if not (CONFIG_FOLDER / filename).exists():
        return jsonify({'error': 'Файл не найден'}), 404
    set_active_config(filename)
    return jsonify({'status': 'ok', 'active': filename})

@app.route('/smtp_settings', methods=['POST'])
def smtp_settings():
    data = request.get_json()
    required = ['server', 'port', 'username', 'password', 'sender']
    if not all(k in data for k in required):
        return jsonify({'error': 'Заполните все поля'}), 400
    save_smtp_config({
        'server': data['server'],
        'port': int(data['port']),
        'username': data['username'],
        'password': data['password'],
        'sender': data['sender'],
        'recipient_email': data.get('recipient_email', ''),
        'use_tls': data.get('use_tls', True)
    })
    return jsonify({'status': 'ok', 'message': 'SMTP сохранены'})

@app.route('/scan_settings', methods=['POST'])
def scan_settings():
    data = request.get_json()
    active = get_active_config()
    fbc_config_path = str(CONFIG_FOLDER / active) if active else None
    config = {
        'format': data.get('format', 'epub2'),
        'send_email': data.get('send_email', False),
        'interval': int(data.get('interval', 5)),
        'fbc_config_path': fbc_config_path
    }
    save_scan_config(config)
    if data.get('enabled', False):
        try:
            auto_scan.start_scan(config)
        except Exception as e:
            return jsonify({'error': f'Ошибка запуска: {str(e)}'}), 500
    else:
        auto_scan.stop_scan()
    return jsonify({'status': 'ok', 'message': 'Настройки автосканирования сохранены'})

@app.route('/scan_status', methods=['GET'])
def scan_status():
    running = auto_scan.scan_thread is not None and auto_scan.scan_thread.is_alive()
    return jsonify({'running': running})

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    try:
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.truncate(0)
        return jsonify({'status': 'ok', 'message': 'Логи очищены'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/logs', methods=['GET'])
def get_logs():
    lines = int(request.args.get('lines', 200))
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                tail = f.readlines()[-lines:]
                return jsonify({'logs': ''.join(tail)})
        except Exception as e:
            return jsonify({'logs': f'Ошибка чтения логов: {str(e)}'})
    else:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.touch()
        LOG_FILE.chmod(0o666)
        return jsonify({'logs': 'Лог-файл создан, пока пуст'})

@app.route('/download_example_config')
def download_example_config():
    example_path = Path('fbc_config.yaml')
    if example_path.exists():
        return send_file(example_path, as_attachment=True, download_name='fb2cng_config.yaml')
    else:
        sample = """version: 1
document:
  output_name_template: "{{ .Title }} - {{ range .Authors }}{{ .LastName }} {{ .FirstName }}{{ end }}"
  metainformation:
    title_template: "{{ .Title }}"
    creator_name_template: "{{ .LastName }} {{ .FirstName }}"
  # stylesheet_path: "mystyle.css"
  # cover_image: "cover.jpg"
  images:
    optimize: true
    jpeg_quality_level: 80
  footnotes:
    mode: float
  dropcaps:
    enable: true
"""
        return send_file(io.BytesIO(sample.encode()), as_attachment=True, download_name='fb2cng_config.yaml', mimetype='text/yaml')

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