import datetime as dt
from pathlib import Path

import pytest

from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def en():
    return parse_document((FIXTURES / "sitting_en.xml").read_bytes())


@pytest.fixture
def fr():
    return parse_document((FIXTURES / "sitting_fr.xml").read_bytes())


def test_metadata(en):
    assert (en.parliament, en.session, en.number) == (44, 1, 50)
    assert en.date == dt.date(2022, 3, 31)
    assert en.lang == "en"
    assert en.speaker_of_house == "Pat Example"
    assert len(en.checksum) == 64


def test_french_speaker_of_house(fr):
    assert fr.speaker_of_house == "Pat Example"


def test_interventions_in_document_order(en):
    kinds = [(iv.house_id, iv.kind) for iv in en.interventions]
    assert kinds == [
        ("", "Procedural"),  # Intro
        ("1001", "Debate"),
        ("1002", "Question"),
        ("1003", "Answer"),
        ("1004", "Interjection"),
        ("1005", "Question"),
        ("1006", "Interjection"),
        ("", "Procedural"),  # loose motion text before the vote
    ]


def test_context_is_carried(en):
    iv = en.interventions[1]
    assert iv.rubric == "StatementsByMembers"
    assert iv.order_title == "Statements by Members"
    assert iv.subject_title == "Harbour Bridges"
    assert iv.time == dt.time(10, 5)
    assert iv.speaker_db_id == "501" and iv.speaker_type == "2"


def test_floor_language_switches_carry_across_interventions(en):
    first = en.interventions[1].paragraphs
    assert [p.floor_language for p in first] == ["en", "fr"]
    # Next intervention has no marker of its own: French continues
    assert en.interventions[2].paragraphs[0].floor_language == "fr"
    assert en.interventions[3].paragraphs[0].floor_language == "en"


def test_timestamp_inside_content_applies_to_later_interventions(en):
    assert en.interventions[3].time == dt.time(10, 5)  # set before its own timestamp
    assert en.interventions[4].time == dt.time(14, 20)


def test_inline_names_are_kept_as_text(en):
    assert en.interventions[1].paragraphs[1].text == "It connects Luc Martel's riding to mine."


def test_division_lists_are_not_speech(en):
    last = en.interventions[-1]
    texts = " ".join(p.text for p in last.paragraphs)
    assert "Alder" not in texts
    assert [p.kind for p in last.paragraphs] == ["procedural", "procedural"]


def test_procedural_text_inside_intervention(en):
    p = en.interventions[6].paragraphs[0]
    assert p.kind == "procedural" and p.text.startswith("(The sitting was suspended")


def test_rejects_non_hansard():
    with pytest.raises(ValueError):
        parse_document(b"<?xml version='1.0'?><html><body/></html>")


def test_rejects_missing_metadata():
    with pytest.raises(ValueError):
        parse_document(b"<?xml version='1.0'?><Hansard><HansardBody/></Hansard>")


# -- merge -----------------------------------------------------------------------------


def test_merge_aligns_languages(en, fr):
    m = merge(en, fr)
    assert m.issues == []
    assert m.has_french
    iv = m.interventions[1]
    assert iv.subject_title_fr == "Les ponts du port"
    assert iv.paragraphs[0].text_fr.startswith("Monsieur le Président")
    assert iv.speaker_label_fr.startswith("Mme Jane Alder")


def test_merge_keeps_english_type_when_french_differs(en, fr):
    assert fr.interventions[2].kind == "Debate"
    assert merge(en, fr).interventions[2].kind == "Question"


def test_short_label_gets_party_from_earlier_full_label(en, fr):
    later = merge(en, fr).interventions[5]
    assert later.speaker.name == "Luc Martel"
    assert later.speaker.party == "BQ" and later.speaker.riding == "Lac-Bleu"


def test_the_speaker_is_named_from_masthead(en, fr):
    chair = merge(en, fr).interventions[4].speaker
    assert chair.is_chair and chair.name == "Pat Example"


def test_merge_without_french(en):
    m = merge(en, None)
    assert not m.has_french
    assert all(p.text_fr == "" for iv in m.interventions for p in iv.paragraphs)


def test_merge_by_id_when_order_differs(en, fr):
    fr.interventions.reverse()
    m = merge(en, fr)
    assert m.issues  # reported
    assert m.interventions[2].paragraphs[0].text_fr.startswith("Monsieur le Président, les loyers")


def test_merge_rejects_different_sittings(en, fr):
    fr.number = 51
    with pytest.raises(ValueError):
        merge(en, fr)
