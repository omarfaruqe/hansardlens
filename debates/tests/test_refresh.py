import pytest
from django.core.management import CommandError, call_command

from debates.models import Sitting, TermShift
from debates.tests.test_commands import FakeHouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def house(monkeypatch, settings, tmp_path):
    settings.DATA_DIR = tmp_path

    def install(available):
        """available: {(parliament, session): [numbers]}"""
        fakes = {}

        def fetch(url, user_agent, timeout=60):
            ps = url.split("/House/")[1].split("/")[0]  # e.g. "441"
            key = (int(ps[:2]), int(ps[2:]))
            fake = fakes.setdefault(key, FakeHouse(available.get(key, [])))
            xml = fake(url, user_agent, timeout).decode("utf-8")
            # the fixture is labelled 44-1; label it with the session asked for
            xml = xml.replace('"ParliamentNumber">44<', f'"ParliamentNumber">{key[0]}<')
            xml = xml.replace('"SessionNumber">1<', f'"SessionNumber">{key[1]}<')
            return xml.encode("utf-8")

        monkeypatch.setattr("debates.loader.fetch", fetch)
        return fakes

    return install


def numbers(p, s):
    return sorted(Sitting.objects.filter(parliament=p, session=s).values_list("number", flat=True))


def test_empty_database_starts_at_44_1(house):
    house({(44, 1): [1, 2]})
    call_command("refresh_data", sleep=0, skip_analysis=True)
    assert numbers(44, 1) == [1, 2]


def test_continues_then_follows_new_session(house):
    house({(44, 1): [1], (44, 2): [1, 2]})
    call_command("refresh_data", sleep=0, skip_analysis=True)
    call_command("refresh_data", sleep=0, skip_analysis=True)
    assert numbers(44, 2) == [1, 2]


def test_follows_new_parliament(house):
    house({(44, 1): [1], (45, 1): [1, 2, 3]})
    call_command("refresh_data", sleep=0, skip_analysis=True)
    call_command("refresh_data", sleep=0, skip_analysis=True)
    assert numbers(45, 1) == [1, 2, 3]


def test_nothing_new_is_quiet(house, capsys):
    house({(44, 1): [1]})
    call_command("refresh_data", sleep=0, skip_analysis=True)
    call_command("refresh_data", sleep=0, skip_analysis=True)
    assert "0 new sitting(s)" in capsys.readouterr().out


def test_term_shifts_run_after_new_sittings(house, monkeypatch):
    house({(44, 1): [1]})
    ran = []
    real = call_command

    def spy(name, *args, **kwargs):
        if name in ("build_term_shifts", "build_bills", "build_topics"):
            ran.append(name)
            return None
        return real(name, *args, **kwargs)

    monkeypatch.setattr("debates.management.commands.refresh_data.call_command", spy)
    call_command("refresh_data", sleep=0)
    # no topic model yet -> built
    assert ran == ["build_term_shifts", "build_bills", "build_topics"]
    assert TermShift.objects.count() == 0  # spy stood in for the real command


def test_failed_load_exits_with_error(house, monkeypatch):
    house({(44, 1): [1, 2]})

    def broken(*args, **kwargs):
        import requests

        raise requests.ConnectionError("down")

    monkeypatch.setattr("debates.loader.fetch", broken)
    with pytest.raises(CommandError):
        call_command("refresh_data", sleep=0, skip_analysis=True)
