import datetime as dt
from pathlib import Path

import pytest

from debates import analysis
from debates.loader import store
from debates.models import (
    Intervention,
    InterventionTopic,
    Paragraph,
    Person,
    Sitting,
    Topic,
    TopicModel,
    person_slug,
)
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


@pytest.fixture
def sitting():
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


# -- slugs ------------------------------------------------------------------------------


def test_slug_drops_accents_and_apostrophes():
    assert person_slug("Bernard Généreux") == "bernard-genereux"
    assert person_slug("Chris d'Entremont") == "chris-dentremont"
    assert person_slug("") == "member"


def test_slug_clash_gets_a_number():
    taken = {"jean-roy", "jean-roy-2"}
    assert person_slug("Jean Roy", taken.__contains__) == "jean-roy-3"


def test_person_gets_slug_on_create_and_keeps_it():
    a = Person.objects.create(name="Jean Roy")
    b = Person.objects.create(name="Jean  Roy")  # different name, same slug base
    assert (a.slug, b.slug) == ("jean-roy", "jean-roy-2")
    a.latest_party = "Lib."
    a.save()
    a.refresh_from_db()
    assert a.slug == "jean-roy"
    assert a.get_absolute_url() == "/members/jean-roy/"


def test_loader_gives_people_slugs(sitting):
    assert Person.objects.filter(slug="").count() == 0
    assert Person.objects.filter(slug="luc-martel").exists()


# -- list -------------------------------------------------------------------------------


def test_member_list_links_and_marks_presiding(client, sitting):
    html = client.get("/members/").content.decode()
    assert '<a href="/members/jane-alder/">Jane Alder</a>' in html
    assert "Riverbend—North Shore" in html
    lind = html.split('href="/members/rosa-lind/"')[1].split("</tr>")[0]
    assert ">chair<" in lind


def test_member_list_filters(client, sitting):
    html = client.get("/members/", {"q": "MARTEL"}).content.decode()
    assert "Luc Martel" in html and "Jane Alder" not in html
    html = client.get("/members/", {"q": "riverbend"}).content.decode()  # riding
    assert "Jane Alder" in html and "Luc Martel" not in html
    html = client.get("/members/", {"party": "BQ"}).content.decode()
    assert "Luc Martel" in html and "Jane Alder" not in html


def test_member_list_accent_insensitive(client):
    Person.objects.create(name="Bernard Généreux")
    s = Sitting.objects.create(parliament=45, session=1, number=1, date=dt.date(2025, 6, 2))
    Intervention.objects.create(sitting=s, sequence=1, kind="Debate", person=Person.objects.get())
    assert "Généreux" in client.get("/members/", {"q": "genereux"}).content.decode()


def test_member_list_sort_by_speeches(client, sitting):
    html = client.get("/members/", {"sort": "speeches"}).content.decode()
    order = [n for n in ("Luc Martel", "Jane Alder", "Sam Okafor") if n in html]
    counts = {
        p.name: analysis.member_speeches(p).count() for p in Person.objects.filter(name__in=order)
    }
    positions = sorted(order, key=html.index)
    assert [counts[n] for n in positions] == sorted(counts.values(), reverse=True)


# -- detail -----------------------------------------------------------------------------


def test_member_page(client, sitting):
    response = client.get("/members/sam-okafor/")
    assert response.status_code == 200
    html = response.content.decode()
    assert "<h1>Sam Okafor</h1>" in html
    assert "Secretary of State (Housing)" in html  # role from the label
    assert 'name="person" value="Sam Okafor"' in html  # search within their speeches
    assert 'id="member-month"' in html


def test_presiding_only_member(client, sitting):
    html = client.get("/members/rosa-lind/").content.decode()
    assert "only while presiding" in html
    assert "The Assistant Deputy Speaker" in html


def test_unknown_member_is_404(client):
    assert client.get("/members/nobody/").status_code == 404


def test_speech_page_links_to_member_but_not_chair(client, sitting):
    martel = Intervention.objects.filter(person__name="Luc Martel").exclude(house_id="").first()
    html = client.get(martel.get_absolute_url()).content.decode()
    assert 'href="/members/luc-martel/"' in html
    chair = Intervention.objects.filter(is_chair=True, person__isnull=False).exclude(house_id="")
    html = client.get(chair.first().get_absolute_url()).content.decode()
    assert "/members/rosa-lind/" not in html.split('class="speaker"')[1].split("</p>")[0]


# -- figures ----------------------------------------------------------------------------


def _speech(person, sitting, seq, kind="Debate", fr_words=0, en_words=0, chair=False):
    iv = Intervention.objects.create(
        sitting=sitting, sequence=seq, kind=kind, person=person, is_chair=chair
    )
    for i, (lang, n) in enumerate((("fr", fr_words), ("en", en_words))):
        if n:
            Paragraph.objects.create(
                intervention=iv,
                sequence=i,
                kind="speech",
                floor_language=lang,
                text_en=" ".join(["word"] * n),
            )
    return iv


def test_profile_counts_months_and_language():
    p = Person.objects.create(name="Ana Test", latest_party="BQ")
    jan = Sitting.objects.create(parliament=45, session=1, number=1, date=dt.date(2026, 1, 27))
    jan2 = Sitting.objects.create(parliament=45, session=1, number=2, date=dt.date(2026, 1, 28))
    mar = Sitting.objects.create(parliament=45, session=1, number=3, date=dt.date(2026, 3, 9))
    _speech(p, jan, 1, "Question", fr_words=900, en_words=100)
    _speech(p, jan2, 1, "Debate", fr_words=600)
    _speech(p, jan2, 2, "Interjection", en_words=5000)  # not a speech
    _speech(p, mar, 1, "Debate", en_words=5000, chair=True)  # presiding: not counted

    profile = analysis.member_profile(p)
    assert profile["speeches"] == 2 and profile["sittings"] == 2 and profile["chair"] == 1
    assert profile["by_kind"] == {"debate": 1, "questions": 1, "answers": 0, "statements": 0}
    month = profile["by_month"]
    assert month["months"] == ["2026-01", "2026-02", "2026-03"]
    assert month["series"][0]["values"] == [2, None, 0]  # February: no sittings
    assert month["denominators"] == [2, None, 1]
    # 1,500 of 1,600 words spoken in French; the interjection is not a speech paragraph
    # but it is measured with the member's speech (same rule as the Languages page)
    assert profile["language"]["share"] == round(100 * 1500 / 6600, 1)


def test_language_share_hidden_below_minimum():
    p = Person.objects.create(name="Few Words")
    s = Sitting.objects.create(parliament=45, session=1, number=1, date=dt.date(2026, 1, 27))
    _speech(p, s, 1, fr_words=50)
    assert analysis.member_profile(p)["language"]["share"] is None


def test_party_history_records_floor_crossing():
    p = Person.objects.create(name="Crosser Test", latest_party="Lib.")
    for n, (day, party) in enumerate(((1, "CPC"), (2, "CPC"), (20, "Lib.")), start=1):
        s = Sitting.objects.create(parliament=45, session=1, number=n, date=dt.date(2026, 2, day))
        Intervention.objects.create(sitting=s, sequence=1, kind="Debate", person=p, party=party)
    parties = analysis.member_profile(p)["parties"]
    assert [(r["value"], r["first"].day, r["last"].day) for r in parties] == [
        ("CPC", 1, 2),
        ("Lib.", 20, 20),
    ]


def test_member_topics_compare_with_house():
    p = Person.objects.create(name="Topic Test")
    model = TopicModel.objects.create(
        lang="en", is_active=True, n_topics=2, n_documents=100, vocabulary_size=10
    )
    housing = Topic.objects.create(model=model, number=1, terms=[["housing", 1]], share=0.25)
    fish = Topic.objects.create(model=model, number=2, terms=[["fish", 1]], share=0.75)
    s = Sitting.objects.create(parliament=45, session=1, number=1, date=dt.date(2026, 1, 27))
    for i in range(12):
        iv = Intervention.objects.create(sitting=s, sequence=i, kind="Debate", person=p)
        InterventionTopic.objects.create(
            intervention=iv, topic=housing if i < 9 else fish, weight=1
        )
    result = analysis.member_topics(p, model)
    assert result["total"] == 12
    assert result["topics"][0] == {
        "number": 1,
        "label": "housing",
        "n": 9,
        "share": 75.0,
        "house": 25.0,
    }


def test_member_topics_need_enough_speeches():
    p = Person.objects.create(name="Quiet Test")
    model = TopicModel.objects.create(lang="en", n_topics=1, n_documents=1, vocabulary_size=1)
    t = Topic.objects.create(model=model, number=1, terms=[["x", 1]], share=1)
    s = Sitting.objects.create(parliament=45, session=1, number=1, date=dt.date(2026, 1, 27))
    iv = Intervention.objects.create(sitting=s, sequence=1, kind="Debate", person=p)
    InterventionTopic.objects.create(intervention=iv, topic=t, weight=1)
    assert analysis.member_topics(p, model) == {"total": 1, "topics": []}
