"""Точка входа воркера. Заглушка каркаса: реальный цикл (jobs, SKIP LOCKED) — задача 6."""
import logging
import time

from app.config import get_settings
from app.logging import setup_logging

log = logging.getLogger("app.worker")

if __name__ == "__main__":
    setup_logging(get_settings().log_level)
    log.info("worker_started_stub")
    while True:
        time.sleep(60)
