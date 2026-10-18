"""Recorded votes (divisions): store them, match the printed names to people, and mark
votes that differ from the majority of the member's party.

Vote lists print surnames, with the riding when two members share one:
"Falk (Provencher)". Each name carries the House's member id (DbId), the same id the
member's speeches carry, so most names match through the speeches. Ministers speak
under a role id, so the rest are matched by surname (and riding) among the members who
spoke in the same Parliament. Names that match nobody keep their printed label.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from django.db.models import Max, Min

from .models import Division, Intervention, Person, Sitting, Vote

# A party line needs at least this many of the party's members voting yea or nay.
MIN_PARTY_VOTERS = 5
NO_PARTY = {"", "Ind.", "Ind"}
LABEL_RE = re.compile(r"^(?P<surname>.+?)\s*(?:\((?P<riding>[^)]*)\))?$")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[-‐‑‒–—'’.]", " ", text).split())


def store_divisions(sitting: Sitting, merged, cache: dict | None = None) -> int:
    """Replace the divisions of one sitting with those of a merged document. Names are
    matched and party lines marked before saving, so each vote is written once."""
    sitting.divisions.all().delete()
    votes = []
    for d in merged.divisions:
        division = Division.objects.create(
            sitting=sitting,
            number=d.number,
            house_id=d.house_id,
            sequence=d.position + 1,  # interventions are numbered from 1
            rubric=d.rubric,
            order_title_en=d.order_title_en[:300],
            order_title_fr=d.order_title_fr[:300],
            subject_title_en=d.subject_title_en[:500],
            subject_title_fr=d.subject_title_fr[:500],
            qualifier_en=d.qualifier_en[:500],
            qualifier_fr=d.qualifier_fr[:500],
            object_en=d.object_en[:300],
            object_fr=d.object_fr[:300],
            result=d.result,
            time=d.time,
            yeas=len(d.votes["yea"]),
            nays=len(d.votes["nay"]),
            paired=len(d.votes["paired"]),
        )
        division.sitting = sitting
        for choice, names in d.votes.items():
            votes += [
                Vote(division=division, house_db_id=db_id, label=label[:200], choice=choice)
                for db_id, label in names
            ]
    _match(votes, cache if cache is not None else {})
    _party_lines(votes)
    Vote.objects.bulk_create(votes, batch_size=2000)
    return len(merged.divisions)


# -- matching -----------------------------------------------------------------------------


def _id_map(db_ids: set[str]) -> dict[str, int]:
    """House member id -> person, from speeches (ids that point to one person only)."""
    seen: dict[str, set[int]] = defaultdict(set)
    rows = (
        Intervention.objects.filter(speaker_db_id__in=db_ids, person__isnull=False)
        .values_list("speaker_db_id", "person")
        .distinct()
    )
    for db_id, person in rows:
        seen[db_id].add(person)
    return {db_id: next(iter(p)) for db_id, p in seen.items() if len(p) == 1}


def _members(parliament: int, cache: dict) -> dict:
    """Who spoke as a member in one Parliament: surname index, ridings and party spans."""
    key = ("members", parliament)
    if key not in cache:
        rows = (
            Intervention.objects.filter(
                sitting__parliament=parliament, person__isnull=False, is_chair=False
            )
            .values("person", "person__name", "party", "riding")
            .annotate(first=Min("sitting__date"), last=Max("sitting__date"))
        )
        names, ridings, spans = {}, defaultdict(set), defaultdict(list)
        for r in rows:
            names[r["person"]] = fold(r["person__name"])
            if r["riding"]:
                ridings[r["person"]].add(fold(r["riding"]))
            if r["party"]:
                spans[r["person"]].append((r["first"], r["last"], r["party"]))
        cache[key] = {"names": names, "ridings": ridings, "spans": spans}
    return cache[key]


def _by_surname(label: str, members: dict) -> int | None:
    match = LABEL_RE.match(label.strip())
    if not match:
        return None
    surname, riding = fold(match.group("surname")), fold(match.group("riding") or "")
    found = [
        pid
        for pid, name in members["names"].items()
        if name == surname or name.endswith(" " + surname)
    ]
    if riding:
        found = [pid for pid in found if riding in members["ridings"].get(pid, ())]
    return found[0] if len(found) == 1 else None


def _party(person_id: int, date, members: dict, fallback: str) -> str:
    spans = members["spans"].get(person_id)
    if not spans:
        return fallback
    for first, last, party in spans:
        if first <= date <= last:
            return party
    return min(spans, key=lambda s: min(abs((s[0] - date).days), abs((s[1] - date).days)))[2]


def _match(votes: list[Vote], cache: dict, taken=None) -> list[Vote]:
    """Set person and party on votes that can be matched; returns those votes."""
    ids = _id_map({v.house_db_id for v in votes if v.house_db_id})
    if "latest" not in cache:
        cache["latest"] = dict(Person.objects.values_list("id", "latest_party"))
    taken = taken if taken is not None else defaultdict(set)  # division -> people matched
    matched = []
    for v in votes:
        sitting = v.division.sitting
        members = _members(sitting.parliament, cache)
        person = ids.get(v.house_db_id) or _by_surname(v.label, members)
        if person is None or person in taken[v.division_id]:
            continue
        taken[v.division_id].add(person)
        v.person_id = person
        v.party = _party(person, sitting.date, members, cache["latest"].get(person, ""))
        matched.append(v)
    return matched


def _party_lines(votes: list[Vote]) -> list[Vote]:
    """against_party = the vote differs from what most of the member's party voted.
    `votes` must hold every vote of the divisions concerned. Returns changed votes."""
    tally: dict[tuple[int, str], dict[str, int]] = defaultdict(lambda: {"yea": 0, "nay": 0})
    for v in votes:
        if v.party not in NO_PARTY and v.choice in ("yea", "nay"):
            tally[(v.division_id, v.party)][v.choice] += 1
    changed = []
    for v in votes:
        counts = tally.get((v.division_id, v.party))
        line = None
        if counts and v.choice != "paired" and counts["yea"] + counts["nay"] >= MIN_PARTY_VOTERS:
            if counts["yea"] != counts["nay"]:
                line = "yea" if counts["yea"] > counts["nay"] else "nay"
        value = None if line is None else v.choice != line
        if value != v.against_party:
            v.against_party = value
            changed.append(v)
    return changed


def link_votes(cache: dict | None = None) -> int:
    """Match votes that have no person yet (members who had not spoken when the vote
    was loaded), then update party lines in those divisions. Returns matches."""
    cache = {} if cache is None else cache
    pending = list(Vote.objects.filter(person__isnull=True).select_related("division__sitting"))
    if not pending:
        return 0
    division_ids = {v.division_id for v in pending}
    taken: dict[int, set[int]] = defaultdict(set)
    for division_id, person_id in Vote.objects.filter(
        division__in=division_ids, person__isnull=False
    ).values_list("division", "person"):
        taken[division_id].add(person_id)
    matched = _match(pending, cache, taken)
    Vote.objects.bulk_update(matched, ["person", "party"], batch_size=2000)
    if matched:
        affected = {v.division_id for v in matched}
        everyone = list(Vote.objects.filter(division__in=affected))
        Vote.objects.bulk_update(_party_lines(everyone), ["against_party"], batch_size=2000)
    return len(matched)
