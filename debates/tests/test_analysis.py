import datetime as dt
from pathlib import Path

import pytest
from django.core.cache import cache

from debates import analysis
from debates.loader import store
from debates.models import Paragraph, Sitting
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


def load(number=50, date=None):
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    m = merge(en, fr)
    m.number = number
    if date:
        m.date = date
    return store(m).sitting


@pytest.fixture(autouse=True)
def small_thresholds(monkeypatch):
    """The fixture sitting is tiny; let every month count."""
    monkeypatch.setattr(analysis, "MIN_MONTH_PARAGRAPHS", 1)
    monkeypatch.setattr(analysis, "MIN_MONTH_WORDS", 1)
    cache.clear()


def test_month_range_crosses_years():
    months = analysis.month_range(dt.date(2021, 11, 22), dt.date(2022, 2, 3))
    assert months == [
        dt.date(2021, 11, 1),
        dt.date(2021, 12, 1),
        dt.date(2022, 1, 1),
        dt.date(2022, 2, 1),
    ]


def test_words_en_generated_column():
    load()
    p = Paragraph.objects.get(intervention__house_id="1001", sequence=1)
    assert p.words_en == len(p.text_en.split())


def test_term_trends_rates_and_gaps():
    load(50, dt.date(2022, 3, 31))
    load(51, dt.date(2022, 5, 2))  # April has no sitting
    data = analysis.term_trends(["bridge", "rents"])
    assert data["months"] == ["2022-03", "2022-04", "2022-05"]
    assert data["denominators"][1] is None
    bridge = data["series"][0]
    # member speech paragraphs per sitting: 2001, 2002, 2003, 2004, 2006 -> 5
    assert data["denominators"][0] == 5
    assert bridge["counts"] == [1, None, 1]
    assert bridge["values"] == [200.0, None, 200.0]
    assert bridge["total_hits"] == 2


def test_term_trends_party_filter_changes_denominator():
    load()
    data = analysis.term_trends(["rents"], party="BQ")
    assert data["denominators"] == [2]  # Martel's two paragraphs
    assert data["series"][0]["values"] == [1000.0]


def test_thin_months_become_gaps(monkeypatch):
    load()
    monkeypatch.setattr(analysis, "MIN_MONTH_PARAGRAPHS", 1000)
    cache.clear()
    data = analysis.term_trends(["bridge"])
    assert data["series"][0]["values"] == [None]
    assert data["denominators"] == [5]  # still reported, so the page can say why


def test_empty_terms():
    assert analysis.term_trends(["", "  "])["series"] == []


def test_language_share_uses_english_yardstick():
    load()
    spoken = Paragraph.objects.filter(
        kind="speech", intervention__is_chair=False, floor_language__in=["en", "fr"]
    )
    fr = sum(p.words_en for p in spoken if p.floor_language == "fr")
    total = sum(p.words_en for p in spoken)
    overall = analysis.language_overall()
    assert (overall["fr"], overall["total"]) == (fr, total)
    assert overall["share"] == round(100 * fr / total, 1)


def test_language_by_party_and_member():
    load()
    parties = {r["party"]: r["share"] for r in analysis.language_by_party(min_words=1)}
    # Martel: "Mr. Speaker, rents keep rising." follows [Translation] (spoken in French,
    # 5 words); "When will rents fall?" follows [English] (4 words) -> 5/9
    assert parties["BQ"] == round(100 * 5 / 9, 1)
    assert parties["CPC"] < 100.0
    members = analysis.language_by_member(min_words=1, sort="name")
    assert [m["name"] for m in members] == sorted(m["name"] for m in members)
    assert "Pat Example" not in [m["name"] for m in members]  # chair excluded


def test_cache_is_invalidated_by_a_new_load():
    load()
    first = analysis.language_overall()["total"]
    Sitting.objects.update(loaded_at=dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
    load(51)
    assert analysis.language_overall()["total"] == 2 * first
