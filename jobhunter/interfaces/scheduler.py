"""In-process scheduler driver (the API runs locally, so no cron needed): daily collect+match at the
time set in Settings, due-reminder checks, and Gmail reply sync."""
import logging

from ..application import mail, notifications, runs
from ..application.tasks import daily
from ..domain.errors import RunBusy

log = logging.getLogger("jobhunter.scheduler")


class AppScheduler:
    def __init__(self, container):
        from apscheduler.schedulers.background import BackgroundScheduler
        self.container = container
        self._s = BackgroundScheduler()

    def _daily(self):
        with self.container.session() as ctx:
            try:
                runs.run_now(ctx, "daily", daily, trigger="schedule", echo=False)
            except RunBusy as e:
                log.info("daily skipped: %s", e)
            except Exception:  # noqa: BLE001
                log.exception("daily run failed")

    def _reminders(self):
        with self.container.session() as ctx:
            notifications.due_reminders(ctx)

    def _gmail(self):
        with self.container.session() as ctx:
            try:
                mail.sync_replies(ctx, log=log.info)
            except Exception:  # noqa: BLE001
                log.exception("gmail sync failed")

    def start(self):
        self._s.add_job(self._reminders, "interval", minutes=15, id="reminders")
        self._s.add_job(self._gmail, "interval", minutes=30, id="gmail")
        self._s.start()
        self.reschedule()
        return self

    def reschedule(self):
        """(Re)apply the daily job from settings.schedule = {"enabled", "time": "HH:MM"}."""
        with self.container.session() as ctx:
            s = ctx.repos.settings.get()["schedule"] or {}
        if self._s.get_job("daily"):
            self._s.remove_job("daily")
        if s.get("enabled", True):
            hour, _, minute = (s.get("time") or "07:30").partition(":")
            self._s.add_job(self._daily, "cron", hour=int(hour), minute=int(minute or 0), id="daily",
                            misfire_grace_time=3600, coalesce=True)

    def next_run(self):
        job = self._s.get_job("daily")
        return job.next_run_time.isoformat() if job and job.next_run_time else None

    def shutdown(self):
        self._s.shutdown(wait=False)
