import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def get_paths():
    base = Path('/app/data')
    return {
        'in': base / 'auto_in',
        'processed': base / 'auto_processed',
        'results': base / 'auto_results',
        'failed': base / 'auto_failed',
    }


def scan_once(config):
    """Один проход по папке auto_in. Обрабатывает все новые файлы и возвращает
    их количество. Не хранит никакого состояния между вызовами: файл либо
    остаётся в auto_in (значит, ещё не увиден), либо уезжает в auto_processed
    (успех), либо в auto_failed (ошибка) — так что на следующий проход просто
    заново смотрим, что лежит в auto_in, без отдельного списка "уже видели"."""
    # Локальный импорт, чтобы избежать циклического импорта с tasks.py (там, в
    # свою очередь, импортируется этот модуль для планирования задачи скана).
    from tasks import convert_single_file

    paths = get_paths()
    in_folder = paths['in']
    processed_folder = paths['processed']
    results_folder = paths['results']
    failed_folder = paths['failed']

    for p in (in_folder, processed_folder, results_folder, failed_folder):
        p.mkdir(parents=True, exist_ok=True)

    fmt = config['format']
    send_email = config['send_email']
    fbc_config_path = config.get('fbc_config_path')

    processed_count = 0
    try:
        files = sorted(f for f in in_folder.glob('*') if f.is_file())
    except Exception:
        logger.exception("Автоскан: не удалось прочитать auto_in")
        return 0

    for file_path in files:
        if file_path.suffix.lower() not in ('.fb2', '.zip'):
            continue
        logger.info(f"Автоскан нашёл: {file_path.name}")
        try:
            result_files = convert_single_file(
                file_path, fmt, send_email, fbc_config_path, output_dir=results_folder
            )
            if result_files:
                shutil.move(str(file_path), str(processed_folder / file_path.name))
                logger.info(f"Автоскан обработал: {file_path.name} -> {results_folder}")
                processed_count += 1
            else:
                shutil.move(str(file_path), str(failed_folder / file_path.name))
                logger.error(f"Автоскан: конвертация не дала файлов, перемещено в auto_failed: {file_path.name}")
        except Exception:
            logger.exception(f"Автоскан: ошибка при обработке {file_path.name}")
            try:
                shutil.move(str(file_path), str(failed_folder / file_path.name))
            except Exception:
                logger.exception(f"Автоскан: не удалось переместить {file_path.name} в auto_failed")
    return processed_count


def enable_scan():
    """Планирует первый проход цепочки задач автоскана. Вызывать только при
    переходе выключено -> включено — иначе получим несколько параллельных
    цепочек (см. проверку was_enabled в app.py /scan_settings)."""
    from tasks import scan_folder_task
    scan_folder_task.delay()
    logger.info("Автоскан: запланирован первый проход")


def disable_scan():
    """Явных действий не требует: каждый проход сам читает scan.yaml и не
    планирует следующий, если enabled=False. Функция оставлена для
    симметрии с enable_scan() и для записи в лог."""
    logger.info("Автоскан: выключение запрошено, цепочка остановится в течение одного интервала")
