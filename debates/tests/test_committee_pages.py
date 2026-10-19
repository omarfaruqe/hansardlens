from pathlib import Path

import pytest

from debates.committees import store_meeting
from debates.models import Person, Witness

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = "https://www.ourcommons.ca/DocumentViewer/en/44-1/EXMP/meeting-12/evidence"
pytestmark = pytest.mark.django_db


@pytest.fixture
def meeting():
    Person.objects.create(name="Sam Okafor", latest_party="Lib.")
    return store_meeting(
        (FIXTURES / "committee_en.xml").read_bytes(),
        (FIXTURES / "committee_fr.xml").read_bytes(),
        SOURCE,
    ).meeting


def test_urls(meeting):
    assert meeting.get_absolute_url() == "/committees/EXMP/44-1/12/"
    assert meeting.committee.get_absolute_url() == "/committees/EXMP/"
    assert Witness.objects.get(name="Lena Park").get_absolute_url() == (
        "/committees/witnesses/lena-park/"
    )
    assert meeting.evidence_url("fr").endswith("/DocumentViewer/fr/44-1/EXMP/meeting-12/evidence")


def test_committee_list(client, meeting):
    html = client.get("/committees/").content.decode()
    assert (
        "Standing Committee on Example Affairs" in html
        and 'href="/committees/EXMP/?text=en"' in html
    )


def test_committee_page(client, meeting):
    html = client.get("/committees/EXMP/").content.decode()
    assert "1 public meeting" in html
    assert "Lena Park, Sam Quill" in html  # witnesses summarise the meeting
    assert "Example Bank of Canada" in html
    assert client.get("/committees/exmp/").status_code == 301
    assert client.get("/committees/ZZZZ/").status_code == 404


def test_meeting_page(client, meeting):
    html = client.get("/committees/EXMP/44-1/12/").content.decode()
    assert "Chair: Tom Reed" in html
    assert 'href="/committees/witnesses/lena-park/?text=en"' in html
    assert 'href="/members/jane-alder/"' in html  # members link to their page
    assert 'href="/members/sam-okafor/"' in html  # the minister too
    assert 'id="ci-2"' in html and "Translated from French" in html
    assert "https://www.ourcommons.ca/DocumentViewer/en/44-1/EXMP/meeting-12/evidence" in html


def test_meeting_page_in_french(client, meeting):
    html = client.get("/committees/EXMP/44-1/12/", {"lang": "fr"}).content.decode()
    assert "Comité permanent des affaires exemples" in html
    assert "économiste en chef, Banque exemple du Canada" in html
    assert "Témoins" in html and "Présidence : Tom Reed" in html and ">Comités<" in html


def test_witnesses(client, meeting):
    html = client.get("/committees/witnesses/").content.decode()
    assert "2 witnesses" in html and "Chief Economist, Example Bank of Canada" in html
    assert "1 witness" in client.get("/committees/witnesses/", {"q": "banque"}).content.decode()
    html = client.get("/committees/witnesses/sam-quill/").content.decode()
    assert "as an individual" in html and "Heard at 1 meeting" in html
    assert "/committees/EXMP/44-1/12/?text=en#ci-3" in html
    html = client.get("/committees/witnesses/", {"lang": "fr"}).content.decode()
    assert "2 témoins" in html and "Dernière comparution" in html


def test_committee_search(client, meeting):
    html = client.get("/committees/search/", {"q": "interest rates"}).content.decode()
    assert "2 matching paragraphs" in html and "<mark>" in html
    html = client.get("/committees/search/", {"q": "interest rates", "role": "witness"}).content
    assert "1 matching paragraph" in html.decode()
    html = client.get("/committees/search/", {"q": "taux", "text": "fr"}).content.decode()
    assert "2 matching paragraphs" in html


def test_member_page_shows_committee_work(client, meeting):
    html = client.get("/members/jane-alder/").content.decode()
    assert "In committee" in html and "Spoke at 1 public meeting" in html
    assert "/committees/EXMP/44-1/12/?text=en#ci-4" in html


def test_committees_api(client, meeting):
    data = client.get("/api/v1/committees/").json()
    assert data == [
        {
            "acronym": "EXMP",
            "name_en": "Standing Committee on Example Affairs",
            "name_fr": "Comité permanent des affaires exemples",
            "meetings": 1,
            "first_date": "2023-03-06",
            "last_date": "2023-03-06",
            "url": "/committees/EXMP/",
        }
    ]
    meetings = client.get("/api/v1/committees/exmp/meetings/").json()
    assert meetings["count"] == 1
    assert [w["slug"] for w in meetings["results"][0]["witnesses"]] == ["lena-park", "sam-quill"]
    assert client.get("/api/v1/committees/EXMP/meetings/", {"session": 2}).json()["count"] == 0
    assert client.get("/api/v1/committees/ZZZZ/meetings/").status_code == 404


def test_meeting_api(client, meeting):
    data = client.get("/api/v1/committees/EXMP/44-1/12/").json()
    assert data["chair"] == "Tom Reed" and data["committee_name_fr"].startswith("Comité")
    roles = [(i["role"], i["person"] or i["witness"]) for i in data["interventions"]]
    assert ("witness", "lena-park") in roles and ("member", "jane-alder") in roles
    assert ("minister", "sam-okafor") in roles
    quill = next(i for i in data["interventions"] if i["witness"] == "sam-quill")
    assert quill["paragraphs"][0]["floor_language"] == "fr"
    assert client.get("/api/v1/committees/EXMP/44-1/13/").status_code == 404


def test_witnesses_api(client, meeting):
    data = client.get("/api/v1/witnesses/", {"q": "banque"}).json()
    assert data["count"] == 1 and data["results"][0]["slug"] == "lena-park"
    assert data["results"][0]["meetings"] == 1
    assert client.get("/api/v1/witnesses/", {"committee": "zzzz"}).json()["count"] == 0
    one = client.get("/api/v1/witnesses/sam-quill/").json()
    assert one["as_individual"] is True
    assert one["appearances"][0]["url"] == "/committees/EXMP/44-1/12/"
    assert client.get("/api/v1/witnesses/nobody/").status_code == 404
