"""Descriptive analysis of committee evidence: what committees discuss, who speaks.

- Topics: committee speeches (members, ministers, witnesses; at least 60 words) are
  scored with the House topic model when it is fitted (`textmine.score_committees`),
  so a committee's topic shares and the House's are measured with the same topics.
  Each share is the committee's scored speeches whose main topic is that topic.
- Members: interventions and words in committee, next to the member's own speeches
  in the House, both counted on the English text.

Results are cached until the next committee load or topic refit.
"""

from __future__ import annotations

from django.db.models import Count, Max, Q, Sum

from .analysis import cached
from .models import Meeting, MeetingIntervention, MeetingInterventionTopic

TOPIC_MIN_SPEECHES = 30  # a committee or meeting needs this many scored speeches


def committee_version() -> str:
    latest = Meeting.objects.aggregate(m=Max("loaded_at"))["m"]
    return latest.isoformat() if latest else "empty"


def _cached(name: str, params: dict, compute):
    return cached(name, {**params, "cv": committee_version()}, compute)


def committee_topics(
    committee, model, session: tuple[int, int] | None = None, limit: int = 8
) -> dict:
    """The topics a committee spends most of its scored speeches on, next to each
    topic's share of House speeches."""

    def compute():
        qs = MeetingInterventionTopic.objects.filter(
            topic__model=model, intervention__meeting__committee=committee
        )
        if session:
            qs = qs.filter(
                intervention__meeting__parliament=session[0],
                intervention__meeting__session=session[1],
            )
        rows = list(
            qs.values("topic__number", "topic__share")
            .annotate(n=Count("id"))
            .order_by("-n", "topic__number")
        )
        total = sum(r["n"] for r in rows)
        if total < TOPIC_MIN_SPEECHES:
            return {"total": total, "rows": []}
        return {
            "total": total,
            "rows": [
                {
                    "number": r["topic__number"],
                    "n": r["n"],
                    "share": round(100 * r["n"] / total, 1),
                    "house_share": round(100 * r["topic__share"], 1),
                }
                for r in rows[:limit]
            ],
        }

    return _cached(
        "committee_topics", {"c": committee.id, "m": model.id, "s": session, "l": limit}, compute
    )


def topic_by_committee(topic) -> list[dict]:
    """For each committee: share of its scored speeches whose main topic is `topic`."""

    def compute():
        rows = (
            MeetingInterventionTopic.objects.filter(topic__model=topic.model_id)
            .values(
                "intervention__meeting__committee__acronym",
                "intervention__meeting__committee__name_en",
                "intervention__meeting__committee__name_fr",
            )
            .annotate(total=Count("id"), hits=Count("id", filter=Q(topic=topic)))
            .order_by("intervention__meeting__committee__acronym")
        )
        out = [
            {
                "acronym": r["intervention__meeting__committee__acronym"],
                "name_en": r["intervention__meeting__committee__name_en"],
                "name_fr": r["intervention__meeting__committee__name_fr"],
                "hits": r["hits"],
                "total": r["total"],
                "share": round(100 * r["hits"] / r["total"], 1),
            }
            for r in rows
            if r["total"] >= TOPIC_MIN_SPEECHES
        ]
        return sorted(out, key=lambda r: -r["share"])

    return _cached("topic_committees", {"m": topic.model_id, "t": topic.number}, compute)


def meeting_topics(meeting, model, limit: int = 3) -> list[int]:
    """Numbers of the most frequent main topics among a meeting's scored speeches,
    each the main topic of at least a fifth of them."""
    rows = list(
        MeetingInterventionTopic.objects.filter(topic__model=model, intervention__meeting=meeting)
        .values("topic__number")
        .annotate(n=Count("id"))
        .order_by("-n", "topic__number")
    )
    total = sum(r["n"] for r in rows)
    if total < 5:
        return []
    return [r["topic__number"] for r in rows[:limit] if r["n"] >= 0.2 * total]


def committee_members(committee, session: tuple[int, int] | None = None, limit: int = 12):
    """Members (and ministers) who spoke most at a committee's meetings, by words."""

    def compute():
        qs = MeetingIntervention.objects.filter(
            meeting__committee=committee,
            role__in=[MeetingIntervention.Role.MEMBER, MeetingIntervention.Role.MINISTER],
            person__isnull=False,
        )
        if session:
            qs = qs.filter(meeting__parliament=session[0], meeting__session=session[1])
        rows = (
            qs.values("person__name", "person__slug", "person__latest_party")
            .annotate(
                meetings=Count("meeting", distinct=True),
                interventions=Count("id"),
                words=Sum("words_en"),
            )
            .order_by("-words", "person__name")[:limit]
        )
        return [
            {
                "name": r["person__name"],
                "slug": r["person__slug"],
                "party": r["person__latest_party"],
                "meetings": r["meetings"],
                "interventions": r["interventions"],
                "words": r["words"] or 0,
            }
            for r in rows
        ]

    return _cached("committee_members", {"c": committee.id, "s": session, "l": limit}, compute)


def member_committee_work(person) -> dict:
    """A member's words in committee and in the House (own speeches), English text."""
    from .analysis import member_speeches

    def compute():
        committee = MeetingIntervention.objects.filter(person=person).exclude(
            role=MeetingIntervention.Role.CHAIR
        )
        c = committee.aggregate(
            n=Count("id"), words=Sum("words_en"), meetings=Count("meeting", distinct=True)
        )
        chair = MeetingIntervention.objects.filter(
            person=person, role=MeetingIntervention.Role.CHAIR
        ).aggregate(meetings=Count("meeting", distinct=True))["meetings"]
        house = member_speeches(person).aggregate(n=Count("id"), words=Sum("word_count_en"))
        c_words, h_words = c["words"] or 0, house["words"] or 0
        both = c_words + h_words
        return {
            "committee_interventions": c["n"],
            "committee_words": c_words,
            "committee_meetings": c["meetings"],
            "chaired_meetings": chair,
            "house_speeches": house["n"],
            "house_words": h_words,
            "committee_share": round(100 * c_words / both, 1) if both else None,
        }

    return _cached("member_committee", {"p": person.id}, compute)


# ------------------------------------------------------------------------------------
# Who is heard
# ------------------------------------------------------------------------------------


def _appearances(committee=None, session: tuple[int, int] | None = None):
    """(committee acronym, kind) for each witness at each meeting, counted once."""
    from .witness_kinds import classify

    qs = MeetingIntervention.objects.filter(witness__isnull=False)
    if committee is not None:
        qs = qs.filter(meeting__committee=committee)
    if session:
        qs = qs.filter(meeting__parliament=session[0], meeting__session=session[1])
    seen = set()
    for meeting_id, witness_id, acronym, detail, individual in qs.order_by(
        "meeting_id", "witness_id", "sequence"
    ).values_list(
        "meeting_id",
        "witness_id",
        "meeting__committee__acronym",
        "detail_en",
        "witness__as_individual",
    ):
        if (meeting_id, witness_id) in seen:
            continue
        seen.add((meeting_id, witness_id))
        yield acronym, classify(detail, individual)


def _shares(counts: dict[str, int]) -> dict:
    from .witness_kinds import ORDER

    total = sum(counts.values())
    return {
        "total": total,
        "rows": [
            {"kind": k, "n": counts[k], "share": round(100 * counts[k] / total, 1)}
            for k in ORDER
            if counts.get(k)
        ],
    }


def witness_kinds(committee=None, session: tuple[int, int] | None = None) -> dict:
    """Witness appearances (a witness at a meeting counts once) by kind."""

    def compute():
        counts: dict[str, int] = {}
        for _acronym, kind in _appearances(committee, session):
            counts[kind] = counts.get(kind, 0) + 1
        return _shares(counts)

    key = {"c": committee.id if committee else None, "s": session}
    return _cached("witness_kinds", key, compute)


def witness_kinds_by_committee() -> dict:
    """Shares of witness appearances by kind for every committee, plus all of them."""
    from .witness_kinds import ORDER

    def compute():
        counts: dict[str, dict[str, int]] = {}
        for acronym, kind in _appearances():
            for col in (acronym, ""):
                counts.setdefault(col, {}).setdefault(kind, 0)
                counts[col][kind] += 1
        columns = sorted(c for c in counts if c) + [""]
        totals = {c: sum(counts[c].values()) for c in columns}
        rows = [
            {
                "kind": k,
                "cells": [
                    round(100 * counts[c].get(k, 0) / totals[c], 1) if totals[c] else 0
                    for c in columns
                ],
            }
            for k in ORDER
            if counts.get("", {}).get(k)
        ]
        return {"columns": columns, "totals": [totals[c] for c in columns], "rows": rows}

    return _cached("witness_kinds_all", {}, compute)
