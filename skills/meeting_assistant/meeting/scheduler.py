"""
Meeting Scheduler
Uses APScheduler to automatically start/stop recordings at specified times.
Timezone-aware — defaults to Asia/Kolkata (IST).

Requirements:
  pip install apscheduler pytz --break-system-packages
"""

import asyncio
from typing import Callable, Optional

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


class MeetingScheduler:
    """
    Schedules meeting recordings using APScheduler.
    Supports IST (Asia/Kolkata) by default.
    """

    def __init__(self, timezone: str = "Asia/Kolkata"):
        self.tz = pytz.timezone(timezone)
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self._scheduled: dict = {}  # label → {start, stop} times

    def start_scheduler(self):
        """Start the APScheduler. Call once during bot startup."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info(f"MeetingScheduler started (timezone={self.tz})")

    def schedule(
        self,
        start_hour: int,
        start_minute: int,
        stop_hour: int,
        stop_minute: int,
        on_start: Callable,
        on_stop: Callable,
        label: str = "meeting",
    ) -> str:
        """
        Schedule a meeting recording.

        Args:
            start_hour: Hour to start recording (24h format)
            start_minute: Minute to start recording
            stop_hour: Hour to stop recording (24h format)
            stop_minute: Minute to stop recording
            on_start: Async callable to run at start time
            on_stop: Async callable to run at stop time
            label: Unique identifier for this schedule

        Returns:
            Confirmation string
        """
        # Remove existing schedule with same label if any
        self.cancel(label)

        self.scheduler.add_job(
            on_start,
            CronTrigger(
                hour=start_hour,
                minute=start_minute,
                timezone=self.tz,
            ),
            id=f"{label}_start",
            replace_existing=True,
            misfire_grace_time=60,
        )

        self.scheduler.add_job(
            on_stop,
            CronTrigger(
                hour=stop_hour,
                minute=stop_minute,
                timezone=self.tz,
            ),
            id=f"{label}_stop",
            replace_existing=True,
            misfire_grace_time=60,
        )

        self._scheduled[label] = {
            "start": f"{start_hour:02d}:{start_minute:02d}",
            "stop": f"{stop_hour:02d}:{stop_minute:02d}",
        }

        msg = (
            f"Meeting scheduled: {start_hour:02d}:{start_minute:02d} → "
            f"{stop_hour:02d}:{stop_minute:02d} IST"
        )
        logger.info(msg)
        return msg

    def cancel(self, label: str = "meeting") -> bool:
        """Cancel a scheduled meeting. Returns True if found and cancelled."""
        cancelled = False
        for suffix in ["_start", "_stop"]:
            job_id = f"{label}{suffix}"
            try:
                self.scheduler.remove_job(job_id)
                cancelled = True
            except Exception:
                pass
        if cancelled:
            self._scheduled.pop(label, None)
            logger.info(f"Meeting schedule '{label}' cancelled")
        return cancelled

    def list_schedules(self) -> str:
        """Return a readable list of all scheduled meetings."""
        if not self._scheduled:
            return "No meetings scheduled."
        lines = ["📅 Scheduled meetings:"]
        for label, times in self._scheduled.items():
            lines.append(f"  • {label}: {times['start']} → {times['stop']} IST")
        return "\n".join(lines)

    def get_status(self) -> str:
        return self.list_schedules()

    def shutdown(self):
        """Gracefully shut down the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("MeetingScheduler stopped")
