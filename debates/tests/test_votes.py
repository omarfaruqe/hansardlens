from pathlib import Path

import pytest

from debates.loader import store
from debates.models import Division, Person, Vote
from debates.parsing import merge, parse_document, read_heading, read_outcome
from debates.votes import fold, link_votes

FIXTURES = Path(__file__).parent / "fixtures"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def merged_votes():
    en = parse_document((FIXTURES / "votes_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "votes_fr.xml").read_bytes())
    return merge(en, fr)


# -- parsing ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, lang, expected",
    [
        (
            "(The House divided on the motion, which was negatived on the following division:)",
            "en",
            ("The motion", "negatived"),
        ),
        (
            "(The House divided on Motion No. 3, which was agreed to on the following division:)",
            "en",
            ("Motion No. 3", "agreed"),
        ),
        (
            "(La motion no 3, mise aux voix, est adoptée par le vote suivant :)",
            "fr",
            ("La motion no 3", "agreed"),
        ),
        (
            "(L'amendement, mis aux voix, est rejeté par le vote suivant :)",
            "fr",
            ("L'amendement", "negatived"),
        ),
        # 2020 reduced-attendance sittings state no outcome before the list
        ("(The House divided on the motion:)", "en", ("The motion", "")),
        ("(La motion est mise aux voix.)", "fr", ("La motion", "")),
        ("Something else entirely", "en", ("", "")),
    ],
)
def test_read_heading(text, lang, expected):
    assert read_heading(text, lang) == expected


def test_divisions_are_parsed_with_context():
    m = merged_votes()
    assert [d.number for d in m.divisions] == [54, 55, 56]
    first, second, third = m.divisions
    assert first.subject_title_en == "Business of Supply"
    assert first.qualifier_en == "Opposition Motion—Example Rents"
    assert first.qualifier_fr == "Motion de l'opposition — Les loyers exemple"
    assert (first.object_en, first.object_fr, first.result) == (
        "The motion",
        "La motion",
        "negatived",
    )
    assert {k: len(v) for k, v in first.votes.items()} == {"yea": 3, "nay": 5, "paired": 2}
    assert ("506", "Reed (Westvale)") in first.votes["yea"]
    # the division points at the block holding "(The House divided on ...)"
    assert m.interventions[first.position].paragraphs[-1].text_en.startswith("(The House divided")
    assert second.qualifier_en == "Concurrence in Vote 1—Example Agency"
    assert (second.object_en, second.result) == ("Motion No. 1", "agreed")
    # a later vote in the same subject does not inherit the qualifier
    assert third.subject_title_en == "Main Estimates, 2022-23" and third.qualifier_en == ""


def test_divisions_do_not_change_speeches():
    m = merged_votes()
    kinds = [iv.kind for iv in m.interventions]
    assert kinds.count("Debate") == 11 and kinds.count("Procedural") == 3


# -- storing and matching -------------------------------------------------------------------


@pytest.mark.django_db
def test_store_saves_divisions_and_votes():
    sitting = store(merged_votes()).sitting
    d = Division.objects.get(sitting=sitting, number=54)
    assert (d.yeas, d.nays, d.paired, d.result) == (3, 5, 2, "negatived")
    assert d.official_url("fr") == "https://www.ourcommons.ca/members/fr/votes/44/1/54"
    assert sitting.interventions.get(sequence=d.sequence).text_en.startswith("(The House divided")
    assert Vote.objects.filter(division=d).count() == 10


@pytest.mark.django_db
def test_votes_match_by_id_then_surname_and_riding():
    store(merged_votes())
    votes = {v.label: v for v in Vote.objects.filter(division__number=54).select_related("person")}
    assert votes["Alder"].person.name == "Jane Alder"  # member id from her speech
    assert votes["Okafor"].person.name == "Sam Okafor"  # role id differs: surname
    assert votes["Reed (Westvale)"].person.name == "Tom Reed"  # surname + riding
    assert votes["Reed (Eastport)"].person.name == "Ana Reed"
    assert votes["Zed"].person is None  # nobody by that name: label kept
    assert votes["Okafor"].party == "Lib." and votes["Alder"].party == "CPC"


@pytest.mark.django_db
def test_party_lines():
    store(merged_votes())
    votes = {v.label: v for v in Vote.objects.filter(division__number=54)}
    # 1 Liberal yea against 4 nays (5 voting, enough for a party line)
    assert votes["Reed (Westvale)"].against_party is True
    assert votes["Bell"].against_party is False
    assert votes["Nash"].against_party is None  # paired
    assert votes["Alder"].against_party is None  # only 2 CPC members voting: no line
    assert votes["Zed"].against_party is None  # party unknown


@pytest.mark.django_db
def test_reloading_replaces_votes():
    store(merged_votes())
    store(merged_votes())
    assert Division.objects.count() == 3
    assert Vote.objects.filter(division__number=55).count() == 9


@pytest.mark.django_db
def test_link_votes_matches_members_who_speak_later():
    store(merged_votes())
    zed = Vote.objects.get(label="Zed")
    assert zed.person is None
    Person.objects.create(name="Alex Zed")  # not enough: has not spoken in this Parliament
    assert link_votes() == 0
    # Zed speaks in a later sitting under member id 999
    from debates.models import Intervention

    iv = Intervention.objects.filter(person__name="Jane Alder").first()
    iv.pk, iv.sequence = None, 999
    iv.person = Person.objects.get(name="Alex Zed")
    iv.speaker_db_id, iv.house_id = "999", ""
    iv.save()
    assert link_votes() == 1
    assert Vote.objects.get(label="Zed").person.name == "Alex Zed"


def test_fold():
    assert fold("Brunelle-Duceppe") == "brunelle duceppe"
    assert fold("Généreux") == "genereux"
    assert fold("d'Entremont") == "d entremont"


# -- real files, when downloaded ---------------------------------------------------------------


def test_real_sitting_with_many_divisions():
    path = RAW / "P44S1-264-en.xml"
    if not path.exists():
        pytest.skip("P44S1-264 not downloaded")
    en = parse_document(path.read_bytes())
    fr = parse_document((RAW / "P44S1-264-fr.xml").read_bytes())
    m = merge(en, fr)
    assert len(m.divisions) == 125
    assert all(d.object_en and d.object_fr and d.result for d in m.divisions)
    first = m.divisions[0]
    assert first.qualifier_en.startswith("Opposition Motion—Carbon Tax")
    assert (len(first.votes["yea"]), len(first.votes["nay"]), first.result) == (
        112,
        202,
        "negatived",
    )


# -- load_divisions command -------------------------------------------------------------------


@pytest.mark.django_db
def test_load_divisions_adds_votes_without_touching_speeches(monkeypatch, settings, tmp_path):
    from django.core.management import call_command

    from debates.models import Intervention

    settings.DATA_DIR = tmp_path
    sitting = store(merged_votes()).sitting
    Division.objects.all().delete()  # as if loaded before version 1.5
    speeches = list(Intervention.objects.values_list("id", flat=True))
    served = []

    def fake_fetch(url, user_agent, timeout=60):
        served.append(url)
        lang = "fr" if url.endswith("-F.XML") else "en"
        return (FIXTURES / f"votes_{lang}.xml").read_bytes()

    monkeypatch.setattr("debates.loader.fetch", fake_fetch)
    call_command("load_divisions", sleep=0, no_cache=True)
    assert Division.objects.filter(sitting=sitting).count() == 3
    assert Vote.objects.filter(person__name="Tom Reed").count() == 2
    assert list(Intervention.objects.values_list("id", flat=True)) == speeches
    assert len(served) == 2 and not (tmp_path / "raw").exists()  # nothing cached
    call_command("load_divisions", sleep=0)  # again, now caching the downloads
    assert Division.objects.count() == 3 and (tmp_path / "raw").exists()


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Motion negatived I declare the motion defeated.", "negatived"),
        ("I declare the motion carried.", "agreed"),
        ("Amendment agreed to", "agreed"),
        ("Je déclare la motion rejetée.", "negatived"),
        ("Order. The hon. member for Calgary.", ""),
    ],
)
def test_read_outcome(text, expected):
    assert read_outcome(text) == expected


def test_tie_decided_after_the_vote():
    """Real 43-1 sitting 38 (May 2020): 23 to 23, the Speaker declares it defeated."""
    path = RAW / "P43S1-038-en.xml"
    if not path.exists():
        pytest.skip("P43S1-038 not downloaded")
    m = merge(
        parse_document(path.read_bytes()), parse_document((RAW / "P43S1-038-fr.xml").read_bytes())
    )
    tie = next(d for d in m.divisions if d.number == 24)
    assert (len(tie.votes["yea"]), len(tie.votes["nay"])) == (23, 23)
    assert (tie.object_en, tie.object_fr, tie.result) == ("The motion", "La motion", "negatived")


def test_outcome_announced_after_the_vote_is_used():
    """A heading without an outcome takes the Speaker's announcement that follows."""

    def variant(lang, heading, announcement):
        xml = (FIXTURES / f"votes_{lang}.xml").read_text(encoding="utf-8")
        old = (
            "(The House divided on the motion, which was agreed to on the following division:)"
            if lang == "en"
            else "(La motion, mise aux voix, est adoptée par le vote suivant :)"
        )
        start = xml.index('<SubjectOfBusiness id="955">')
        head, tail = xml[:start], xml[start:].replace(old, heading, 1)
        reply = (
            '<Intervention Type="Debate" id="1300"><PersonSpeaking><Affiliation DbId="504" '
            f'Type="96">Speaker</Affiliation></PersonSpeaking><Content><ParaText id="2300">'
            f"{announcement}</ParaText></Content></Intervention>"
        )
        tail = tail.replace("</Division>", "</Division>" + reply, 1)
        return parse_document((head + tail).encode("utf-8"))

    m = merge(
        variant("en", "(The House divided on the motion:)", "Motion negatived"),
        variant("fr", "(La motion est mise aux voix.)", "Je déclare la motion rejetée."),
    )
    last = m.divisions[-1]
    assert last.number == 56 and (len(last.votes["yea"]), len(last.votes["nay"])) == (1, 0)
    # the counts alone would say "agreed"; the announcement decides
    assert (last.object_en, last.object_fr, last.result) == ("The motion", "La motion", "negatived")
