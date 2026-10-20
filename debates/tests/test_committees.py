import datetime as dt
from pathlib import Path

import pytest
import requests
from django.core.management import call_command

from debates.committees import (
    MeetingNotFound,
    NoEvidence,
    get_meeting_xml,
    read_speaker,
    store_meeting,
)
from debates.models import Committee, Meeting, MeetingIntervention, Person, Witness

FIXTURES = Path(__file__).parent / "fixtures"
EN = (FIXTURES / "committee_en.xml").read_bytes()
FR = (FIXTURES / "committee_fr.xml").read_bytes()
SOURCE = "https://www.ourcommons.ca/DocumentViewer/en/44-1/EXMP/meeting-12/evidence"


# -- speakers -------------------------------------------------------------------------------


def test_chair_label_holds_name_riding_and_party():
    sp = read_speaker(
        "35",
        "The Chair (Hon. Karina Gould (Burlington, Lib.))",
        "La présidente (L'hon. Karina Gould (Burlington, Lib.))",
    )
    assert (sp.role, sp.name, sp.riding, sp.party) == (
        "chair",
        "Karina Gould",
        "Burlington",
        "Lib.",
    )
    assert (sp.detail_en, sp.detail_fr) == ("The Chair", "La présidente")


def test_witness_title_affiliation_and_individual():
    sp = read_speaker(
        "28",
        "Prof. Luc Roy (Professor, Chair in Taxation, Université X, As an Individual)",
        "M. Luc Roy (professeur, Chaire en fiscalité, Université X, à titre personnel)",
    )
    assert sp.role == "witness" and sp.name == "Luc Roy"
    assert (sp.title_en, sp.affiliation_en) == ("Professor", "Chair in Taxation, Université X")
    assert (sp.title_fr, sp.affiliation_fr) == ("professeur", "Chaire en fiscalité, Université X")
    assert sp.individual is True
    # an organisation whose name has a comma stays whole
    sp = read_speaker("28", "Mr. Dan Brook (President, Letko, Brosseau & Associates Inc.)", "")
    assert sp.affiliation_en == "Letko, Brosseau & Associates Inc."


def test_minister_member_and_clerk():
    assert read_speaker("4", "Hon. Ann Lee (Minister of Finance)", "").role == "minister"
    member = read_speaker("47", "Mr. Dan Albas (Okanagan Lake West, CPC)", "")
    assert (member.role, member.name, member.party) == ("member", "Dan Albas", "CPC")
    clerk = read_speaker("27", "The Clerk of the Committee (Ms. Ada Byrne)", "")
    assert (clerk.role, clerk.name) == ("clerk", "Ada Byrne")


# -- storing -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_store_meeting():
    result = store_meeting(EN, FR, SOURCE)
    m = result.meeting
    assert (m.committee.acronym, m.parliament, m.session, m.number) == ("EXMP", 44, 1, 12)
    assert m.date == dt.date(2023, 3, 6) and m.chair == "Tom Reed" and m.issues == []
    assert m.committee.name_fr == "Comité permanent des affaires exemples"
    ivs = list(m.interventions.order_by("sequence"))
    assert [iv.role for iv in ivs] == [
        "chair",
        "witness",
        "witness",
        "member",
        "witness",
        "chair",
        "minister",
        "member",
        "clerk",
    ]
    # short labels later in the meeting keep the details of the first, full label
    assert ivs[5].name == "Tom Reed" and ivs[5].party == "Lib."
    assert ivs[7].name == "Jane Alder" and ivs[7].party == "CPC"
    assert ivs[4].witness == ivs[1].witness
    assert ivs[2].paragraphs.get().floor_language == "fr"
    assert ivs[3].paragraphs.get().text_fr.startswith("Madame Park")


@pytest.mark.django_db
def test_witnesses_and_people():
    store_meeting(EN, FR, SOURCE)
    park = Witness.objects.get(name="Lena Park")
    assert (park.title_en, park.affiliation_en) == ("Chief Economist", "Example Bank of Canada")
    assert (park.title_fr, park.affiliation_fr) == (
        "économiste en chef",
        "Banque exemple du Canada",
    )
    assert Witness.objects.get(name="Sam Quill").as_individual is True
    assert Person.objects.filter(name="Jane Alder").exists()  # members are people
    assert not Person.objects.filter(name="Lena Park").exists()  # witnesses are not


@pytest.mark.django_db
def test_minister_linked_only_to_existing_person():
    Person.objects.create(name="Sam Okafor", latest_party="Lib.")
    store_meeting(EN, FR, SOURCE)
    minister = MeetingIntervention.objects.get(role="minister")
    assert minister.person.name == "Sam Okafor" and minister.party == "Lib."


@pytest.mark.django_db
def test_reloading_replaces_the_meeting():
    store_meeting(EN, FR, SOURCE)
    store_meeting(EN, FR, SOURCE)
    assert Meeting.objects.count() == 1 and MeetingIntervention.objects.count() == 9
    assert Witness.objects.count() == 2


# -- finding transcripts ------------------------------------------------------------------------


def fake_site(pages: dict, files: dict, calls: list):
    """pages: url -> html (missing: 404); files: url -> bytes"""

    def fetch(url, user_agent, timeout=60):
        calls.append(url)
        if url in pages:
            return pages[url].encode()
        if url in files:
            return files[url]
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError(response=response)

    return fetch


def page(n):
    return f"https://www.ourcommons.ca/DocumentViewer/en/44-1/EXMP/meeting-{n}/evidence"


XML = "https://www.ourcommons.ca/Content/Committee/441/EXMP/Evidence/EV1/EXMPEV12"


@pytest.fixture
def site(monkeypatch, settings, tmp_path):
    settings.DATA_DIR = tmp_path
    calls = []
    pages = {
        page(12): '<a href="/Content/Committee/441/EXMP/Evidence/EV1/EXMPEV12-E.XML">XML</a>',
        page(13): "<h1>Meeting 13</h1> In camera",
    }
    files = {XML + "-E.XML": EN, XML + "-F.XML": FR}
    monkeypatch.setattr("debates.committees.fetch", fake_site(pages, files, calls))
    return calls


def test_transcript_found_from_meeting_page(site, tmp_path):
    en, fr, source = get_meeting_xml(44, 1, "EXMP", 12)
    assert (en, fr, source) == (EN, FR, page(12))
    assert (tmp_path / "raw" / "committees" / "44-1-EXMP-012-en.xml").exists()
    get_meeting_xml(44, 1, "EXMP", 12)  # second time: from the cache
    assert len(site) == 3


def test_in_camera_and_missing_meetings(site):
    with pytest.raises(NoEvidence):
        get_meeting_xml(44, 1, "EXMP", 13)
    with pytest.raises(MeetingNotFound):
        get_meeting_xml(44, 1, "EXMP", 14)


@pytest.mark.django_db
def test_load_committees_command(site, tmp_path, capsys):
    call_command(
        "load_committees",
        committee=["exmp"],
        parliament=44,
        session=1,
        start=11,
        max_misses=3,
        sleep=0,
        no_cache=True,
    )
    out = capsys.readouterr().out
    assert "011: no meeting" in out and "012: 2023-03-06" in out and "013: no transcript" in out
    assert "Done: 1 meeting(s) loaded" in out
    assert not (tmp_path / "raw" / "committees").exists()  # --no-cache
    assert Committee.objects.get().acronym == "EXMP"
    # next run continues after the last loaded meeting
    call_command(
        "load_committees", committee=["EXMP"], parliament=44, session=1, max_misses=2, sleep=0
    )
    assert "EXMP 44-1: from meeting 13" in capsys.readouterr().out


@pytest.mark.django_db
def test_in_camera_meetings_do_not_end_the_search(monkeypatch, settings, tmp_path, capsys):
    """Meetings 1-5 have a page but no transcript yet, 6 is public, then nothing: with
    --max-misses 2 the search still reaches meeting 6, and stops after two numbers that
    do not exist."""
    settings.DATA_DIR = tmp_path
    calls = []
    pages = {page(n): f"<h1>Meeting {n}</h1> In camera" for n in range(1, 6)}
    pages[page(6)] = '<a href="/Content/Committee/441/EXMP/Evidence/EV1/EXMPEV12-E.XML">XML</a>'
    files = {XML + "-E.XML": EN, XML + "-F.XML": FR}
    monkeypatch.setattr("debates.committees.fetch", fake_site(pages, files, calls))
    call_command(
        "load_committees",
        committee=["EXMP"],
        parliament=44,
        session=1,
        start=1,
        max_misses=2,
        sleep=0,
        no_cache=True,
    )
    out = capsys.readouterr().out
    assert "005: no transcript" in out and "Done: 1 meeting(s) loaded" in out
    assert "008: no meeting" in out and "009" not in out
    # but a very long run of meetings without transcripts does end it
    Meeting.objects.all().delete()
    call_command(
        "load_committees",
        committee=["EXMP"],
        parliament=44,
        session=1,
        start=1,
        max_misses=10,
        max_in_camera=3,
        sleep=0,
        no_cache=True,
    )
    out = capsys.readouterr().out
    assert "003: no transcript" in out and "004" not in out
    assert "Done: 0 meeting(s) loaded" in out
