import os
import time
import threading
import logging
import shutil
from pathlib import Path
from tasks import convert_single_file

logger = logging.getLogger(__name__)

scan_thread = None
stop_scan_event = threading.Event()
last_processed = set()

def get_paths():
    base = Path('/app/data')
    return {
        'in': base / 'auto_in',
        'processed': base / 'auto_processed',
        'results': base / 'auto_results'
    }

def scan_and_process(config):
    paths = get_paths()
    in_folder = paths['in']
    processed_folder = paths['processed']
    results_folder = paths['results']

    for p in [in_folder, processed_folder, results_folder]:
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created folder: {p}")

    interval = config.get('interval', 5)
    fmt = config['format']
    send_email = config['send_email']
    fbc_config_path = config.get('fbc_config_path')

    while not stop_scan_event.is_set():
        try:
            files = list(in_folder.glob('*'))
            for file_path in files:
                if file_path.is_dir():
                    continue
                if file_path.suffix.lower() not in ('.fb2', '.zip'):
                    continue
                if str(file_path) in last_processed:
                    continue
                last_processed.add(str(file_path))
                logger.info(f"Auto-scan found: {file_path}")

                try:
                    result_files = convert_single_file(
                        file_path, fmt, send_email, fbc_config_path, output_dir=results_folder
                    )
                    if result_files:
                        dest_path = processed_folder / file_path.name
                        shutil.move(str(file_path), str(dest_path))
                        logger.info(f"Moved original to {dest_path}")
                        logger.info(f"Auto processed: {file_path.name}, results saved to {results_folder}")
                    else:
                        logger.error(f"Auto conversion failed for {file_path.name}")
                except Exception as e:
                    logger.exception(f"Error processing {file_path}")
        except Exception as e:
            logger.exception("Auto-scan error")
        for _ in range(interval):
            if stop_scan_event.is_set():
                break
            time.sleep(1)

def start_scan(config):
    global scan_thread, stop_scan_event
    if scan_thread and scan_thread.is_alive():
        stop_scan_event.set()
        scan_thread.join()
    stop_scan_event.clear()
    scan_thread = threading.Thread(target=scan_and_process, args=(config,), daemon=True)
    scan_thread.start()
    logger.info("Auto-scan thread started")

def stop_scan():
    global scan_thread, stop_scan_event
    stop_scan_event.set()
    if scan_thread:
        scan_thread.join()
        scan_thread = None
    logger.info("Auto-scan thread stopped")