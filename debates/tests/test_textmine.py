"""Topic and term-shift methods on a small synthetic corpus with two clear subjects."""

import datetime as dt

import numpy as np
import pytest
from django.core.management import call_command

from debates import textmine
from debates.models import Intervention, InterventionTopic, Person, Sitting, TermShift, TopicModel

pytestmark = pytest.mark.django_db

FISH = "salmon fishery harvesters ocean boats wharf coastal quota lobster"
HOMES = "housing rent mortgage homes tenants apartments builders zoning landlords"


def make_corpus(per_subject=30, start=dt.date(2025, 1, 6)):
    """Speeches alternate subjects; fisheries speeches become rare after the 40th day."""
    alice = Person.objects.create(name="Alice Test", latest_party="Lib.")
    bob = Person.objects.create(name="Bob Test", latest_party="CPC")
    rng = np.random.default_rng(0)
    seq = 0
    for day in range(per_subject):
        date = start + dt.timedelta(days=2 * day)
        sitting = Sitting.objects.create(parliament=45, session=1, number=day + 1, date=date)
        for words, person, party in ((FISH, alice, "Lib."), (HOMES, bob, "CPC")):
            if words is FISH and day >= 20 and day % 3:
                continue  # fisheries fades in the recent window
            vocab = words.split()
            text = " ".join(rng.choice(vocab, size=70))
            seq += 1
            Intervention.objects.create(
                sitting=sitting,
                sequence=seq,
                house_id=str(seq),
                kind="Debate",
                person=person,
                party=party,
                text_en=text,
                word_count_en=70,
            )


def test_log_odds_z_signs_and_symmetry():
    a = np.array([50.0, 5.0, 20.0])
    b = np.array([5.0, 50.0, 20.0])
    z = textmine.log_odds_z(a, b, np.ones(3))
    assert z[0] > 3 and z[1] < -3 and abs(z[2]) < 1e-9
    assert np.allclose(z, -textmine.log_odds_z(b, a, np.ones(3)))


def test_prior_shrinks_rare_terms():
    a, b = np.array([3.0, 300.0]), np.array([1.0, 100.0])
    z = textmine.log_odds_z(a, b, np.array([10.0, 10.0]))
    assert z[1] > z[0]  # same 3:1 ratio, far more evidence


def test_documents_skip_chairs_short_and_procedural():
    make_corpus(per_subject=2)
    iv = Intervention.objects.first()
    Intervention.objects.create(
        sitting=iv.sitting, sequence=99, kind="Procedural", text_en="x " * 80, word_count_en=80
    )
    Intervention.objects.create(
        sitting=iv.sitting,
        sequence=100,
        kind="Debate",
        is_chair=True,
        text_en="x " * 80,
        word_count_en=80,
    )
    Intervention.objects.create(
        sitting=iv.sitting, sequence=101, kind="Debate", text_en="short", word_count_en=1
    )
    ids = {d[0] for d in textmine.documents("en", min_words=60)}
    assert ids == set(Intervention.objects.filter(sequence__lt=99).values_list("id", flat=True))


def test_fit_topics_separates_subjects():
    make_corpus()
    model = textmine.fit_topics(
        textmine.TopicParams(n_topics=2, min_df=2, max_df=0.9, min_words=10), log=lambda *_: None
    )
    assert model.is_active and model.n_documents == Intervention.objects.count()
    tops = [{t for t, _ in topic.terms[:5]} for topic in model.topics.all()]
    assert any(top <= set(FISH.split()) for top in tops)
    assert any(top <= set(HOMES.split()) for top in tops)
    # every speech is assigned to the topic of its own subject
    for a in InterventionTopic.objects.select_related("topic", "intervention"):
        words = set(a.intervention.text_en.split())
        top = {t for t, _ in a.topic.terms[:5]}
        assert top & words
    assert sum(t.share for t in model.topics.all()) == pytest.approx(1, abs=0.01)


def test_refit_replaces_previous_model():
    make_corpus()
    p = textmine.TopicParams(n_topics=2, min_df=2, max_df=0.9, min_words=10)
    first = textmine.fit_topics(p, log=lambda *_: None)
    second = textmine.fit_topics(p, log=lambda *_: None)
    assert list(TopicModel.objects.values_list("id", flat=True)) == [second.id]
    assert not InterventionTopic.objects.filter(topic__model_id=first.id).exists()


def test_too_few_documents():
    make_corpus(per_subject=1)
    with pytest.raises(ValueError):
        textmine.fit_topics(
            textmine.TopicParams(n_topics=5, min_df=1, min_words=10), log=lambda *_: None
        )


def test_term_shifts_find_the_fading_subject():
    make_corpus()
    end = Sitting.objects.order_by("-date").first().date
    shift = textmine.compute_shifts(
        textmine.ShiftParams(recent_days=20, base_days=60, min_count=5, min_words=10),
        end,
        log=lambda *_: None,
    )
    rising = {r["term"] for r in shift.rising}
    fading = {r["term"] for r in shift.fading}
    assert fading & set(FISH.split())
    assert not rising & set(FISH.split())
    row = shift.fading[0]
    assert row["rate_base"] > row["rate_recent"]
    assert shift.words_recent > 0 and shift.words_base > 0


def test_dedupe_drops_word_covered_by_phrase():
    vocab = np.array(["drinking", "drinking water", "water", "food"])
    counts = np.array([10, 9, 40, 5])
    assert textmine._dedupe([0, 1, 2, 3], vocab, counts) == [1, 2, 3]


def test_commands(capsys):
    make_corpus()
    call_command("build_topics", topics=2, min_df=2, max_df=0.9, min_words=10)
    assert "Model with 2 topics" in capsys.readouterr().out
    call_command("build_term_shifts", recent_days=20, base_days=60, min_count=5)
    assert TermShift.objects.count() == 1


def test_topic_pages(client):
    make_corpus()
    textmine.fit_topics(
        textmine.TopicParams(n_topics=2, min_df=2, max_df=0.9, min_words=10), log=lambda *_: None
    )
    html = client.get("/topics/").content.decode()
    assert "2 topics found" in html
    html = client.get("/topics/1/").content.decode()
    assert "Words that define it" in html and 'id="topic-month"' in html
    assert "Share of each party" not in html  # parties below 200 speeches are hidden
    assert client.get("/topics/9/").status_code == 404


def test_pages_before_anything_is_built(client):
    assert b"No topic model has been built yet" in client.get("/topics/").content
    assert b"Nothing computed yet" in client.get("/new/").content
    assert client.get("/topics/1/").status_code == 404


def test_whats_new_page(client):
    make_corpus()
    call_command("build_term_shifts", recent_days=20, base_days=60, min_count=5)
    html = client.get("/new/").content.decode()
    assert "Used more" in html and "Used less" in html and "/trends/?text=en&amp;t1=" in html
