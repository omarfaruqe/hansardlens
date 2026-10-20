"""Committee analysis: kinds of witnesses, committee speech scored with the House topics,
and members' committee work."""

import datetime as dt
from pathlib import Path

import pytest

from debates import committee_analysis, textmine
from debates.committees import store_meeting
from debates.models import (
    Committee,
    Meeting,
    MeetingIntervention,
    MeetingInterventionTopic,
    MeetingParagraph,
    Person,
    Witness,
)
from debates.tests.test_textmine import FISH, HOMES, make_corpus
from debates.witness_kinds import classify, classify_parts

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE = "https://www.ourcommons.ca/DocumentViewer/en/44-1/EXMP/meeting-12/evidence"
QUIET = {"log": lambda *_: None}


# -- kinds of witnesses (labels as printed in real committee evidence) ------------------


@pytest.mark.parametrize(
    "label, kind",
    [
        ("Assistant Deputy Minister, Tax Policy Branch, Department of Finance", "federal"),
        ("Deputy Minister, Department of Public Works and Government Services", "federal"),
        ("Governor, Bank of Canada", "federal"),
        ("Chief Operating Officer, Canada Post Corporation", "federal"),
        (
            "Consul General of Canada in New York, Consulate General of Canada in New York",
            "federal",
        ),
        (
            "Director General, Economic Policy Development, Department of Indigenous Services",
            "federal",
        ),
        ("Parliamentary Budget Officer, Office of the Parliamentary Budget Officer", "officer"),
        ("Auditor General of Canada, Office of the Auditor General", "officer"),
        ("Commissioner of Lobbying of Canada", "officer"),
        (
            "Commissioner, Office of the Information and Privacy Commissioner of Ontario",
            "government",
        ),
        ("Mayor, City of Winnipeg", "government"),
        ("Director, Department of Finance, Government of the Northwest Territories", "government"),
        ("National Chief, Assembly of First Nations", "indigenous"),
        ("President, Inuit Tapiriit Kanatami", "indigenous"),
        ("President, Canadian Labour Congress", "labour"),
        ("National President, Public Service Alliance of Canada", "labour"),
        ("National President, Union of National Defence Employees", "labour"),
        ("President, Canadian Federation of Independent Business", "business"),
        ("Vice-President, Union des producteurs agricoles", "business"),
        ("Chief Economist, National Bank of Canada", "business"),
        ("Policy Lead, Meta Platforms Inc.", "business"),
        ("Senior Vice-President, Canadian Chamber of Commerce", "business"),
        ("President, C.D. Howe Institute", "research"),
        ("Professor, University of British Columbia", "research"),
        ("Vice-Provost, Indigenous Engagement, University of Saskatchewan", "research"),
        ("Executive Director, Democracy Watch", "civil"),
        ("Executive Director, Daily Bread Food Bank", "civil"),
        ("Economist, Organisation for Economic Co-operation and Development", "international"),
        ("Vice-President, Environment, Vancouver Fraser Port Authority", "federal"),
        ("Manager, Government Relations, Vancouver Airport Authority", "business"),
        ("Chair, Canadian Radio-television and Telecommunications Commission", "federal"),
        ("National President, Alliance of Canadian Cinema, Television and Radio Artists", "labour"),
        ("Social Worker, Women's Mental Health Program, Royal Ottawa Health Care Group", "civil"),
        ("President, Oliver and Bonacini Hospitality", "business"),
        ("President, Alberta Municipalities", "government"),
        ("Professor, Carleton University, As an Individual", "individual"),
        ("Tax Expert, As individual", "individual"),
        ("President", "unknown"),
        ("", "unknown"),
    ],
)
def test_classify(label, kind):
    assert classify(label) == kind


def test_individual_flag_wins():
    assert classify("Governor, Bank of Canada", as_individual=True) == "individual"


def test_classify_parts_keeps_commas_in_the_organisation():
    assert classify_parts("", "Tax Policy Branch, Department of Finance") == "federal"
    assert classify_parts("Professor", "") == "unknown"


# -- data -------------------------------------------------------------------------------


@pytest.fixture
def meeting(db):
    Person.objects.create(name="Sam Okafor", latest_party="Lib.")
    return store_meeting(
        (FIXTURES / "committee_en.xml").read_bytes(),
        (FIXTURES / "committee_fr.xml").read_bytes(),
        SOURCE,
    ).meeting


def committee_speeches():
    """A committee meeting whose witness talks fisheries and member talks housing."""
    committee = Committee.objects.create(acronym="FOPO", name_en="Fisheries")
    m = Meeting.objects.create(
        committee=committee, parliament=45, session=1, number=1, date=dt.date(2025, 3, 1)
    )
    member = Person.objects.get(name="Bob Test")
    witness = Witness.objects.create(house_db_id="1", name="Wanda Witness")
    rows = [
        ("witness", None, witness, FISH),
        ("member", member, None, HOMES),
        ("chair", member, None, FISH),  # the chair is not scored
        ("witness", None, witness, "salmon"),  # too short
    ]
    for seq, (role, person, wit, words) in enumerate(rows, 1):
        text = " ".join(words.split() * 8)
        iv = MeetingIntervention.objects.create(
            meeting=m,
            sequence=seq,
            role=role,
            person=person,
            witness=wit,
            words_en=len(text.split()),
        )
        MeetingParagraph.objects.create(
            intervention=iv, sequence=1, kind="speech", text_en=text, text_fr=text
        )
    return committee, m


PARAMS = textmine.TopicParams(n_topics=2, min_df=2, max_df=0.9, min_words=10)


@pytest.mark.django_db
def test_committee_speech_is_scored_with_the_house_topics():
    make_corpus()
    committee, meeting = committee_speeches()
    model = textmine.fit_topics(PARAMS, **QUIET)
    scored = {
        a.intervention.role: {t for t, _ in a.topic.terms[:5]}
        for a in MeetingInterventionTopic.objects.select_related("intervention", "topic")
    }
    assert set(scored) == {"witness", "member"}  # chair and short speech left out
    assert scored["witness"] <= set(FISH.split())
    assert scored["member"] <= set(HOMES.split())
    assert MeetingInterventionTopic.objects.count() == 2

    # a refit replaces the committee assignments with the new model's
    second = textmine.fit_topics(PARAMS, **QUIET)
    assert not MeetingInterventionTopic.objects.exclude(topic__model=second).exists()
    assert model.id != second.id


@pytest.mark.django_db
def test_committee_topic_shares(monkeypatch):
    make_corpus()
    committee, meeting = committee_speeches()
    model = textmine.fit_topics(PARAMS, **QUIET)
    monkeypatch.setattr(committee_analysis, "TOPIC_MIN_SPEECHES", 1)
    shares = committee_analysis.committee_topics(committee, model)
    assert shares["total"] == 2
    assert sorted(r["share"] for r in shares["rows"]) == [50.0, 50.0]
    assert {r["house_share"] for r in shares["rows"]} <= {
        round(100 * t.share, 1) for t in model.topics.all()
    }
    fish = MeetingInterventionTopic.objects.get(intervention__role="witness").topic
    by_committee = committee_analysis.topic_by_committee(fish)
    assert by_committee == [
        {
            "acronym": "FOPO",
            "name_en": "Fisheries",
            "name_fr": "",
            "hits": 1,
            "total": 2,
            "share": 50.0,
        }
    ]
    assert committee_analysis.meeting_topics(meeting, model) == []  # fewer than 5 speeches


@pytest.mark.django_db
def test_too_few_committee_speeches_show_no_topics():
    make_corpus()
    committee, _ = committee_speeches()
    model = textmine.fit_topics(PARAMS, **QUIET)
    assert committee_analysis.committee_topics(committee, model) == {"total": 2, "rows": []}


def test_witness_kinds(meeting):
    kinds = committee_analysis.witness_kinds(meeting.committee)
    # Lena Park's "Example Bank of Canada" reads as the central bank; Sam Quill speaks
    # as an individual. Each witness counts once for the meeting.
    assert kinds == {
        "total": 2,
        "rows": [
            {"kind": "federal", "n": 1, "share": 50.0},
            {"kind": "individual", "n": 1, "share": 50.0},
        ],
    }
    table = committee_analysis.witness_kinds_by_committee()
    assert table["kinds"] == ["federal", "individual"]
    assert table["rows"] == [{"acronym": "EXMP", "total": 2, "cells": [50.0, 50.0]}]
    assert table["all"] == {"acronym": "", "total": 2, "cells": [50.0, 50.0]}
    assert committee_analysis.witness_kinds(meeting.committee, (45, 1))["total"] == 0


def test_committee_members_and_member_work(meeting):
    members = committee_analysis.committee_members(meeting.committee)
    assert [m["name"] for m in members] == ["Jane Alder", "Sam Okafor"] or [
        m["name"] for m in members
    ] == ["Sam Okafor", "Jane Alder"]
    jane = Person.objects.get(name="Jane Alder")
    work = committee_analysis.member_committee_work(jane)
    assert work["committee_interventions"] == 2 and work["committee_meetings"] == 1
    assert work["house_speeches"] == 0 and work["committee_share"] == 100.0
    assert work["chaired_meetings"] == 0


def test_witness_kind_property(meeting):
    assert Witness.objects.get(name="Sam Quill").kind == "individual"
    assert Witness.objects.get(name="Lena Park").kind == "federal"


# -- pages and API ----------------------------------------------------------------------


def test_committee_pages_show_who_is_heard(client, meeting):
    html = client.get("/committees/").content.decode()
    assert "Who is heard" in html and "Federal departments and agencies" in html
    html = client.get("/committees/EXMP/").content.decode()
    assert "Who is heard" in html and "Share of 2 witness appearances" in html
    assert "Members who spoke most" in html and 'href="/members/jane-alder/"' in html
    html = client.get("/committees/EXMP/", {"lang": "fr"}).content.decode()
    assert "Qui est entendu" in html and "Particuliers" in html


def test_witness_kind_filter_and_label(client, meeting):
    html = client.get("/committees/witnesses/", {"kind": "individual"}).content.decode()
    assert "1 witness" in html and "Sam Quill" in html and "Lena Park" not in html
    assert "2 witnesses" in client.get("/committees/witnesses/", {"kind": "x"}).content.decode()
    html = client.get("/committees/witnesses/sam-quill/").content.decode()
    assert 'href="/committees/witnesses/?kind=individual"' in html


def test_member_page_compares_committee_and_house(client, meeting):
    html = client.get("/members/jane-alder/").content.decode()
    assert "100.0% of what this member said was said in committee" in html


@pytest.mark.django_db
def test_topic_and_meeting_pages_show_committee_topics(client, monkeypatch):
    make_corpus()
    committee, meeting = committee_speeches()
    textmine.fit_topics(PARAMS, **QUIET)
    fish = MeetingInterventionTopic.objects.get(intervention__role="witness").topic
    monkeypatch.setattr(committee_analysis, "TOPIC_MIN_SPEECHES", 1)
    html = client.get(f"/topics/{fish.number}/").content.decode()
    assert "In committee" in html and 'href="/committees/FOPO/"' in html
    html = client.get("/committees/FOPO/").content.decode()
    assert "Main topics" in html and f'href="/topics/{fish.number}/"' in html
    html = client.get("/committees/FOPO/45-1/1/").content.decode()
    assert "Main topics:" not in html  # too few speeches for a meeting's topics


def test_committee_api(client, meeting):
    data = client.get("/api/v1/committees/exmp/").json()
    assert data["acronym"] == "EXMP" and data["session"] is None
    assert data["witness_kinds"]["total"] == 2 and data["topics"] is None
    assert [m["slug"] for m in data["members"]][0] in {"jane-alder", "sam-okafor"}
    assert client.get("/api/v1/committees/EXMP/", {"session": "45-1"}).json()["session"] == "45-1"
    assert client.get("/api/v1/committees/ZZZZ/").status_code == 404
    rows = client.get("/api/v1/witnesses/", {"kind": "individual"}).json()["results"]
    assert [(w["slug"], w["kind"]) for w in rows] == [("sam-quill", "individual")]
