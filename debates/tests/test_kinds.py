"""Statements, questions and answers that the House typed "Debate"."""

import datetime as dt

import pytest

from debates import kinds
from debates.models import Intervention, Person, Sitting


def row(pk, house_type="Debate", rubric=kinds.QUESTION_PERIOD, person=None, role="", chair=False):
    return {
        "id": pk,
        "house_type": house_type,
        "rubric": rubric,
        "is_chair": chair,
        "person_id": person,
        "speaker_db_id": "",
        "speaker_role": role,
    }


def test_statements_by_members():
    assert kinds.infer([row(1, rubric=kinds.STATEMENTS, person=1)]) == {1: "Statement"}


def test_question_period_split_by_who_answers():
    rows = [
        row(1, person=1, role="Leader of the Opposition"),  # asks
        row(2, person=2, role="Minister of Justice and Attorney General of Canada"),
        row(3, person=1),  # short label, still asking
        row(4, person=2),  # short label: same minister, answering
        row(5, person=3, role="Parliamentary Secretary to the Minister of Health"),
        row(6, person=4, house_type="Answer"),  # typed by the House
        row(7, person=4),  # so this one is an answer too
        row(8, chair=True, person=5),  # the Speaker is left alone
        row(9, house_type="Interjection", person=1),  # other types are left alone
        row(10, person=6, role="Prime Minister"),
    ]
    assert kinds.infer(rows) == {
        1: "Question",
        2: "Answer",
        3: "Question",
        4: "Answer",
        5: "Answer",
        7: "Answer",
        10: "Answer",
    }


def test_other_parts_of_the_day_are_left_alone():
    assert kinds.infer([row(1, rubric="Other", person=1)]) == {}


def test_speakers_without_a_person_are_told_apart():
    rows = [
        {**row(1, role="Minister of Finance"), "speaker_db_id": "77"},
        {**row(2), "speaker_db_id": "77"},
        row(3),  # no person, no id: not the minister
    ]
    assert kinds.infer(rows) == {1: "Answer", 2: "Answer", 3: "Question"}


@pytest.mark.django_db
def test_apply_sets_kinds_and_keeps_the_house_type():
    sitting = Sitting.objects.create(parliament=42, session=1, number=1, date=dt.date(2016, 1, 1))
    minister = Person.objects.create(name="Mina Ster")
    member = Person.objects.create(name="Mem Ber")

    def make(seq, person, rubric, role=""):
        return Intervention.objects.create(
            sitting=sitting,
            sequence=seq,
            kind="Debate",
            house_type="Debate",
            rubric=rubric,
            person=person,
            speaker_role=role,
        )

    q = make(1, member, kinds.QUESTION_PERIOD)
    a = make(2, minister, kinds.QUESTION_PERIOD, role="Minister of Health")
    s = make(3, member, kinds.STATEMENTS)
    d = make(4, member, "Other")
    assert kinds.apply(Intervention, [sitting.id]) == 3
    got = {iv.id: (iv.kind, iv.house_type) for iv in Intervention.objects.all()}
    assert got == {
        q.id: ("Question", "Debate"),
        a.id: ("Answer", "Debate"),
        s.id: ("Statement", "Debate"),
        d.id: ("Debate", "Debate"),
    }
