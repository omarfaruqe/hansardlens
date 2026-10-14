import datetime as dt
from pathlib import Path

import pytest
from django.http import QueryDict

from debates import search
from debates.loader import store
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


@pytest.fixture
def sitting():
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


def run(**kwargs):
    params = search.SearchParams(**kwargs)
    return list(search.ordered(search.filtered(params), params.sort)), params


def texts(rows, lang="en"):
    return [getattr(r, f"text_{lang}") for r in rows]


def test_english_stemming(sitting):
    rows, _ = run(q="bridges")
    assert texts(rows) == ["Mr. Speaker, the bridge in my riding opened last week."]


def test_french_is_accent_insensitive(sitting):
    with_accent, _ = run(q="président", lang="fr")
    without, _ = run(q="president", lang="fr")
    assert with_accent and len(with_accent) == len(without)


def test_phrase_and_exclusion(sitting):
    assert len(run(q='"rents keep rising"')[0]) == 1
    assert len(run(q='"rising rents keep"')[0]) == 0
    assert len(run(q="rents -rising")[0]) == 1  # only "When will rents fall?"


def test_procedural_text_is_not_searched(sitting):
    assert run(q="suspended")[0] == []


def test_filters(sitting):
    assert {r.intervention.party for r in run(q="speaker", party="BQ")[0]} == {"BQ"}
    assert run(q="speaker", person="sam okafor")[0][0].intervention.house_id == "1003"
    assert all(
        r.intervention.rubric == "OralQuestionPeriod"
        for r in run(q="speaker", rubric="OralQuestionPeriod")[0]
    )
    assert run(q="speaker", date_from=dt.date(2023, 1, 1))[0] == []
    assert run(q="speaker", parliament=45)[0] == []


def test_sort_oldest_follows_speech_order(sitting):
    rows, _ = run(q="speaker", sort="oldest")
    seqs = [r.intervention.sequence for r in rows]
    assert seqs == sorted(seqs)


def test_headlines_are_escaped_and_marked(sitting):
    from debates.models import Paragraph

    p = Paragraph.objects.get(intervention__house_id="1002")
    p.text_en = "Rents <script>alert(1)</script> keep rising."
    p.save()
    params = search.SearchParams(q="rents")
    ids = list(search.ordered(search.filtered(params), "relevance").values_list("id", flat=True))
    html = " ".join(r.snippet_html for r in search.page_results(ids, params))
    # PostgreSQL's highlighter drops tags, and our escaping is a second layer
    assert "<script" not in html
    assert "<mark>Rents</mark>" in html


def test_highlight_escapes_before_marking():
    raw = f"a < b & {search._START}c{search._STOP} <i>"
    assert search._safe_highlight(raw) == "a &lt; b &amp; <mark>c</mark> &lt;i&gt;"


def test_party_counts(sitting):
    counts = dict(search.party_counts(search.filtered(search.SearchParams(q="speaker"))))
    assert counts["CPC"] == 1 and counts["BQ"] == 1


def test_params_from_query_dict():
    p = search.SearchParams.from_query_dict(
        QueryDict(
            "q=  carbon   tax &lang=xx&sort=bogus&parliament=44"
            "&date_from=2024-05-01&date_to=2024-01-01"
        ),
        default_lang="fr",
    )
    assert p.q == "carbon tax" and p.lang == "fr" and p.sort == "relevance"
    assert p.parliament == 44
    assert p.date_from == dt.date(2024, 1, 1) and p.date_to == dt.date(2024, 5, 1)


def test_bad_date_is_reported():
    p = search.SearchParams.from_query_dict(QueryDict("q=x&date_from=31/03/2024"))
    assert p.errors
