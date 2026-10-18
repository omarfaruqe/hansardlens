"""Find the bills debated in the House and link them to their debates and votes.

A bill is found from the motion that moves it, which names it and gives its long title:

    moved that Bill C-37, An Act respecting water ..., be read the second time and ...
    propose que le projet de loi C‑37, Loi concernant l'eau ..., soit lu pour la ...
    moved for leave to introduce Bill C-370, An Act to amend the Criminal Code ...

The heading of the debate where that happens is the bill's short title ("First Nations
Clean Water Act"). Every debate with that heading in the same session is a debate on the
bill. Some headings are shared ("Criminal Code" for many private members' bills): such a
debate goes to the bill it names most, and is left unlinked when it names none.
Later stages often say only "moved that the bill be read the third time"; they belong to
the bill of the debate they are in. Recorded votes go to the bill of their debate too.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q

from .models import Bill, Division, Intervention, Paragraph

HYPHEN = r"[-‐‑‒–]"
CODE_EN = re.compile(rf"\bBills?\s+([CS]){HYPHEN}\s?(\d{{1,4}})\b")
CODE_FR = re.compile(rf"\bprojets? de loi\s+([CS]){HYPHEN}\s?(\d{{1,4}})\b", re.IGNORECASE)
# "moved that Bill C-37, An Act ..., be read the second time" (title may lack the comma)
MOVED_EN = re.compile(
    rf"moved that Bill\s+([CS]){HYPHEN}\s?(\d{{1,4}}),\s*(?P<title>An Act\b.+?),?\s+be\s+"
    r"(?:now\s+)?(?:read|concurred|referred)",
    re.IGNORECASE,
)
INTRODUCE_EN = re.compile(
    rf"leave to introduce Bill\s+([CS]){HYPHEN}\s?(\d{{1,4}}),\s*(?P<title>An Act\b[^.]+)",
    re.IGNORECASE,
)
MOVED_FR = re.compile(
    rf"projet de loi\s+([CS]){HYPHEN}\s?(\d{{1,4}}),\s*(?P<title>Loi\b.+?),?\s+soit\s",
    re.IGNORECASE,
)
INTRODUCE_FR = re.compile(
    rf"(?:déposer|présenter) le projet de loi\s+([CS]){HYPHEN}\s?(\d{{1,4}}),\s*"
    r"(?P<title>Loi\b[^.]+)",
    re.IGNORECASE,
)
# Stage moved in a motion, named or not: "... be read the third time and passed"
STAGE_MOVED = re.compile(
    r"moved (?:for leave to introduce|that (?:Bill\s+[CS]\S*|the bill)[^.]*?be\s+(?:now\s+)?"
    r"(?:read (?:a|the) (?P<reading>first|second|third) time|(?P<report>concurred in at "
    r"report stage)|(?P<committee>referred forthwith to)))",
    re.IGNORECASE,
)
# Outcomes printed by the House: "(Bill read the third time and passed)"
STAGE_DONE = re.compile(
    r"bill (?:deemed )?read (?:a|the) (?P<reading>first|second|third) time"
    r"(?P<passed> and passed)?|(?P<report>bill(?:, as amended,)? concurred in at report stage)",
    re.IGNORECASE,
)
STAGES = ("introduction", "second", "committee", "report", "third")
# Headings that hold motions about several bills or none (supply, estimates, routine).
NOT_A_BILL = re.compile(
    r"supply|estimates|government business|business of the house|privilege|point of order|"
    r"routine|petitions|questions|statements|motions?\b|committees? of the house",
    re.IGNORECASE,
)


def _capital(title: str) -> str:
    title = " ".join(title.split())
    return title[:1].upper() + title[1:]


def code_of(letter: str, number: str) -> str:
    return f"{letter.upper()}-{int(number)}"


def stage_moved(text: str) -> str:
    m = STAGE_MOVED.search(text)
    if not m:
        return ""
    if m.group("reading"):
        return {"first": "introduction"}.get(m.group("reading").lower(), m.group("reading").lower())
    if m.group("report"):
        return "report"
    if m.group("committee"):
        return "committee"
    return "introduction"  # leave to introduce


def stage_done(text: str) -> str:
    m = STAGE_DONE.search(text)
    if not m:
        return ""
    if m.group("reading"):
        return {"first": "introduction"}.get(m.group("reading").lower(), m.group("reading").lower())
    return "report"


@dataclass
class Section:
    """Consecutive debate under one heading in one sitting."""

    sitting_id: int
    parliament: int
    session: int
    date: object
    number: int  # sitting number
    subject_en: str
    subject_fr: str
    interventions: list[int] = field(default_factory=list)
    named: Counter = field(default_factory=Counter)  # bill codes named in the debate
    moved: set[str] = field(default_factory=set)  # bills moved or introduced here
    moved_by: dict[int, str] = field(default_factory=dict)  # intervention -> bill it moves
    events: list[dict] = field(default_factory=list)  # stage events (code may be None)


def _sections():
    """Walk all interventions in order. Each titled heading starts a section; an untitled
    one continues the previous subject of the same order of business, as in Hansard."""
    rows = (
        Intervention.objects.order_by("sitting__date", "sitting_id", "sequence")
        .values_list(
            "id",
            "sequence",
            "sitting_id",
            "sitting__parliament",
            "sitting__session",
            "sitting__number",
            "sitting__date",
            "order_title_en",
            "subject_title_en",
            "subject_title_fr",
        )
        .iterator(chunk_size=5000)
    )
    sections: dict[tuple, Section] = {}
    of_intervention: dict[int, tuple] = {}
    at: dict[tuple, tuple] = {}  # (sitting, sequence) -> section, for votes
    count = 0
    last = (None, None, "", "", None, "")  # sitting, order, subject, subject_fr, key, raw
    for iv_id, seq, sitting_id, parl, sess, num, date, order, subject_en, subject_fr in rows:
        if (sitting_id, order) != last[:2]:
            last = (sitting_id, order, "", "", None, "")
        if subject_en and subject_en != last[5]:
            count += 1
            last = (sitting_id, order, subject_en, subject_fr, (sitting_id, count), subject_en)
        elif not subject_en:
            last = last[:5] + ("",)  # untitled: same section; a repeated title starts anew
        key = last[4]
        if key is None:
            continue
        if key not in sections:
            sections[key] = Section(sitting_id, parl, sess, date, num, last[2], last[3])
        sections[key].interventions.append(iv_id)
        of_intervention[iv_id] = key
        at[(sitting_id, seq)] = key
    return sections, of_intervention, at


def find_bills():
    """-> (bills by (parliament, session, code), section assignments, mention counts)."""
    sections, of_intervention, at = _sections()
    found: dict[tuple, dict] = {}
    mentions: Counter = Counter()

    candidates = (
        Paragraph.objects.filter(
            Q(text_en__iregex=r"bills?\s+[CS]")
            | Q(text_en__iregex=r"(moved|read).{0,60}time")
            | Q(text_en__icontains="report stage")
            | Q(text_fr__iregex=r"projets? de loi\s+[CS]")
        )
        .order_by("intervention__sitting__date", "intervention__sequence", "sequence")
        .values_list("intervention_id", "intervention__sequence", "text_en", "text_fr")
        .iterator(chunk_size=2000)
    )
    for iv_id, seq, text_en, text_fr in candidates:
        key = of_intervention.get(iv_id)
        section = sections.get(key) if key else None
        codes_en = {code_of(*m.groups()) for m in CODE_EN.finditer(text_en)}
        codes = codes_en or {code_of(*m.groups()) for m in CODE_FR.finditer(text_fr)}
        if section is None:
            continue
        for c in codes:
            mentions[(section.parliament, section.session, c)] += 1
            section.named[c] += 1
        for regex_en, regex_fr in ((MOVED_EN, MOVED_FR), (INTRODUCE_EN, INTRODUCE_FR)):
            m = regex_en.search(text_en)
            if m:
                code = code_of(m.group(1), m.group(2))
                info = found.setdefault(
                    (section.parliament, section.session, code),
                    {"long_en": "", "long_fr": "", "titles": Counter()},
                )
                info["long_en"] = info["long_en"] or _capital(m.group("title"))
                fm = regex_fr.search(text_fr or "")
                if fm and code_of(fm.group(1), fm.group(2)) == code:
                    info["long_fr"] = info["long_fr"] or _capital(fm.group("title"))
                info["titles"][(section.subject_en, section.subject_fr)] += 1
                section.moved.add(code)
                section.moved_by[iv_id] = code
        moved, done = stage_moved(text_en), stage_done(text_en)
        if moved or done:
            named = sorted(codes_en)
            section.events.append(
                {
                    "code": named[0] if len(named) == 1 else None,
                    "stage": moved or done,
                    "event": "moved" if moved else "done",
                    "passed": bool(done and "passed" in text_en.lower()),
                    "sequence": seq,
                    "intervention": iv_id,
                }
            )

    # A debate whose stages are moved without naming the bill ("moved that the bill be
    # read the third time") and that names one bill far more than any other is that
    # bill's debate, even when the motion naming it was in a sitting not loaded.
    for s in sections.values():
        if s.moved or not s.events or NOT_A_BILL.search(s.subject_en):
            continue
        top = s.named.most_common(2)
        if top and top[0][1] >= 2 and (len(top) == 1 or top[0][1] >= 2 * top[1][1]):
            code = top[0][0]
            info = found.setdefault(
                (s.parliament, s.session, code), {"long_en": "", "long_fr": "", "titles": Counter()}
            )
            info["titles"][(s.subject_en, s.subject_fr)] += 1
            s.moved.add(code)

    # Which bills each heading stands for in a session.
    by_title: dict[tuple, set[str]] = defaultdict(set)
    for (parl, sess, code), info in found.items():
        for (title_en, _), _n in info["titles"].items():
            # A generic heading ("Main Estimates, 2021-22" for an appropriation bill)
            # links only the debate where the bill is moved, not every debate under it.
            if not NOT_A_BILL.search(title_en):
                by_title[(parl, sess, title_en)].add(code)

    assignment: dict[tuple, str] = {}
    for key, s in sections.items():
        options = by_title.get((s.parliament, s.session, s.subject_en), set()) | s.moved
        if not options:
            continue
        if s.moved & options:
            # bills moved here: the first one; others are split off per intervention
            code = (
                next(c for c in s.moved_by.values() if c in options)
                if s.moved_by
                else (sorted(s.moved & options)[0])
            )
        else:
            # By heading alone: the only bill with that heading when the debate names
            # none, else the heading's bill that it names most, if no other bill is
            # named more.
            most = max(s.named.values(), default=0)
            if most == 0:
                code = next(iter(options)) if len(options) == 1 else None
            else:
                top = [c for c in options if s.named[c] == most]
                code = top[0] if len(top) == 1 else None
        if code:
            assignment[key] = code
    return found, sections, assignment, mentions, at


@transaction.atomic
def build_bills() -> dict:
    """Rebuild bills and their links from scratch. Returns counts."""
    found, sections, assignment, mentions, at = find_bills()
    Intervention.objects.filter(bill__isnull=False).update(bill=None)
    Division.objects.filter(bill__isnull=False).update(bill=None, bill_stage="")

    bills: dict[tuple, Bill] = {}
    keep = []
    for (parl, sess, code), info in found.items():
        (title_en, title_fr), _ = info["titles"].most_common(1)[0]
        if NOT_A_BILL.search(title_en):
            # the heading is not the bill's title: use the long title instead
            title_en, title_fr = info["long_en"] or title_en, info["long_fr"] or title_fr
        bill, _ = Bill.objects.update_or_create(
            parliament=parl,
            session=sess,
            code=code,
            defaults={
                "number": int(code.split("-")[1]),
                "short_title_en": title_en[:300],
                "short_title_fr": title_fr[:300],
                "long_title_en": info["long_en"],
                "long_title_fr": info["long_fr"],
                "mentions": mentions[(parl, sess, code)],
            },
        )
        bills[(parl, sess, code)] = bill
        keep.append(bill.id)
    Bill.objects.exclude(id__in=keep).delete()

    timelines: dict[int, list] = defaultdict(list)
    dates: dict[int, list] = defaultdict(list)
    linked = 0
    for key, code in assignment.items():
        s = sections[key]
        bill = bills[(s.parliament, s.session, code)]
        # Several bills introduced under one heading: each intervention goes to the bill
        # it moves, and the House's reply after it to the same bill.
        owner, current = {}, code
        for iv_id in s.interventions:
            current = s.moved_by.get(iv_id, current if len(s.moved) > 1 else code)
            owner[iv_id] = current
        for c in set(owner.values()):
            target = bills[(s.parliament, s.session, c)]
            linked += Intervention.objects.filter(
                id__in=[i for i, o in owner.items() if o == c]
            ).update(bill=target)
            dates[target.id].append(s.date)
        for e in s.events:
            e_code = e["code"] or owner.get(e["intervention"], code)
            target = bills.get((s.parliament, s.session, e_code))
            if target is not None:
                timelines[target.id].append(
                    {
                        "date": s.date.isoformat(),
                        "stage": e["stage"],
                        "event": e["event"],
                        "passed": e["passed"],
                        "sitting": [s.parliament, s.session, s.number],
                        "sequence": e["sequence"],
                    }
                )
    # A vote belongs to the debate holding "(The House divided on ...)".
    for division in Division.objects.all():
        key = at.get((division.sitting_id, division.sequence))
        code = assignment.get(key)
        if code:
            s = sections[key]
            before = [e for e in s.events if e["sequence"] <= division.sequence]
            after = [e for e in s.events if e["sequence"] > division.sequence]
            moved = [e for e in before if e["event"] == "moved"]
            done = [e for e in after if e["event"] == "done"]
            division.bill = bills[(s.parliament, s.session, code)]
            # the stage moved before the vote, else the one the House records after it
            division.bill_stage = (moved or done[:1] or [{"stage": ""}])[-1]["stage"]
            division.save(update_fields=["bill", "bill_stage"])

    for bill in bills.values():
        days = dates.get(bill.id, [])
        bill.first_date, bill.last_date = (min(days), max(days)) if days else (None, None)
        bill.timeline = _dedupe(timelines.get(bill.id, []))
        bill.speeches = bill.interventions.filter(person__isnull=False, is_chair=False).count()
        bill.save(update_fields=["first_date", "last_date", "timeline", "speeches"])
    return {"bills": len(bills), "linked": linked}


def _dedupe(events: list[dict]) -> list[dict]:
    """One entry per (date, stage, event), in date order."""
    seen, out = set(), []
    for e in sorted(events, key=lambda e: (e["date"], e["sequence"])):
        key = (e["date"], e["stage"], e["event"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
