from pathlib import Path

import pytest
from django.core.cache import cache

from debates.loader import store
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


@pytest.fixture
def sitting(monkeypatch):
    from debates import analysis

    monkeypatch.setattr(analysis, "MIN_MONTH_PARAGRAPHS", 1)
    monkeypatch.setattr(analysis, "MIN_MONTH_WORDS", 1)
    cache.clear()
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


def test_schema_and_docs(client):
    schema = client.get("/api/schema/")
    assert schema.status_code == 200
    body = schema.content.decode()
    for path in ("/api/v1/search/", "/api/v1/speeches/{house_id}/", "/api/v1/trends/"):
        assert path in body
    assert client.get("/api/docs/").status_code == 200


def test_sittings_list_and_filters(client, sitting):
    data = client.get("/api/v1/sittings/").json()
    assert data["count"] == 1
    row = data["results"][0]
    assert row["number"] == 50 and row["interventions"] == 8
    assert row["url"] == "/sittings/44-1/50/"
    assert client.get("/api/v1/sittings/", {"parliament": 45}).json()["count"] == 0
    assert client.get("/api/v1/sittings/", {"date_from": "2023-01-01"}).json()["count"] == 0
    assert client.get("/api/v1/sittings/", {"date_from": "bad"}).status_code == 400


def test_sitting_detail(client, sitting):
    data = client.get("/api/v1/sittings/44-1/50/").json()
    assert [i["sequence"] for i in data["items"]] == list(range(1, 9))
    alder = data["items"][1]
    assert alder["speaker"]["name"] == "Jane Alder" and alder["speaker"]["party"] == "CPC"
    assert client.get("/api/v1/sittings/44-1/99/").status_code == 404


def test_speech_detail_has_both_languages(client, sitting):
    data = client.get("/api/v1/speeches/1001/").json()
    assert data["sitting"]["date"] == "2022-03-31"
    paras = data["paragraphs"]
    assert paras[0]["text_fr"].startswith("Monsieur le Président")
    assert [p["floor_language"] for p in paras] == ["en", "fr"]
    assert client.get("/api/v1/speeches/nope/").status_code == 404


def test_people(client, sitting):
    data = client.get("/api/v1/people/", {"party": "BQ"}).json()
    assert [p["name"] for p in data["results"]] == ["Luc Martel"]
    assert client.get("/api/v1/people/", {"name": "ald"}).json()["count"] == 1
    assert data["results"][0]["url"] == "/members/luc-martel/"


def test_person_detail(client, sitting):
    data = client.get("/api/v1/people/sam-okafor/").json()
    assert data["name"] == "Sam Okafor" and data["slug"] == "sam-okafor"
    assert data["speeches"] >= 1 and set(data["by_kind"]) == {
        "debate",
        "questions",
        "answers",
        "statements",
    }
    assert data["roles"][0]["value"] == "Secretary of State (Housing)"
    assert data["by_month"]["months"] == ["2022-03"]
    assert data["topics"] is None  # no topic model in this test database
    assert client.get("/api/v1/people/nobody/").status_code == 404


def test_search(client, sitting):
    data = client.get("/api/v1/search/", {"q": "bridge"}).json()
    assert data["count"] == 1
    hit = data["results"][0]
    assert hit["speech"] == "1001" and "<mark>bridge</mark>" in hit["snippet_html"]
    assert hit["url"].endswith("?text=en#p-1")
    fr = client.get("/api/v1/search/", {"q": "loyers", "text": "fr"}).json()
    assert fr["count"] == 2
    assert client.get("/api/v1/search/").status_code == 400
    assert client.get("/api/v1/search/", {"q": "x", "date_from": "31/12/2024"}).status_code == 400


def test_search_pagination(client, sitting):
    data = client.get("/api/v1/search/", {"q": "speaker", "page_size": 1}).json()
    assert len(data["results"]) == 1 and data["next"]


def test_trends(client, sitting):
    data = client.get("/api/v1/trends/", {"term": ["bridge", "rents"]}).json()
    assert [s["name"] for s in data["series"]] == ["bridge", "rents"]
    assert data["months"] == ["2022-03"]
    assert client.get("/api/v1/trends/").status_code == 400


def test_language(client, sitting):
    data = client.get("/api/v1/language/").json()
    assert set(data) >= {"overall", "by_month", "by_party", "by_member", "method"}


def test_topics_and_shifts_404_before_built(client):
    assert client.get("/api/v1/topics/").status_code == 404
    assert client.get("/api/v1/term-shifts/").status_code == 404


def test_api_is_read_only(client, sitting):
    assert client.post("/api/v1/sittings/", {}).status_code == 405
    assert client.delete("/api/v1/speeches/1001/").status_code == 405


def test_throttling(client, sitting, settings):
    from rest_framework.throttling import AnonRateThrottle

    cache.clear()
    original = AnonRateThrottle.THROTTLE_RATES
    AnonRateThrottle.THROTTLE_RATES = {"anon": "2/minute"}
    try:
        codes = [client.get("/api/v1/sittings/").status_code for _ in range(3)]
    finally:
        AnonRateThrottle.THROTTLE_RATES = original
        cache.clear()
    assert codes == [200, 200, 429]
