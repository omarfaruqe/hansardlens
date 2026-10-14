from pathlib import Path

import pytest

from debates.loader import store
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


@pytest.fixture
def sitting():
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


def test_health_reports_database_ok(client):
    response = client.get("/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["vendor"] == "postgresql" and body["version"] == "1.0.0"


def test_home_empty_database(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"No debates are loaded yet" in response.content


def test_home_with_data(client, sitting):
    response = client.get("/")
    assert b"1 sittings" in response.content or b"sittings so far" in response.content
    assert sitting.get_absolute_url().encode() in response.content


def test_home_in_french(client):
    response = client.get("/", HTTP_ACCEPT_LANGUAGE="fr")
    assert b'lang="fr"' in response.content


def test_search_page_without_query(client):
    response = client.get("/search/")
    assert response.status_code == 200
    assert b"Type a word or phrase" in response.content


def test_search_results_link_to_speech_and_paragraph(client, sitting):
    response = client.get("/search/", {"q": "bridge"})
    html = response.content.decode()
    assert "1 matching paragraph" in html
    assert "/speeches/1001/?text=en#p-1" in html
    assert "<mark>bridge</mark>" in html


def test_search_french_marks_original_language(client, sitting):
    html = client.get("/search/", {"q": "loyers", "text": "fr"}).content.decode()
    assert "matching paragraphs" in html
    assert "<mark>loyers</mark>" in html


def test_search_no_results(client, sitting):
    html = client.get("/search/", {"q": "zebra"}).content.decode()
    assert "No paragraphs match" in html


def test_search_pagination_keeps_filters(client, sitting, monkeypatch):
    monkeypatch.setattr("debates.views.PAGE_SIZE", 1)
    html = client.get("/search/", {"q": "speaker", "party": ""}).content.decode()
    assert "Page 1 of" in html and "q=speaker" in html and "page=2" in html


def test_speech_page_shows_both_languages(client, sitting):
    html = client.get("/speeches/1001/").content.decode()
    assert "Jane Alder" in html
    assert "the bridge in my riding" in html
    assert "le pont de ma circonscription" in html
    assert "Translated from French" in html  # second paragraph was spoken in French
    assert "/speeches/1002/" in html  # next speech


def test_speech_page_in_french(client, sitting):
    html = client.get("/speeches/1001/", {"lang": "fr"}).content.decode()
    assert "Les ponts du port" in html
    assert "Translated from English" in html or "Traduit" in html


def test_unknown_speech_is_404(client):
    assert client.get("/speeches/999999/").status_code == 404


def test_sitting_pages(client, sitting):
    assert client.get("/sittings/").status_code == 200
    html = client.get(sitting.get_absolute_url()).content.decode()
    assert "Statements by Members" in html and "Harbour Bridges" in html
    assert 'id="iv-2"' in html
    assert client.get("/sittings/44-1/999/").status_code == 404


@pytest.fixture
def no_thresholds(monkeypatch):
    from django.core.cache import cache

    from debates import analysis

    monkeypatch.setattr(analysis, "MIN_MONTH_PARAGRAPHS", 1)
    monkeypatch.setattr(analysis, "MIN_MONTH_WORDS", 1)
    monkeypatch.setattr(analysis, "MIN_PARTY_WORDS", 1)
    monkeypatch.setattr(analysis, "MIN_MEMBER_WORDS", 1)
    cache.clear()


def test_trends_page_empty_shows_examples(client):
    html = client.get("/trends/").content.decode()
    assert "Enter at least one term" in html and "t1=housing" in html


def test_trends_page_with_terms(client, sitting, no_thresholds):
    html = client.get("/trends/", {"t1": "bridge", "t2": "rents"}).content.decode()
    assert 'id="trend-data"' in html and "linechart.js" in html
    assert "Show the numbers as a table" in html
    assert "<td>2022-03</td>" in html


def test_trends_page_escapes_terms(client, sitting, no_thresholds):
    html = client.get("/trends/", {"t1": "<img src=x>"}).content.decode()
    assert "<img src=x>" not in html


def test_trends_page_no_hits(client, sitting, no_thresholds):
    html = client.get("/trends/", {"t1": "zebra"}).content.decode()
    assert "None of these terms appear" in html


def test_language_page(client, sitting, no_thresholds):
    html = client.get("/language/").content.decode()
    assert "of what members said was spoken in French" in html
    assert 'id="lang-month"' in html
    assert "Luc Martel" in html and "Jane Alder" in html
    assert "Pat Example" not in html.split("By member")[1]  # chair excluded


def test_language_page_empty(client):
    assert b"No debates are loaded yet" in client.get("/language/").content


def test_lang_parameter_sets_interface_language_and_cookie(client):
    response = client.get("/", {"lang": "fr"})
    assert b'<html lang="fr">' in response.content
    assert response.cookies["hansardlens_language"].value == "fr"
    # remembered on the next request without the parameter
    assert b'<html lang="fr">' in client.get("/search/").content


def test_text_parameter_is_independent_of_interface(client, sitting):
    html = client.get("/speeches/1001/", {"text": "fr"}).content.decode()
    assert '<html lang="en">' in html
    assert "Les ponts du port" in html


def test_switch_language_link_keeps_query(client, sitting):
    html = client.get("/search/", {"q": "bridge", "text": "en"}).content.decode()
    assert "/search/?q=bridge&amp;lang=fr" in html


def test_robots_and_404(client):
    assert b"Disallow: /api/" in client.get("/robots.txt").content
    response = client.get("/no/such/page/")
    assert response.status_code == 404 and b"Page not found" in response.content


def test_template_helpers_in_both_languages():
    import datetime as dt

    from django.utils import translation

    from debates.templatetags.hansard import ldate, ordinal_parliament, party

    with translation.override("en"):
        assert ordinal_parliament(42) == "42nd Parliament"
        assert ldate(dt.date(2024, 3, 1), "long") == "Friday, March 1, 2024"
        assert party("CPC") == "CPC"
    with translation.override("fr"):
        assert ordinal_parliament(44) == "44<sup>e</sup> législature"
        assert ldate(dt.date(2024, 3, 1), "long") == "vendredi 1er mars 2024"
        assert ldate(dt.date(2024, 3, 11), "date") == "11 mars 2024"
        assert ldate(dt.date(2024, 3, 1), "date") == "1er mars 2024"
        assert party("CPC") == "PCC" and party("NDP") == "NPD" and party("BQ") == "BQ"


def test_french_interface_strings(client, sitting):
    html = client.get("/search/", {"q": "bridge", "text": "en", "lang": "fr"}).content.decode()
    assert "1 paragraphe correspondant" in html
    assert "Appliquer les filtres" in html
    assert "<sup>e</sup> législature" in html and "&lt;sup&gt;" not in html
