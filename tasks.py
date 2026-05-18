import os
import re
import subprocess
import smtplib
import yaml
import zipfile
import tempfile
import shutil
from email.message import EmailMessage
from pathlib import Path
from celery import Celery

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery = Celery(__name__, broker=REDIS_URL, backend=REDIS_URL)

BASE_DIR = Path('/app/data')
UPLOAD_FOLDER = BASE_DIR / 'uploads'
RESULT_FOLDER = BASE_DIR / 'results'
CONFIG_FOLDER = BASE_DIR / 'configs'
SMTP_CONFIG_FILE = CONFIG_FOLDER / 'smtp.yaml'

def load_smtp_config():
    if SMTP_CONFIG_FILE.exists():
        with open(SMTP_CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def normalize_filename(filename):
    """Очищает имя файла: убирает множественные пробелы, недопустимые символы."""
    name, ext = os.path.splitext(filename)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'[.,;:_\-]+$', '', name)
    if not name:
        name = "converted"
    return f"{name}{ext}"

def send_email_via_smtp(recipient, subject, body, attachment_paths, timeout=120):
    cfg = load_smtp_config()
    if not cfg.get('server'):
        raise RuntimeError("SMTP не настроен.")
    if not recipient:
        raise RuntimeError("Не указан email получателя в настройках SMTP.")

    msg = EmailMessage()
    msg['From'] = cfg['sender']
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.set_content(body)

    for attach_path in attachment_paths:
        with open(attach_path, 'rb') as f:
            file_data = f.read()
            filename = Path(attach_path).name
            msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=filename)

    try:
        with smtplib.SMTP(cfg['server'], cfg['port'], timeout=timeout) as server:
            if cfg.get('use_tls', True):
                server.starttls()
            server.login(cfg['username'], cfg['password'])
            server.send_message(msg)
    except (smtplib.SMTPServerDisconnected, TimeoutError) as e:
        import time
        time.sleep(2)
        with smtplib.SMTP(cfg['server'], cfg['port'], timeout=timeout) as server:
            if cfg.get('use_tls', True):
                server.starttls()
            server.login(cfg['username'], cfg['password'])
            server.send_message(msg)

def convert_single_fb2(fb2_path, output_format, fbc_config_path, output_dir):
    cmd = ['fbc', 'convert', '--to', output_format]
    if fbc_config_path and Path(fbc_config_path).exists():
        cmd.extend(['--config', fbc_config_path])
    cmd.extend([str(fb2_path), str(output_dir)])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"fb2cng ошибка для {fb2_path.name}: {proc.stderr}")

    ext_map = {
        'epub2': 'epub', 'epub3': 'epub', 'kepub': 'epub',
        'kfx': 'kfx', 'azw8': 'azw8'
    }
    ext = ext_map.get(output_format, 'epub')
    candidates = list(output_dir.glob(f'*.{ext}'))
    if not candidates and output_format == 'kepub':
        candidates = list(output_dir.glob('*.epub'))
    if not candidates:
        raise RuntimeError(f"Выходной файл .{ext} не найден для {fb2_path.name}")
    return candidates[0]

@celery.task(bind=True)
def convert_book(self, task_id, input_path, output_format, send_email, fbc_config_path=None):
    input_path = Path(input_path)
    if not input_path.exists():
        return {'error': f'Входной файл не найден: {input_path}'}

    output_filenames = []
    error_msg = None
    smtp_cfg = load_smtp_config()
    recipient_email = smtp_cfg.get('recipient_email', '') if send_email else None

    try:
        if input_path.suffix.lower() == '.zip':
            with tempfile.TemporaryDirectory() as tmpdir:
                extract_dir = Path(tmpdir) / 'extract'
                extract_dir.mkdir()
                with zipfile.ZipFile(input_path, 'r') as zf:
                    zf.extractall(extract_dir)

                fb2_files = list(extract_dir.rglob('*.fb2'))
                if not fb2_files:
                    raise RuntimeError("В ZIP-архиве не найдено FB2 файлов")

                conv_temp_dir = Path(tmpdir) / 'converted'
                conv_temp_dir.mkdir()

                for fb2 in fb2_files:
                    rel_dir = fb2.relative_to(extract_dir).parent
                    target_dir = conv_temp_dir / rel_dir
                    target_dir.mkdir(parents=True, exist_ok=True)
                    out_file = convert_single_fb2(fb2, output_format, fbc_config_path, target_dir)
                    final_name = normalize_filename(out_file.name)
                    final_path = RESULT_FOLDER / final_name
                    shutil.move(str(out_file), str(final_path))
                    output_filenames.append(final_path.name)
        else:
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                out_file = convert_single_fb2(input_path, output_format, fbc_config_path, tmp_path)
                final_name = normalize_filename(out_file.name)
                final_path = RESULT_FOLDER / final_name
                shutil.move(str(out_file), str(final_path))
                output_filenames.append(final_path.name)
    except Exception as e:
        error_msg = str(e)
        return {'error': error_msg}

    email_sent = False
    email_error = None
    if send_email and recipient_email and output_filenames:
        attachment_paths = [RESULT_FOLDER / fname for fname in output_filenames]
        try:
            send_email_via_smtp(
                recipient=recipient_email,
                subject=f"Ваши сконвертированные книги ({output_format})",
                body=f"Конвертация завершена. Приложено {len(attachment_paths)} файлов.",
                attachment_paths=attachment_paths
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)

    download_urls = [f"/download/{fname}" for fname in output_filenames]

    return {
        'output_filenames': output_filenames,
        'download_urls': download_urls,
        'email_sent': email_sent,
        'email_error': email_error,
        'format': output_format
    }