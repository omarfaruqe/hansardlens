"""Descriptive analysis: how often terms come up, and which language is spoken.

Every figure is a share with a stated denominator, never a raw count alone:

- Term trends: paragraphs mentioning a term per 1,000 speech paragraphs in that month.
  Paragraphs (not words) are the unit so that phrases and OR-queries count the same way
  as single words.
- Language on the floor: share of speech spoken in French, measured on the length of
  the English text of each paragraph, so both languages share one yardstick.

Chair occupants and procedural text are excluded; written answers ([Text]) are not speech.
Results are cached until the next load (the cache key includes the latest load time).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json

from django.core.cache import cache
from django.db.models import Count, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth

from .models import Paragraph, Person, Sitting
from .search import SearchParams

MAX_TERMS = 4
CACHE_SECONDS = 6 * 3600
# Months with less debate than this are shown as gaps: one short sitting alone in a
# month (an adjournment after a death, say) would otherwise produce extreme rates.
MIN_MONTH_PARAGRAPHS = 100
MIN_MONTH_WORDS = 5_000
MIN_PARTY_WORDS = 20_000
MIN_MEMBER_WORDS = 10_000


def data_version() -> str:
    latest = Sitting.objects.aggregate(m=Max("loaded_at"))["m"]
    return latest.isoformat() if latest else "empty"


def cached(name: str, params: dict, compute):
    raw = json.dumps(params, sort_keys=True, default=str)
    key = f"hl:{name}:{hashlib.sha1(raw.encode()).hexdigest()}:{data_version()}"
    value = cache.get(key)
    if value is None:
        value = compute()
        cache.set(key, value, CACHE_SECONDS)
    return value


def month_range(first: dt.date, last: dt.date) -> list[dt.date]:
    months, d = [], first.replace(day=1)
    while d <= last:
        months.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return months


def _speech(parliament: int | None = None, party: str = ""):
    qs = Paragraph.objects.filter(kind="speech", intervention__is_chair=False)
    if parliament:
        qs = qs.filter(intervention__sitting__parliament=parliament)
    if party:
        qs = qs.filter(intervention__party=party)
    return qs


def _by_month(qs, **aggregates) -> dict[dt.date, dict]:
    rows = (
        qs.annotate(month=TruncMonth("intervention__sitting__date"))
        .values("month")
        .annotate(**aggregates)
        .order_by("month")
    )
    return {row["month"]: row for row in rows}


def _axis(parliament: int | None) -> list[dt.date]:
    """Every calendar month from the first to the last loaded sitting. Months without
    sittings (summer and winter breaks) stay on the axis as gaps, not zeros."""
    sittings = Sitting.objects.all()
    if parliament:
        sittings = sittings.filter(parliament=parliament)
    bounds = sittings.aggregate(first=Min("date"), last=Max("date"))
    return month_range(bounds["first"], bounds["last"]) if bounds["first"] else []


# ------------------------------------------------------------------------------------
# Term trends
# ------------------------------------------------------------------------------------


def term_trends(
    terms: list[str], lang: str = "en", party: str = "", parliament: int | None = None
) -> dict:
    terms = [t for t in (" ".join(t.split()) for t in terms) if t][:MAX_TERMS]

    def compute():
        months = _axis(parliament)
        base = _speech(parliament, party)
        totals = _by_month(base, n=Count("id"))
        series = []
        for term in terms:
            query = SearchParams(q=term, lang=lang).query()
            hits = _by_month(base.filter(**{f"search_{lang}": query}), n=Count("id"))
            values, counts = [], []
            for m in months:
                total = totals.get(m, {}).get("n", 0)
                hit = hits.get(m, {}).get("n", 0)
                enough = total >= MIN_MONTH_PARAGRAPHS
                counts.append(hit if enough else None)
                values.append(round(1000 * hit / total, 2) if enough else None)
            series.append(
                {
                    "name": term,
                    "values": values,
                    "counts": counts,
                    "total_hits": sum(c or 0 for c in counts),
                }
            )
        return {
            "months": [m.strftime("%Y-%m") for m in months],
            "denominators": [totals.get(m, {}).get("n", 0) or None for m in months],
            "series": series,
            "unit": "per 1,000 paragraphs",
        }

    if not terms:
        return {"months": [], "denominators": [], "series": [], "unit": "per 1,000 paragraphs"}
    return cached("trends", {"t": terms, "l": lang, "p": party, "parl": parliament}, compute)


# ------------------------------------------------------------------------------------
# Language on the floor
# ------------------------------------------------------------------------------------

_LANG_AGG = {
    "fr": Sum("words_en", filter=Q(floor_language="fr")),
    "total": Sum("words_en"),
}


def _spoken(parliament: int | None):
    return _speech(parliament).filter(floor_language__in=["en", "fr"])


def _share(fr, total):
    return round(100 * fr / total, 1) if total else None


def language_by_month(parliament: int | None = None) -> dict:
    def compute():
        months = _axis(parliament)
        rows = _by_month(_spoken(parliament), **_LANG_AGG)
        values = []
        for m in months:
            row = rows.get(m)
            enough = row is not None and (row["total"] or 0) >= MIN_MONTH_WORDS
            values.append(_share(row["fr"] or 0, row["total"]) if enough else None)
        return {
            "months": [m.strftime("%Y-%m") for m in months],
            "denominators": [rows[m]["total"] if m in rows else None for m in months],
            "series": [{"name": "French", "values": values}],
            "unit": "% of words spoken",
        }

    return cached("lang_month", {"parl": parliament}, compute)


def language_overall(parliament: int | None = None) -> dict:
    def compute():
        row = _spoken(parliament).aggregate(**_LANG_AGG)
        return {
            "fr": row["fr"] or 0,
            "total": row["total"] or 0,
            "share": _share(row["fr"] or 0, row["total"] or 0),
        }

    return cached("lang_all", {"parl": parliament}, compute)


def language_by_party(parliament: int | None = None, min_words: int | None = None) -> list[dict]:
    min_words = MIN_PARTY_WORDS if min_words is None else min_words

    def compute():
        rows = (
            _spoken(parliament)
            .exclude(intervention__party="")
            .values("intervention__party")
            .annotate(**_LANG_AGG)
        )
        out = [
            {
                "party": r["intervention__party"],
                "fr": r["fr"] or 0,
                "total": r["total"],
                "share": _share(r["fr"] or 0, r["total"]),
            }
            for r in rows
            if r["total"] and r["total"] >= min_words
        ]
        return sorted(out, key=lambda r: -r["share"])

    return cached("lang_party", {"parl": parliament, "min": min_words}, compute)


MEMBER_SORTS = {"french": "-share", "words": "-total", "name": "name"}


def language_by_member(
    parliament: int | None = None, min_words: int | None = None, sort: str = "french"
) -> list[dict]:
    min_words = MIN_MEMBER_WORDS if min_words is None else min_words

    def compute():
        rows = (
            _spoken(parliament)
            .exclude(intervention__person__isnull=True)
            .values("intervention__person")
            .annotate(**_LANG_AGG)
            .filter(total__gte=min_words)
        )
        people = {
            p.id: p for p in Person.objects.filter(id__in=[r["intervention__person"] for r in rows])
        }
        return [
            {
                "name": people[r["intervention__person"]].name,
                "slug": people[r["intervention__person"]].slug,
                "party": people[r["intervention__person"]].latest_party,
                "fr": r["fr"] or 0,
                "total": r["total"],
                "share": _share(r["fr"] or 0, r["total"]),
            }
            for r in rows
        ]

    rows = cached("lang_member2", {"parl": parliament, "min": min_words}, compute)
    key = MEMBER_SORTS.get(sort, "-share")
    reverse = key.startswith("-")
    field = key.lstrip("-")
    return sorted(
        rows, key=lambda r: (r[field], r["name"]) if field != "name" else r["name"], reverse=reverse
    )


# ------------------------------------------------------------------------------------
# Topics
# ------------------------------------------------------------------------------------

MIN_MONTH_SPEECHES = 30
MIN_PARTY_SPEECHES = 200


def topic_by_month(topic) -> dict:
    """Share of each month's speeches whose main topic is `topic`."""
    from .models import InterventionTopic

    def compute():
        model = topic.model
        months = month_range(model.first_date, model.last_date)
        base = InterventionTopic.objects.filter(topic__model=model)
        month = TruncMonth("intervention__sitting__date")
        totals = {
            r["m"]: r["n"] for r in base.annotate(m=month).values("m").annotate(n=Count("id"))
        }
        hits = {
            r["m"]: r["n"]
            for r in base.filter(topic=topic).annotate(m=month).values("m").annotate(n=Count("id"))
        }
        values, counts = [], []
        for m in months:
            total = totals.get(m, 0)
            ok = total >= MIN_MONTH_SPEECHES
            values.append(round(100 * hits.get(m, 0) / total, 1) if ok else None)
            counts.append(hits.get(m, 0) if ok else None)
        return {
            "months": [m.strftime("%Y-%m") for m in months],
            "denominators": [totals.get(m) for m in months],
            "series": [{"name": topic.label, "values": values, "counts": counts}],
            "unit": "% of speeches",
        }

    return cached("topic_month", {"model": topic.model_id, "topic": topic.number}, compute)


def topic_by_party(topic) -> list[dict]:
    """For each party: share of its own speeches whose main topic is `topic`."""
    from .models import InterventionTopic

    def compute():
        rows = (
            InterventionTopic.objects.filter(topic__model=topic.model_id)
            .exclude(intervention__party="")
            .values("intervention__party")
            .annotate(total=Count("id"), hits=Count("id", filter=Q(topic=topic)))
        )
        out = [
            {
                "party": r["intervention__party"],
                "hits": r["hits"],
                "total": r["total"],
                "share": round(100 * r["hits"] / r["total"], 1),
            }
            for r in rows
            if r["total"] >= MIN_PARTY_SPEECHES
        ]
        return sorted(out, key=lambda r: -r["share"])

    return cached("topic_party", {"model": topic.model_id, "topic": topic.number}, compute)


# ------------------------------------------------------------------------------------
# Members
# ------------------------------------------------------------------------------------

# What counts as a member's speech: everything they say on the floor except
# interjections and procedural text, and nothing said while in the chair.
SPEECH_KINDS = [
    "Debate",
    "Question",
    "QuestionSupplemental",
    "QuestionComment",
    "Answer",
    "AnswerSupplemental",
    "Statement",
]
KIND_GROUPS = {
    "debate": ["Debate"],
    "questions": ["Question", "QuestionSupplemental", "QuestionComment"],
    "answers": ["Answer", "AnswerSupplemental"],
    "statements": ["Statement"],
}
MIN_MEMBER_LANGUAGE_WORDS = 1_000
MIN_MEMBER_TOPIC_SPEECHES = 10
MEMBER_LIST_SORTS = ("name", "speeches", "recent")


def member_speeches(person):
    from .models import Intervention

    return Intervention.objects.filter(person=person, is_chair=False, kind__in=SPEECH_KINDS)


def _spans(qs, field: str) -> list[dict]:
    """Each distinct value of `field` with the first and last sitting date it was used."""
    rows = (
        qs.exclude(**{field: ""})
        .values(field)
        .annotate(first=Min("sitting__date"), last=Max("sitting__date"), n=Count("id"))
        .order_by("first", field)
    )
    return [{"value": r[field], "first": r["first"], "last": r["last"], "n": r["n"]} for r in rows]


def member_profile(person) -> dict:
    """Descriptive facts about one person's speeches: counts, parties, ridings, roles,
    speeches by month and the language they speak on the floor."""
    from .models import Intervention

    def compute():
        speeches = member_speeches(person)
        totals = speeches.aggregate(
            n=Count("id"),
            sittings=Count("sitting", distinct=True),
            first=Min("sitting__date"),
            last=Max("sitting__date"),
        )
        kinds = dict(speeches.values_list("kind").annotate(n=Count("id")))
        mine = Intervention.objects.filter(person=person)
        as_member = mine.filter(is_chair=False)

        # Speeches per month, from the member's first speech to the latest sitting;
        # months without sittings are gaps, months with sittings but no speech are 0.
        months, values, denominators = [], [], []
        if totals["first"]:
            last = Sitting.objects.aggregate(m=Max("date"))["m"]
            months = month_range(totals["first"], last)
            sittings = {
                r["m"]: r["n"]
                for r in Sitting.objects.annotate(m=TruncMonth("date"))
                .values("m")
                .annotate(n=Count("id"))
            }
            spoken = {
                r["m"]: r["n"]
                for r in speeches.annotate(m=TruncMonth("sitting__date"))
                .values("m")
                .annotate(n=Count("id"))
            }
            for m in months:
                denominators.append(sittings.get(m))
                values.append(spoken.get(m, 0) if m in sittings else None)

        language = Paragraph.objects.filter(
            kind="speech",
            intervention__person=person,
            intervention__is_chair=False,
            floor_language__in=["en", "fr"],
        ).aggregate(**_LANG_AGG)
        lang_total = language["total"] or 0
        return {
            "speeches": totals["n"],
            "sittings": totals["sittings"],
            "first": totals["first"],
            "last": totals["last"],
            "by_kind": {k: sum(kinds.get(x, 0) for x in xs) for k, xs in KIND_GROUPS.items()},
            "chair": mine.filter(is_chair=True).count(),
            "parties": _spans(as_member, "party"),
            "ridings": _spans(as_member, "riding"),
            "roles": sorted(
                _spans(as_member, "speaker_role"), key=lambda r: r["last"], reverse=True
            ),
            "chair_roles": _spans(mine.filter(is_chair=True), "speaker_role"),
            "language": {
                "fr": language["fr"] or 0,
                "total": lang_total,
                "share": _share(language["fr"] or 0, lang_total)
                if lang_total >= MIN_MEMBER_LANGUAGE_WORDS
                else None,
            },
            "by_month": {
                "months": [m.strftime("%Y-%m") for m in months],
                "denominators": denominators,
                "series": [{"name": "Speeches", "values": values}],
                "unit": "speeches",
            },
        }

    return cached("member", {"id": person.id}, compute)


def member_topics(person, model, limit: int = 6) -> dict:
    """The topics a member's speeches are most often about, next to the House share."""
    from .models import InterventionTopic

    def compute():
        rows = list(
            InterventionTopic.objects.filter(
                topic__model=model, intervention__person=person, intervention__is_chair=False
            )
            .values("topic")
            .annotate(n=Count("id"))
            .order_by("-n", "topic")
        )
        total = sum(r["n"] for r in rows)
        if total < MIN_MEMBER_TOPIC_SPEECHES:
            return {"total": total, "topics": []}
        topics = model.topics.in_bulk([r["topic"] for r in rows[:limit]])
        return {
            "total": total,
            "topics": [
                {
                    "number": topics[r["topic"]].number,
                    "label": topics[r["topic"]].label,
                    "n": r["n"],
                    "share": round(100 * r["n"] / total, 1),
                    "house": round(100 * topics[r["topic"]].share, 1),
                }
                for r in rows[:limit]
            ],
        }

    return cached("member_topics", {"id": person.id, "model": model.id}, compute)


def member_list(parliament: int | None = None) -> list[dict]:
    """Everyone who has spoken (in one Parliament, if given), with speech counts."""
    from .models import Intervention

    def compute():
        qs = Intervention.objects.filter(person__isnull=False)
        if parliament:
            qs = qs.filter(sitting__parliament=parliament)
        rows = qs.values("person").annotate(
            speeches=Count("id", filter=Q(is_chair=False, kind__in=SPEECH_KINDS)),
            chair=Count("id", filter=Q(is_chair=True)),
            last=Max("sitting__date"),
        )
        people = Person.objects.in_bulk([r["person"] for r in rows])
        return [
            {
                "name": people[r["person"]].name,
                "slug": people[r["person"]].slug,
                "party": people[r["person"]].latest_party,
                "riding": people[r["person"]].latest_riding,
                "speeches": r["speeches"],
                "chair": r["chair"],
                "last": r["last"],
            }
            for r in rows
            if r["speeches"] or r["chair"]
        ]

    return cached("members", {"parl": parliament}, compute)
