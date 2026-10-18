"""Run a refresh command on a timetable, inside the Docker stack.

    python manage.py run_scheduler                          # refresh_data, Tue-Sat 06:30
    python manage.py run_scheduler --at 07:00 --days mon,tue,wed,thu,fri
    python manage.py run_scheduler --once                   # run if due, then exit

Catches up: if the computer was asleep or off at the scheduled time, the run happens
as soon as the scheduler is running again. After a failure it retries every hour until
it succeeds or the next scheduled time comes. Status is written to
data/scheduler_state.json and shown by /health/.
"""

from __future__ import annotations

import datetime as dt
import json
import signal
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def state_path() -> Path:
    data_dir = getattr(settings, "DATA_DIR", Path(settings.BASE_DIR) / "data")
    return Path(data_dir) / "scheduler_state.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)  # atomic, so /health/ never reads half a file


def parse_days(text: str) -> set[int]:
    days = {d.strip().lower()[:3] for d in text.split(",") if d.strip()}
    unknown = days - set(DAYS)
    if unknown or not days:
        raise ValueError(f"Days must be from {','.join(DAYS)}")
    return {DAYS.index(d) for d in days}


def latest_slot(now: dt.datetime, at: dt.time, days: set[int]) -> dt.datetime | None:
    """Most recent scheduled moment at or before `now` (searching back one week)."""
    for back in range(8):
        day = (now - dt.timedelta(days=back)).date()
        slot = dt.datetime.combine(day, at, tzinfo=now.tzinfo)
        if day.weekday() in days and slot <= now:
            return slot
    return None


def next_slot(now: dt.datetime, at: dt.time, days: set[int]) -> dt.datetime:
    for ahead in range(8):
        day = (now + dt.timedelta(days=ahead)).date()
        slot = dt.datetime.combine(day, at, tzinfo=now.tzinfo)
        if day.weekday() in days and slot > now:
            return slot
    raise ValueError("No scheduled day")


def is_due(
    now: dt.datetime,
    at: dt.time,
    days: set[int],
    last_success: dt.datetime | None,
    last_attempt: dt.datetime | None,
    retry: dt.timedelta,
) -> bool:
    slot = latest_slot(now, at, days)
    if slot is None or (last_success and last_success >= slot):
        return False
    return last_attempt is None or last_attempt < slot or now - last_attempt >= retry


def _parse_time(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


class Command(BaseCommand):
    help = "Run a refresh command on a schedule (for the scheduler service)."

    def add_arguments(self, parser):
        parser.add_argument("--command", default="refresh_data")
        parser.add_argument("--at", default="06:30", help="Local time, HH:MM (default 06:30).")
        parser.add_argument("--days", default="tue,wed,thu,fri,sat")
        parser.add_argument("--tz", default=settings.TIME_ZONE)
        parser.add_argument("--retry-minutes", type=int, default=60)
        parser.add_argument("--once", action="store_true", help="Run if due, then exit.")

    def log(self, message: str) -> None:
        stamp = dt.datetime.now(self.tz).strftime("%Y-%m-%d %H:%M:%S")
        self.stdout.write(f"[scheduler {stamp}] {message}")
        self.stdout.flush()

    def handle(self, *args, **o):
        try:
            self.tz = ZoneInfo(o["tz"])
            at = dt.time.fromisoformat(o["at"])
            days = parse_days(o["days"])
        except (ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        retry = dt.timedelta(minutes=o["retry_minutes"])
        # docker stop sends SIGTERM; Python ignores it as PID 1 unless handled.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

        now = dt.datetime.now(self.tz)
        self.log(
            f"running '{o['command']}' at {o['at']} on {o['days']} ({o['tz']}); "
            f"next scheduled {next_slot(now, at, days):%a %Y-%m-%d %H:%M}"
        )
        while True:
            now = dt.datetime.now(self.tz)
            state = load_state()
            if is_due(
                now,
                at,
                days,
                _parse_time(state.get("last_success")),
                _parse_time(state.get("last_attempt")),
                retry,
            ):
                self.run(o["command"], state)
            if o["once"]:
                return
            time.sleep(60)  # checking every minute also notices waking from sleep

    def run(self, command: str, state: dict) -> None:
        started = dt.datetime.now(self.tz)
        state.update(command=command, last_attempt=started.isoformat(), status="running")
        save_state(state)
        self.log(f"starting {command}")
        close_old_connections()
        try:
            call_command(command, stdout=self.stdout, stderr=self.stderr)
        except Exception as exc:  # keep the scheduler alive whatever happens
            state.update(status="failed", last_error=f"{type(exc).__name__}: {exc}"[:500])
            self.log(f"{command} failed: {exc}; will retry")
        else:
            state.update(status="ok", last_success=started.isoformat(), last_error="")
            self.log(f"{command} finished in {(dt.datetime.now(self.tz) - started).seconds} s")
        finally:
            close_old_connections()
            state["finished"] = dt.datetime.now(self.tz).isoformat()
            save_state(state)
