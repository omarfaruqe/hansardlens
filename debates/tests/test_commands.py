from pathlib import Path

import pytest
import requests
from django.core.management import call_command

from debates.models import Sitting

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


def fixture_for(number, lang, parliament=44, session=1):
    """Fixture XML re-numbered as sitting `number` of `parliament`-`session`."""
    xml = (FIXTURES / f"sitting_{lang}.xml").read_text(encoding="utf-8")
    xml = xml.replace('"MetaNumberNumber">050<', f'"MetaNumberNumber">{number:03d}<')
    xml = xml.replace('"ParliamentNumber">44<', f'"ParliamentNumber">{parliament}<')
    xml = xml.replace('"SessionNumber">1<', f'"SessionNumber">{session}<')
    return xml.encode("utf-8")


class FakeHouse:
    """Stands in for ourcommons.ca: serves sittings in `available`, 404 otherwise."""

    def __init__(self, available, french=True):
        self.available, self.french, self.calls = set(available), french, []

    def __call__(self, url, user_agent, timeout=60):
        self.calls.append(url)
        number = int(url.rsplit("/HAN", 1)[1][:3])
        lang = "fr" if url.endswith("-F.XML") else "en"
        if number not in self.available or (lang == "fr" and not self.french):
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        house = url.split("/Content/House/", 1)[1][:3]  # "441" -> 44, 1
        return fixture_for(number, lang, int(house[:2]), int(house[2:]))


@pytest.fixture
def house(monkeypatch, settings, tmp_path):
    settings.DATA_DIR = tmp_path

    def install(available, french=True):
        fake = FakeHouse(available, french)
        monkeypatch.setattr("debates.loader.fetch", fake)
        return fake

    return install


def test_explicit_range(house):
    house([1, 2, 3])
    call_command("load_hansard", parliament=44, session=1, start=1, end=3, sleep=0)
    assert list(Sitting.objects.values_list("number", flat=True)) == [1, 2, 3]


def test_incremental_continues_after_last_and_stops_on_misses(house, capsys):
    house([1, 2, 3, 4, 5])
    call_command("load_hansard", parliament=44, session=1, start=1, end=2, sleep=0)
    fake = house([1, 2, 3, 4, 5])
    call_command("load_hansard", parliament=44, session=1, sleep=0, max_misses=2)
    assert Sitting.objects.count() == 5
    numbers_fetched = sorted({int(u.rsplit("/HAN", 1)[1][:3]) for u in fake.calls})
    assert numbers_fetched == [3, 4, 5, 6, 7]  # 6 and 7 are the two misses
    assert "5 sitting(s)" not in capsys.readouterr().out  # second run loaded 3


def test_cache_avoids_second_download(house):
    house([1])
    call_command("load_hansard", parliament=44, session=1, start=1, end=1, sleep=0)
    fake = house([1])
    call_command("load_hansard", parliament=44, session=1, start=1, end=1, sleep=0)
    assert fake.calls == []


def test_missing_french_is_recorded(house):
    house([1], french=False)
    call_command("load_hansard", parliament=44, session=1, start=1, end=1, sleep=0)
    sitting = Sitting.objects.get()
    assert not sitting.has_french
    assert "French version not available" in sitting.issues


def test_quality_report(house, settings, capsys):
    house([1, 3])
    call_command("load_hansard", parliament=44, session=1, start=1, end=3, sleep=0)
    call_command("hansard_quality")
    out = capsys.readouterr().out
    assert "missing numbers : 2" in out
    assert "French share" in out
    assert list((Path(settings.DATA_DIR) / "reports").glob("quality_*.txt"))


def test_open_ended_load_stops_when_network_is_down(house, monkeypatch, capsys):
    def broken(url, user_agent, timeout=60):
        raise requests.ConnectionError("down")

    house([1])
    monkeypatch.setattr("debates.loader.fetch", broken)
    call_command("load_hansard", parliament=44, session=1, sleep=0, max_misses=3)
    assert "several failures in a row" in capsys.readouterr().err


def test_no_cache_keeps_nothing_in_data_raw(house, settings):
    house([1, 2])
    call_command("load_hansard", parliament=44, session=1, start=1, end=2, sleep=0, no_cache=True)
    assert Sitting.objects.count() == 2
    assert not list((Path(settings.DATA_DIR) / "raw").glob("*.xml"))


def test_earlier_parliament_loads_beside_later_ones(house):
    house([1, 2])
    call_command("load_hansard", parliament=45, session=1, start=1, end=1, sleep=0)
    call_command("load_hansard", parliament=43, session=2, start=1, end=2, sleep=0)
    assert sorted(Sitting.objects.values_list("parliament", "session", "number")) == [
        (43, 2, 1),
        (43, 2, 2),
        (45, 1, 1),
    ]
