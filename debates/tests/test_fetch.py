import pytest
import requests

from debates import hansard_xml


class FakeResponse:
    def __init__(self, status, content=b"<Hansard/>"):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(hansard_xml.time, "sleep", lambda s: None)


def scripted(monkeypatch, outcomes):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)

    monkeypatch.setattr(hansard_xml.requests, "get", fake_get)
    return calls


def test_retries_dropped_connection_then_succeeds(monkeypatch, no_sleep):
    calls = scripted(monkeypatch, [requests.ConnectionError("reset"), 503, 200])
    assert hansard_xml.fetch("u", "ua") == b"<Hansard/>"
    assert len(calls) == 3


def test_404_is_not_retried(monkeypatch, no_sleep):
    calls = scripted(monkeypatch, [404, 200])
    with pytest.raises(requests.HTTPError):
        hansard_xml.fetch("u", "ua")
    assert len(calls) == 1


def test_gives_up_after_attempts(monkeypatch, no_sleep):
    calls = scripted(monkeypatch, [requests.Timeout()] * 4)
    with pytest.raises(requests.Timeout):
        hansard_xml.fetch("u", "ua", attempts=4)
    assert len(calls) == 4
