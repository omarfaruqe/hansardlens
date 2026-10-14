import datetime as dt
from pathlib import Path

import pytest

from debates.loader import backfill_missing_parties, store, word_count
from debates.models import Intervention, Paragraph, Person, Sitting
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


def merged():
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return merge(en, fr)


def test_word_count_handles_apostrophes_and_hyphens():
    assert word_count("Saint-Jean's riding, l’économie et 2,500 jobs") == 7


def test_store_creates_rows():
    result = store(merged())
    assert result.created
    assert Sitting.objects.count() == 1
    assert result.interventions == Intervention.objects.count() == 8
    assert result.paragraphs == Paragraph.objects.count()


def test_store_is_idempotent():
    store(merged())
    result = store(merged())
    assert not result.created
    assert Sitting.objects.count() == 1
    assert Intervention.objects.count() == 8
    assert Person.objects.count() == 5  # Alder, Martel, Okafor, Pat Example, Rosa Lind


def test_member_fields_and_floor_words():
    store(merged())
    iv = Intervention.objects.get(house_id="1001")
    assert iv.person.name == "Jane Alder"
    assert (iv.party, iv.riding) == ("CPC", "Riverbend—North Shore")
    assert iv.floor_words_en == word_count("Mr. Speaker, the bridge in my riding opened last week.")
    assert iv.floor_words_fr == word_count("Il relie la circonscription de Luc Martel à la mienne.")
    assert iv.word_count_en > iv.floor_words_en


def test_chairs_do_not_get_a_party():
    store(merged())
    chair = Intervention.objects.get(house_id="1006")
    assert chair.is_chair and chair.party == ""
    assert chair.speaker_role == "The Assistant Deputy Speaker"
    assert chair.person.name == "Rosa Lind"


def test_procedural_words_are_not_counted():
    store(merged())
    proc = Intervention.objects.filter(kind="Procedural").last()
    assert proc.word_count_en == 0 and proc.text_en


def test_person_latest_party_updates_only_forward_in_time():
    store(merged())
    m = merged()
    m.number, m.date = 49, dt.date(2022, 3, 30)
    m.interventions[1].speaker = m.interventions[1].speaker.__class__(
        raw="x", name="Jane Alder", riding="Old Riding", party="NDP"
    )
    store(m)
    assert Person.objects.get(name="Jane Alder").latest_party == "CPC"


def test_backfill_uses_nearest_sitting():
    store(merged())
    m = merged()
    m.number, m.date = 60, dt.date(2022, 4, 20)
    # only a short label for Martel in this sitting
    m.interventions = [m.interventions[5]]
    m.interventions[0].speaker = m.interventions[0].speaker.__class__(
        raw="Luc Martel", name="Luc Martel"
    )
    Person.objects.filter(name="Luc Martel").update(latest_party="")
    store(m)
    iv = Intervention.objects.get(sitting__number=60)
    assert iv.party == ""
    assert backfill_missing_parties() == 1
    iv.refresh_from_db()
    assert iv.party == "BQ"


def test_unlisted_house_type_is_kept():
    m = merged()
    m.interventions[1].kind = "Statement"
    m.interventions[2].kind = "SomethingNew"
    store(m)
    assert Intervention.objects.get(house_id="1001").kind == "Statement"
    assert Intervention.objects.get(house_id="1002").kind == "SomethingNew"
