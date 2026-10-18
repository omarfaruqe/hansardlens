import datetime as dt

import pytest


@pytest.fixture
def bill(db):
    """Bill C-37 moved at second reading on 2 June 2025 and debated again on 9 June,
    with a recorded vote at second reading and a speech with House id 777."""
    from debates.bills import build_bills
    from debates.models import Bill
    from debates.tests.test_bills import NB, Day

    d1 = Day(10, dt.date(2025, 6, 2))
    d1.say(
        "Clean Water Act",
        "moved that Bill C-37, An Act respecting water, be read the second time and referred "
        "to a committee.",
        f"propose que le projet de loi C{NB}37, Loi concernant l'eau, soit lu pour la "
        "deuxième fois.",
    )
    d1.say(
        "",
        "(Motion agreed to, bill read the second time and referred to a committee)",
        procedural=True,
    )
    divided = d1.say(
        "", "(The House divided on the motion, which was agreed to ...)", procedural=True
    )
    d1.vote(7, divided.sequence)
    d2 = Day(11, dt.date(2025, 6, 9))
    iv = d2.say("Clean Water Act", "Mr. Speaker, the bill helps.")
    iv.house_id = "777"
    iv.save()
    build_bills()
    return Bill.objects.get()
