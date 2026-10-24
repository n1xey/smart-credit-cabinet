"""Основной исполнитель очереди фоновых задач конвейера (Worker Runner).

Обеспечивает:
1. Захват задачи через claim_next_job() в короткой отдельной транзакции.
2. Вызов обработчика шага из HANDLERS в рабочей транзакции.
3. Фиксацию complete_job() при успехе или fail_job() с бэкоффом/эскалацией при ошибке.
4. Выполнение одиночного прогона run_once() (для CLI флага --once и интеграционных тестов).
5. Непрерывный цикл run_loop() с периодическим запуском watchdog и корректной обработкой сигналов.
"""
from datetime import datetime, timezone
import logging
import signal
import sys
import time

from app.models.tables import Job
from app.worker.deps import WorkerDeps
from app.worker.handlers import HANDLERS
from app.worker.queue import claim_next_job, fail_job
from app.worker.watchdog import run_watchdog_cycle

log = logging.getLogger("app.worker.runner")


class WorkerRunner:
    """Исполнитель фоновых задач воркера."""

    def __init__(self, deps: WorkerDeps, poll_interval_sec: float = 1.0) -> None:
        self.deps = deps
        self.poll_interval_sec = poll_interval_sec
        self._stop_requested = False

    def request_stop(self) -> None:
        """Запрашивает корректную остановку цикла воркера."""
        self._stop_requested = True

    def process_next_job(self) -> bool:
        """Захватывает и выполняет одну готовую задачу из очереди.

        Возвращает True, если задача была найдена и обработана; False, если очередь пуста.
        """
        # 1. Захватываем задачу отдельной короткой транзакцией
        with self.deps.session_factory() as session:
            job = claim_next_job(session)
            if job is None:
                return False
            job_id = job.id
            job_type = job.type
            app_id = job.application_id
            session.commit()

        log.info("claimed_job_for_processing", extra={"job_id": str(job_id), "type": job_type})

        # 2. Поиск обработчика
        handler = HANDLERS.get(job_type)
        if handler is None:
            log.error("unknown_job_type", extra={"job_id": str(job_id), "type": job_type})
            fail_job(
                session_factory=self.deps.session_factory,
                job_id=job_id,
                app_id=app_id,
                error_message=f"Неизвестный тип задачи: {job_type}",
                max_attempts=1,
                base_backoff_sec=1,
            )
            return True

        # 3. Выполнение обработчика в отдельной рабочей транзакции
        with self.deps.session_factory() as session:
            try:
                active_job = session.query(Job).filter(Job.id == job_id).first()
                if active_job is None:
                    log.warning("job_disappeared", extra={"job_id": str(job_id)})
                    return True

                handler(session, active_job, self.deps)
                session.commit()
                log.info("job_processed_successfully", extra={"job_id": str(job_id), "type": job_type})
            except Exception as exc:
                session.rollback()
                log.warning(
                    "job_step_handler_failed",
                    extra={"job_id": str(job_id), "type": job_type, "error": str(exc)},
                )
                fail_job(
                    session_factory=self.deps.session_factory,
                    job_id=job_id,
                    app_id=app_id,
                    error_message=str(exc),
                    max_attempts=self.deps.settings.job_max_attempts,
                    base_backoff_sec=self.deps.settings.job_base_backoff_sec,
                )

        return True

    def run_once(self) -> int:
        """Выполняет все готовые задачи в очереди, один цикл watchdog и завершает работу.

        Возвращает 0 при успешном завершении.
        """
        log.info("starting_run_once")
        processed_count = 0
        while not self._stop_requested:
            has_job = self.process_next_job()
            if not has_job:
                break
            processed_count += 1

        log.info("run_once_jobs_processed", extra={"count": processed_count})

        # Выполняем цикл проверок watchdog
        watchdog_stats = run_watchdog_cycle(self.deps)
        log.info("run_once_watchdog_finished", extra=watchdog_stats)

        return 0

    def run_loop(self) -> None:
        """Непрерывный цикл работы воркера до получения SIGINT / SIGTERM."""
        log.info("starting_worker_loop", extra={"poll_interval_sec": self.poll_interval_sec})

        def _sig_handler(signum, frame):
            log.info("stop_signal_received", extra={"signal": signum})
            self.request_stop()

        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)

        last_watchdog_run = 0.0
        watchdog_interval = float(self.deps.settings.watchdog_interval_sec)

        while not self._stop_requested:
            now_mono = time.monotonic()
            if now_mono - last_watchdog_run >= watchdog_interval:
                try:
                    stats = run_watchdog_cycle(self.deps)
                    log.info("watchdog_cycle_completed", extra=stats)
                except Exception:
                    log.exception("watchdog_cycle_error")
                last_watchdog_run = now_mono

            has_job = self.process_next_job()
            if not has_job and not self._stop_requested:
                time.sleep(self.poll_interval_sec)

        log.info("worker_loop_stopped_gracefully")
