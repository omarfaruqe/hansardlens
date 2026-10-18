import datetime as dt

import pytest
from django.core.management import call_command

from debates.bills import CODE_EN, CODE_FR, MOVED_EN, MOVED_FR, build_bills, stage_done, stage_moved
from debates.models import Bill, Division, Intervention, Paragraph, Person, Sitting

NB = "‑"  # non-breaking hyphen, common in Hansard
pytestmark = pytest.mark.django_db


class Day:
    """Builds a sitting intervention by intervention."""

    def __init__(self, number, date, parliament=45, session=1):
        self.sitting = Sitting.objects.create(
            parliament=parliament, session=session, number=number, date=date
        )
        self.seq = 0
        self.member = Person.objects.get_or_create(name="Ana Test")[0]

    def say(
        self,
        subject,
        text_en,
        text_fr="",
        order="Government Orders",
        kind="Debate",
        procedural=False,
    ):
        self.seq += 1
        iv = Intervention.objects.create(
            sitting=self.sitting,
            sequence=self.seq,
            kind="Procedural" if procedural else kind,
            order_title_en=order,
            subject_title_en=subject,
            subject_title_fr=f"FR {subject}" if subject else "",
            person=None if procedural else self.member,
            text_en=text_en,
        )
        Paragraph.objects.create(
            intervention=iv,
            sequence=1,
            kind="procedural" if procedural else "speech",
            text_en=text_en,
            text_fr=text_fr,
        )
        return iv

    def vote(self, number, at_sequence, subject=""):
        return Division.objects.create(
            sitting=self.sitting, number=number, sequence=at_sequence, subject_title_en=subject
        )


# -- text patterns ------------------------------------------------------------------------------


def test_bill_codes_with_any_hyphen():
    assert [m.groups() for m in CODE_EN.finditer(f"Bill C-37 and Bill S{NB}214")] == [
        ("C", "37"),
        ("S", "214"),
    ]
    assert CODE_FR.search(f"le projet de loi C{NB}4 est").groups() == ("C", "4")


def test_moved_motion_gives_code_and_long_title():
    m = MOVED_EN.search(
        "moved that Bill C-37, An Act respecting water, source water and wastewater, be read "
        "the second time and referred to a committee."
    )
    assert m.groups()[:2] == ("C", "37")
    assert m.group("title") == "An Act respecting water, source water and wastewater"
    fm = MOVED_FR.search(
        f"propose que le projet de loi C{NB}37, Loi concernant l'eau, soit lu pour la "
        "deuxième fois."
    )
    assert fm.group("title") == "Loi concernant l'eau"


@pytest.mark.parametrize(
    "text, moved, done",
    [
        ("moved that the bill be read the third time and passed.", "third", ""),
        ("moved that Bill C-4, An Act, be read the second time.", "second", ""),
        ("moved for leave to introduce Bill C-370, An Act to amend.", "introduction", ""),
        ("moved that the bill be concurred in at report stage.", "report", ""),
        ("(Bill read the third time and passed)", "", "third"),
        ("(Bill, as amended, concurred in at report stage)", "", "report"),
        ("(Motion agreed to, bill read the second time and referred to a committee)", "", "second"),
        ("(Motions agreed to, bill read the first time and printed)", "", "introduction"),
        ("Mr. Speaker, I support this bill.", "", ""),
    ],
)
def test_stages(text, moved, done):
    assert (stage_moved(text), stage_done(text)) == (moved, done)


# -- linking ------------------------------------------------------------------------------------


def test_bill_found_and_followed_across_sittings():
    d1 = Day(10, dt.date(2025, 6, 2))
    d1.say(
        "Clean Water Act",
        "moved that Bill C-37, An Act respecting water, be read the second time and referred "
        "to a committee.",
        f"propose que le projet de loi C{NB}37, Loi concernant l'eau, soit lu pour la "
        "deuxième fois.",
    )
    d1.say("", "Mr. Speaker, water matters.")  # untitled continuation
    d1.say("Health", "Mr. Speaker, about hospitals.", order="Oral Questions")
    d2 = Day(11, dt.date(2025, 6, 9))
    d2.say("Clean Water Act", "Mr. Speaker, as I was saying, the bill helps.")
    d2.say("Clean Water Act", "moved that the bill be read the third time and passed.")
    d2.say("Clean Water Act", "(Bill read the third time and passed)", procedural=True)

    assert build_bills() == {"bills": 1, "linked": 5}
    bill = Bill.objects.get()
    assert (bill.code, bill.number, bill.short_title_en) == ("C-37", 37, "Clean Water Act")
    assert bill.long_title_en == "An Act respecting water"
    assert bill.long_title_fr == "Loi concernant l'eau"
    assert (bill.first_date, bill.last_date) == (dt.date(2025, 6, 2), dt.date(2025, 6, 9))
    assert bill.speeches == 4
    assert [(e["stage"], e["event"], e["passed"]) for e in bill.timeline] == [
        ("second", "moved", False),
        ("third", "moved", False),
        ("third", "done", True),
    ]
    assert not Intervention.objects.get(subject_title_en="Health").bill
    assert bill.legisinfo_url("fr") == "https://www.parl.ca/legisinfo/fr/bill/45-1/c-37"


def test_shared_heading_goes_to_the_bill_named():
    d1 = Day(10, dt.date(2025, 6, 2))
    d1.say(
        "Criminal Code",
        "moved that Bill C-301, An Act to amend the Criminal Code, be read "
        "the second time and referred to a committee.",
    )
    d1.say(
        "Criminal Code",
        "moved that Bill C-302, An Act to amend the Criminal Code (theft), "
        "be read the second time and referred to a committee.",
    )
    d2 = Day(11, dt.date(2025, 6, 9))
    d2.say("Criminal Code", "Mr. Speaker, Bill C-302 protects shops. Bill C-302 is needed.")
    d3 = Day(12, dt.date(2025, 6, 10))
    d3.say("Criminal Code", "Mr. Speaker, Bill S-205 is a Senate bill about something else.")
    build_bills()
    c301, c302 = Bill.objects.get(code="C-301"), Bill.objects.get(code="C-302")
    assert list(c301.interventions.values_list("sequence", flat=True)) == [1]
    assert c302.interventions.count() == 2  # its introduction and the 9 June debate
    assert Intervention.objects.get(sitting=d3.sitting).bill is None  # names neither


def test_debate_found_from_unnamed_stage_and_dominant_bill():
    d = Day(20, dt.date(2025, 10, 8))
    d.say("Magnitsky Act", "Mr. Speaker, Bill C-219 matters.")
    d.say("Magnitsky Act", "Bill C-219 is overdue.")
    d.say("Magnitsky Act", "moved that the bill be read the third time and passed.")
    d.say("Supplementary Estimates", "Bill C-60 is the appropriation bill.")
    d.say("Supplementary Estimates", "Bill C-60, again.")
    d.say("Supplementary Estimates", "(Bill read the second time)", procedural=True)
    build_bills()
    assert list(Bill.objects.values_list("code", "short_title_en", "long_title_en")) == [
        ("C-219", "Magnitsky Act", "")
    ]


def test_vote_linked_with_stage():
    d = Day(30, dt.date(2025, 6, 2))
    d.say(
        "Clean Water Act",
        "moved that Bill C-37, An Act respecting water, be read the "
        "second time and referred to a committee.",
    )
    divided = d.say(
        "", "(The House divided on the motion, which was agreed to ...)", procedural=True
    )
    vote = d.vote(5, divided.sequence)
    other = Day(31, dt.date(2025, 6, 3))
    other.say("Business of Supply", "Mr. Speaker, the opposition motion.")
    unrelated = other.vote(6, 1)
    build_bills()
    vote.refresh_from_db()
    unrelated.refresh_from_db()
    assert (vote.bill.code, vote.bill_stage) == ("C-37", "second")
    assert unrelated.bill is None


def test_rebuild_is_idempotent_and_drops_stale_bills():
    d = Day(10, dt.date(2025, 6, 2))
    iv = d.say(
        "Clean Water Act",
        "moved that Bill C-37, An Act respecting water, be read the "
        "second time and referred to a committee.",
    )
    call_command("build_bills", stdout=open("/dev/null", "w"))
    call_command("build_bills", stdout=open("/dev/null", "w"))
    assert Bill.objects.count() == 1
    Paragraph.objects.filter(intervention=iv).update(text_en="Mr. Speaker, water.")
    build_bills()
    assert Bill.objects.count() == 0
    assert Intervention.objects.filter(bill__isnull=False).count() == 0


def test_bill_moved_under_a_generic_heading():
    d = Day(40, dt.date(2021, 6, 17), parliament=43, session=2)
    d.say(
        "Main Estimates, 2021-22",
        "moved that Bill C-33, An Act for granting to Her Majesty "
        "certain sums of money, be read the second time and referred to a committee.",
    )
    d.say("Main Estimates, 2021-22", "(Bill read the second time)", procedural=True)
    later = Day(41, dt.date(2021, 6, 18), parliament=43, session=2)
    later.say("Main Estimates, 2021-22", "Mr. Speaker, about the estimates in general.")
    build_bills()
    bill = Bill.objects.get()
    assert bill.short_title_en == "An Act for granting to Her Majesty certain sums of money"
    assert bill.interventions.count() == 2  # not the later debate on the estimates
