"""Точка входа воркера кредитного конвейера.

Поддерживает запуск:
  python -m app.worker          - непрерывный фоновый цикл (long-running process)
  python -m app.worker --once   - разовый прогон очереди и проверок watchdog
"""
import argparse
import logging
import sys

from app.config import get_settings
from app.logging import setup_logging
from app.worker.deps import get_worker_deps
from app.worker.runner import WorkerRunner

log = logging.getLogger("app.worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Воркер кредитного конвейера")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Выполнить один проход по очереди и проверкам watchdog, затем завершить работу",
    )
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)

    try:
        deps = get_worker_deps(settings=settings)
    except RuntimeError as exc:
        log.error("worker_startup_failed", extra={"error": str(exc)})
        print(f"Ошибка запуска воркера: {exc}", file=sys.stderr)
        sys.exit(1)

    runner = WorkerRunner(deps=deps)

    if args.once:
        sys.exit(runner.run_once())
    else:
        runner.run_loop()


if __name__ == "__main__":
    main()
