"""Daily run windows and intervals anchored to each window's opening."""
from datetime import datetime, time, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo

from apscheduler.triggers.base import BaseTrigger


def in_run_window(job, now: datetime) -> bool:
    if not job.window_start:
        return True
    local_time = now.astimezone(ZoneInfo(job.timezone)).strftime("%H:%M")
    start, end = job.window_start, job.window_end
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


class WindowIntervalTrigger(BaseTrigger):
    """Run at opening, then every interval; end is exclusive. Supports overnight."""

    def __init__(self, minutes: int, start: str, end: str, zone: str):
        self.interval = timedelta(minutes=minutes)
        self.start, self.end = time.fromisoformat(start), time.fromisoformat(end)
        self.zone = ZoneInfo(zone)

    def get_next_fire_time(self, previous_fire_time, now):
        earliest = max(now, previous_fire_time + timedelta(microseconds=1)) if previous_fire_time else now
        first_date = earliest.astimezone(self.zone).date() - timedelta(days=1)
        for offset in range(4):
            day = first_date + timedelta(days=offset)
            opening = datetime.combine(day, self.start, self.zone).astimezone(timezone.utc)
            end_day = day + timedelta(days=1) if self.end < self.start else day
            closing = datetime.combine(end_day, self.end, self.zone).astimezone(timezone.utc)
            steps = max(0, ceil((earliest - opening) / self.interval))
            candidate = opening + steps * self.interval
            if candidate < closing:
                return candidate
        return None
