import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest
from django.core.management import CommandError, call_command

from debates.management.commands import run_scheduler as rs

TZ = ZoneInfo("America/Toronto")
AT = dt.time(6, 30)
TUE_SAT = rs.parse_days("tue,wed,thu,fri,sat")
HOUR = dt.timedelta(hours=1)


def t(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ)  # Oct 13, 2026 is a Tuesday


def test_parse_days():
    assert rs.parse_days("mon, Tue,friday") == {0, 1, 4}
    with pytest.raises(ValueError):
        rs.parse_days("funday")


def test_latest_and_next_slot():
    assert rs.latest_slot(t(13, 6, 29), AT, TUE_SAT) == t(10, 6, 30)  # the Saturday before
    assert rs.latest_slot(t(13, 6, 30), AT, TUE_SAT) == t(13, 6, 30)
    assert rs.next_slot(t(17, 7, 0), AT, TUE_SAT) == t(20, 6, 30)  # Sat -> next Tuesday


def test_due_once_per_slot():
    assert rs.is_due(t(14, 6, 31), AT, TUE_SAT, None, None, HOUR)
    assert not rs.is_due(t(14, 9, 0), AT, TUE_SAT, t(14, 6, 31), t(14, 6, 31), HOUR)


def test_catches_up_after_sleep():
    # last ran Tuesday; the Mac slept through Wednesday and Thursday mornings
    assert rs.is_due(t(16, 22, 0), AT, TUE_SAT, t(13, 6, 31), t(13, 6, 31), HOUR)


def test_retries_hourly_after_failure():
    failed_at = t(14, 6, 31)
    assert not rs.is_due(t(14, 7, 0), AT, TUE_SAT, t(13, 6, 31), failed_at, HOUR)
    assert rs.is_due(t(14, 7, 32), AT, TUE_SAT, t(13, 6, 31), failed_at, HOUR)


def test_no_run_on_sunday_or_monday():
    assert not rs.is_due(t(19, 12, 0), AT, TUE_SAT, t(17, 6, 31), t(17, 6, 31), HOUR)


@pytest.mark.django_db
def test_once_runs_and_records_state(settings, tmp_path, monkeypatch):
    settings.DATA_DIR = tmp_path
    calls = []
    monkeypatch.setattr(rs, "call_command", lambda name, **kw: calls.append(name))
    call_command("run_scheduler", once=True, days="mon,tue,wed,thu,fri,sat,sun", at="00:00")
    state = json.loads((tmp_path / "scheduler_state.json").read_text())
    assert calls == ["refresh_data"] and state["status"] == "ok" and state["last_success"]
    call_command("run_scheduler", once=True, days="mon,tue,wed,thu,fri,sat,sun", at="00:00")
    assert calls == ["refresh_data"]  # already done for today's slot


@pytest.mark.django_db
def test_failure_is_recorded_and_scheduler_survives(settings, tmp_path, monkeypatch):
    settings.DATA_DIR = tmp_path

    def boom(name, **kw):
        raise CommandError("2 sitting(s) failed to load")

    monkeypatch.setattr(rs, "call_command", boom)
    call_command("run_scheduler", once=True, days="mon,tue,wed,thu,fri,sat,sun", at="00:00")
    state = json.loads((tmp_path / "scheduler_state.json").read_text())
    assert state["status"] == "failed" and "failed to load" in state["last_error"]


def test_bad_arguments():
    with pytest.raises(CommandError):
        call_command("run_scheduler", once=True, days="someday")


@pytest.mark.django_db
def test_health_reports_last_refresh(client, settings, tmp_path):
    settings.DATA_DIR = tmp_path
    (tmp_path / "scheduler_state.json").write_text(
        json.dumps({"status": "ok", "last_success": "2026-10-14T06:30:00-04:00"})
    )
    body = client.get("/health/").json()
    assert body["refresh"]["status"] == "ok"
    assert body["refresh"]["last_success"].startswith("2026-10-14")


class FakePost:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, data=b"", timeout=None):
        if self.fail:
            import requests

            raise requests.ConnectionError("monitoring down")
        self.calls.append((url, data.decode()))


@pytest.mark.django_db
def test_healthcheck_pings_start_and_success(settings, tmp_path, monkeypatch):
    settings.DATA_DIR = tmp_path
    fake = FakePost()
    monkeypatch.setenv("REFRESH_HEALTHCHECK_URL", "https://hc.example/abc/")
    monkeypatch.setattr(rs.requests, "post", fake)
    monkeypatch.setattr(rs, "call_command", lambda name, **kw: None)
    call_command("run_scheduler", once=True, days="mon,tue,wed,thu,fri,sat,sun", at="00:00")
    assert [u for u, _ in fake.calls] == ["https://hc.example/abc/start", "https://hc.example/abc"]


@pytest.mark.django_db
def test_healthcheck_reports_failure_with_the_error(settings, tmp_path, monkeypatch):
    settings.DATA_DIR = tmp_path
    fake = FakePost()
    monkeypatch.setenv("REFRESH_HEALTHCHECK_URL", "https://hc.example/abc")

    def boom(name, **kw):
        raise CommandError("3 sitting(s) failed to load")

    monkeypatch.setattr(rs.requests, "post", fake)
    monkeypatch.setattr(rs, "call_command", boom)
    call_command("run_scheduler", once=True, days="mon,tue,wed,thu,fri,sat,sun", at="00:00")
    url, body = fake.calls[-1]
    assert url == "https://hc.example/abc/fail" and "failed to load" in body


def test_healthcheck_is_optional_and_never_raises(monkeypatch):
    calls = FakePost()
    monkeypatch.setattr(rs.requests, "post", calls)
    monkeypatch.delenv("REFRESH_HEALTHCHECK_URL", raising=False)
    rs.ping_healthcheck("/start")
    assert calls.calls == []
    monkeypatch.setenv("REFRESH_HEALTHCHECK_URL", "https://hc.example/abc")
    monkeypatch.setattr(rs.requests, "post", FakePost(fail=True))
    rs.ping_healthcheck("")  # monitoring outage must not break the refresh


@pytest.mark.django_db
def test_health_reports_latest_backup(client, settings, tmp_path):
    settings.DATA_DIR = tmp_path
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "hansardlens-2026-10-17.dump").write_bytes(b"x")
    (backups / "hansardlens-2026-10-18.dump").write_bytes(b"xy")
    (backups / "hansardlens-2026-10-19.dump.partial").write_bytes(b"incomplete")
    backup = client.get("/health/").json()["backup"]
    assert backup["latest"] == "hansardlens-2026-10-18.dump"
    assert backup["count"] == 2 and backup["age_hours"] is not None


@pytest.mark.django_db
def test_health_without_backups(client, settings, tmp_path):
    settings.DATA_DIR = tmp_path
    assert client.get("/health/").json()["backup"] == {"latest": None, "count": 0}
