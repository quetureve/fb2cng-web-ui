import os
import re
import platform
import subprocess
import smtplib
import yaml
import zipfile
import tempfile
import shutil
import time
import logging
import requests
from email.message import EmailMessage
from pathlib import Path
from celery import Celery
import auto_scan

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery = Celery(__name__, broker=REDIS_URL, backend=REDIS_URL)

BASE_DIR = Path('/app/data')
UPLOAD_FOLDER = BASE_DIR / 'uploads'
RESULT_FOLDER = BASE_DIR / 'results'
CONFIG_FOLDER = BASE_DIR / 'configs'
LOG_FILE = BASE_DIR / 'logs/converter.log'
SMTP_CONFIG_FILE = CONFIG_FOLDER / 'smtp.yaml'
SCAN_CONFIG_FILE = CONFIG_FOLDER / 'scan.yaml'

FBC_CMD = os.getenv('FBC_PATH', 'fbc')
FBC_BIN = Path(FBC_CMD)
FBC_DIR = FBC_BIN.parent
FBC_VERSION_FILE = FBC_DIR / 'VERSION'
FB2CNG_REPO = 'rupor-github/fb2cng'
RESULT_RETENTION_SECONDS = 24 * 3600  # хранить результаты ручной конвертации сутки

for folder in [UPLOAD_FOLDER, RESULT_FOLDER, CONFIG_FOLDER, BASE_DIR / 'logs']:
    folder.mkdir(parents=True, exist_ok=True)

# Настройка логирования: пишем и в файл, и в консоль
if not LOG_FILE.exists():
    LOG_FILE.touch()
    LOG_FILE.chmod(0o666)

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

def load_smtp_config():
    if SMTP_CONFIG_FILE.exists():
        with open(SMTP_CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def load_scan_config():
    if SCAN_CONFIG_FILE.exists():
        with open(SCAN_CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}

def normalize_filename(filename):
    name, ext = os.path.splitext(filename)
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'[.,;:_\-]+$', '', name)
    if not name:
        name = "converted"
    return f"{name}{ext}"

def send_email_via_smtp(recipient, subject, body, attachment_paths, timeout=90, retries=2):
    cfg = load_smtp_config()
    if not cfg.get('server'):
        raise RuntimeError("SMTP не настроен.")
    if not recipient:
        raise RuntimeError("Не указан email получателя.")
    msg = EmailMessage()
    msg['From'] = cfg['sender']
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.set_content(body)
    for attach_path in attachment_paths:
        with open(attach_path, 'rb') as f:
            msg.add_attachment(f.read(), maintype='application', subtype='octet-stream', filename=Path(attach_path).name)

    for attempt in range(retries):
        try:
            logger.info(f"Отправка email на {recipient}, попытка {attempt+1}")
            with smtplib.SMTP(cfg['server'], cfg['port'], timeout=timeout) as server:
                if cfg.get('use_tls', True):
                    server.starttls()
                server.login(cfg['username'], cfg['password'])
                server.send_message(msg)
            logger.info("Email успешно отправлен")
            return
        except (smtplib.SMTPServerDisconnected, TimeoutError, ConnectionError) as e:
            logger.warning(f"Ошибка отправки (попытка {attempt+1}): {e}")
            if attempt == retries - 1:
                raise
            time.sleep(2)
        except Exception as e:
            logger.exception("Неожиданная ошибка при отправке email")
            raise

def fix_config_paths(config_path):
    if not config_path or not Path(config_path).exists():
        return config_path

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if not config:
        return config_path

    config_dir = Path(config_path).parent
    modified = False
    path_keys = ['stylesheet_path', 'cover_image', 'default_image_path', 'font_path', 'image_path', 'cover', 'stylesheet', 'font']

    def fix_paths(obj):
        nonlocal modified
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in path_keys and isinstance(v, str) and v:
                    if v.startswith('/app/') and not v.startswith('/app/data/configs/'):
                        filename = Path(v).name
                        new_path = config_dir / filename
                        if new_path.exists():
                            obj[k] = str(new_path)
                            modified = True
                            logger.info(f"Fixed {k}: {v} -> {new_path}")
                        else:
                            logger.warning(f"File {filename} not found, keeping {v}")
                    elif not v.startswith('/'):
                        abs_path = config_dir / v
                        if abs_path.exists():
                            obj[k] = str(abs_path)
                            modified = True
                            logger.info(f"Fixed {k}: {v} -> {abs_path}")
                        else:
                            logger.warning(f"Path {v} not found, keeping as is")
                else:
                    fix_paths(v)
        elif isinstance(obj, list):
            for item in obj:
                fix_paths(item)

    fix_paths(config)

    if modified:
        tmp_path = Path(tempfile.mktemp(suffix='.yaml', dir=config_dir))
        with open(tmp_path, 'w') as f:
            yaml.dump(config, f)
        logger.info(f"Created temporary fixed config: {tmp_path}")
        return str(tmp_path)
    return config_path

def convert_single_fb2(fb2_path, output_format, fbc_config_path, output_dir):
    fixed_config = fix_config_paths(fbc_config_path)
    is_temp_config = bool(fixed_config) and fixed_config != fbc_config_path
    try:
        cmd = [FBC_CMD, 'convert', '--to', output_format]
        if fixed_config and Path(fixed_config).exists():
            cmd.extend(['--config', fixed_config])
        cmd.extend([str(fb2_path), str(output_dir)])
        logger.info(f"Running: {' '.join(cmd)}")
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"fb2cng ошибка: {proc.stderr}")
        ext_map = {'epub2':'epub','epub3':'epub','kepub':'epub','kfx':'kfx','azw8':'azw8','pdf':'pdf','txt':'txt','md':'md'}
        ext = ext_map.get(output_format, 'epub')
        candidates = list(output_dir.glob(f'*.{ext}'))
        if not candidates and output_format == 'kepub':
            candidates = list(output_dir.glob('*.epub'))
        if not candidates:
            raise RuntimeError(f"Выходной файл .{ext} не найден")
        return candidates[0]
    finally:
        # fix_config_paths() мог создать временный YAML в configs/ — раньше он
        # удалялся только при ошибке fbc, и накапливался там при успехе.
        if is_temp_config and Path(fixed_config).exists():
            Path(fixed_config).unlink()

def _resolve_output_path(output_dir, final_name, used_names, disambiguator):
    """Путь для сохранения результата. Суффикс добавляется, только если имя
    уже встречалось В ЭТОМ ЖЕ вызове (например, два разных fb2 в одном ZIP
    нормализовались в одинаковое имя). Файл, оставшийся в output_dir от
    ДРУГОЙ, более ранней конвертации, не считается коллизией и будет
    перезаписан — так повторная конвертация той же книги просто обновляет
    файл, а не плодит копии со случайными суффиксами."""
    final_path = output_dir / final_name
    if final_name in used_names:
        final_path = output_dir / f"{final_path.stem}_{disambiguator}{final_path.suffix}"
    used_names.add(final_name)
    return final_path

def convert_single_file(input_path, output_format, send_email, fbc_config_path=None, output_dir=None):
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")

    if output_dir is None:
        output_dir = RESULT_FOLDER
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    output_files = []
    used_names = set()
    logger.info(f"Конвертация файла: {input_path.name}")

    if input_path.suffix.lower() == '.zip':
        with tempfile.TemporaryDirectory() as tmpdir:
            extract_dir = Path(tmpdir) / 'extract'
            extract_dir.mkdir()
            with zipfile.ZipFile(input_path, 'r') as zf:
                zf.extractall(extract_dir)
            fb2_files = list(extract_dir.rglob('*.fb2'))
            if not fb2_files:
                raise RuntimeError("В ZIP-архиве нет FB2 файлов")
            conv_dir = Path(tmpdir) / 'converted'
            conv_dir.mkdir()
            for fb2 in fb2_files:
                rel_dir = fb2.relative_to(extract_dir).parent
                target_dir = conv_dir / rel_dir
                target_dir.mkdir(parents=True, exist_ok=True)
                out_file = convert_single_fb2(fb2, output_format, fbc_config_path, target_dir)
                final_name = normalize_filename(out_file.name)
                final_path = _resolve_output_path(output_dir, final_name, used_names, fb2.stem[:8])
                shutil.move(str(out_file), str(final_path))
                output_files.append(str(final_path))
                logger.info(f"Сконвертирован FB2: {fb2.name} -> {final_path.name}")
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = convert_single_fb2(input_path, output_format, fbc_config_path, Path(tmpdir))
            final_name = normalize_filename(out_file.name)
            final_path = _resolve_output_path(output_dir, final_name, used_names, input_path.stem[:8])
            shutil.move(str(out_file), str(final_path))
            output_files.append(str(final_path))
            logger.info(f"Сконвертирован файл: {input_path.name} -> {final_path.name}")

    if send_email:
        cfg = load_smtp_config()
        recipient = cfg.get('recipient_email')
        if recipient:
            try:
                send_email_via_smtp(recipient, f"Готовая книга ({output_format})", "Файл прикреплён.", output_files)
                logger.info(f"Email отправлен на {recipient}")
            except Exception as e:
                logger.exception("Ошибка отправки email")
    return output_files

@celery.task(bind=True)
def convert_book(self, task_id, input_path, output_format, send_email, fbc_config_path=None):
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Файл не найден: {input_path}")
    try:
        logger.info(f"Получена задача {task_id}: {input_path.name}")
        result_files = convert_single_file(input_path, output_format, send_email, fbc_config_path, output_dir=RESULT_FOLDER)
        output_filenames = [Path(f).name for f in result_files]
        download_urls = [f"/download/{fname}" for fname in output_filenames]
        logger.info(f"Задача {task_id} выполнена, файлы: {output_filenames}")
        return {
            'output_filenames': output_filenames,
            'download_urls': download_urls,
            'email_sent': send_email,
            'format': output_format
        }
    except Exception:
        # Раньше исключение гасилось и возвращалось как {'error': ...} — Celery
        # считал задачу SUCCESS, а фронтенд рисовал "Готово!" без ссылки на
        # скачивание. Теперь ошибка всплывает по-настоящему: task.failed()
        # срабатывает, и /status/<task_id> отдаёт её в поле error.
        logger.exception(f"Задача {task_id} завершилась ошибкой")
        raise


@celery.task(bind=True)
def scan_folder_task(self):
    """Один шаг цепочки автоскана. Каждый вызов сам решает, продолжать ли:
    читает scan.yaml, и если enabled=True — делает проход и планирует
    следующий вызов через interval секунд. Так исключается прежняя проблема
    привязки состояния к конкретному процессу gunicorn: единственный источник
    истины — файл на общем volume, а не Python-переменная в памяти."""
    config = load_scan_config()
    if not config.get('enabled'):
        logger.info("Автоскан: выключен, цепочка остановлена")
        return {'running': False}
    try:
        count = auto_scan.scan_once(config)
        if count:
            logger.info(f"Автоскан: за проход обработано файлов: {count}")
    except Exception:
        logger.exception("Автоскан: ошибка прохода, цепочка продолжится по расписанию")
    interval = max(1, int(config.get('interval', 5)))
    scan_folder_task.apply_async(countdown=interval)
    return {'running': True}


def _detect_fbc_arch():
    machine = platform.machine().lower()
    if machine in ('x86_64', 'amd64'):
        return 'amd64'
    if machine in ('aarch64', 'arm64'):
        return 'arm64'
    raise RuntimeError(f"Неизвестная архитектура сервера: {machine}")


def get_installed_fbc_version():
    if FBC_VERSION_FILE.exists():
        return FBC_VERSION_FILE.read_text().strip()
    return None


def get_latest_fbc_release():
    """Метаданные последнего релиза fb2cng с GitHub (используется и роутом
    проверки версии, и самой задачей обновления)."""
    resp = requests.get(f"https://api.github.com/repos/{FB2CNG_REPO}/releases/latest", timeout=30)
    resp.raise_for_status()
    return resp.json()


@celery.task(bind=True)
def update_fbc(self):
    """Скачивает последнюю версию fb2cng с GitHub и подменяет бинарник на
    общем volume. Замена атомарная (staged-файл + rename), поэтому уже
    запущенные в этот момент конвертации со старым бинарником не пострадают —
    новую версию подхватят только следующие запуски subprocess."""
    arch = _detect_fbc_arch()
    release = get_latest_fbc_release()
    tag = release.get('tag_name')
    if not tag:
        raise RuntimeError("GitHub не вернул tag_name последнего релиза")

    asset_name = f"fbc-linux-{arch}.zip"
    asset = next((a for a in release.get('assets', []) if a.get('name') == asset_name), None)
    if not asset:
        raise RuntimeError(f"В релизе {tag} не найден файл {asset_name}")

    current_version = get_installed_fbc_version()
    if current_version == tag:
        logger.info(f"fb2cng уже последней версии: {tag}")
        return {'updated': False, 'version': tag, 'previous_version': current_version}

    logger.info(f"Обновление fb2cng: {current_version or '?'} -> {tag} ({asset_name})")
    FBC_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_zip = Path(tmpdir) / asset_name
        with requests.get(asset['browser_download_url'], stream=True, timeout=180) as r:
            r.raise_for_status()
            with open(tmp_zip, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)

        extract_dir = Path(tmpdir) / 'extract'
        extract_dir.mkdir()
        with zipfile.ZipFile(tmp_zip, 'r') as zf:
            zf.extractall(extract_dir)

        new_binary = extract_dir / 'fbc'
        if not new_binary.exists():
            found = list(extract_dir.rglob('fbc'))
            if not found:
                raise RuntimeError("В скачанном архиве не найден исполняемый файл fbc")
            new_binary = found[0]
        new_binary.chmod(0o755)

        check = subprocess.run([str(new_binary), '--version'], capture_output=True, text=True, timeout=30)
        if check.returncode != 0:
            raise RuntimeError(f"Скачанный fbc не запускается: {check.stderr.strip() or check.stdout.strip()}")
        logger.info(f"Проверка новой версии: {check.stdout.strip()}")

        staged = FBC_DIR / '.fbc.new'
        shutil.copy(str(new_binary), str(staged))
        staged.chmod(0o755)
        staged.replace(FBC_BIN)  # атомарный rename на том же ФС

    FBC_VERSION_FILE.write_text(tag)
    logger.info(f"fb2cng обновлён: {current_version or '?'} -> {tag}")
    return {'updated': True, 'version': tag, 'previous_version': current_version}