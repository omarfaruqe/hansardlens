"""Data-quality report over everything loaded so far."""

from __future__ import annotations

from django.db.models import Count, Max, Min, Q, Sum

from .models import Intervention, Paragraph, Person, Sitting


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def ranges(numbers: list[int]) -> str:
    """[2, 3, 4, 9] -> '2–4, 9'"""
    if not numbers:
        return "none"
    out, start, prev = [], numbers[0], numbers[0]
    for n in numbers[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(f"{start}–{prev}" if start != prev else str(start))
        if n is not None:
            start = prev = n
    return ", ".join(out)


def build_report() -> str:
    lines = ["HansardLens data-quality report", "=" * 31, ""]
    sessions = (
        Sitting.objects.values("parliament", "session")
        .annotate(
            n=Count("id"),
            first=Min("number"),
            last=Max("number"),
            d1=Min("date"),
            d2=Max("date"),
        )
        .order_by("parliament", "session")
    )
    if not sessions:
        return "\n".join(lines + ["No sittings loaded yet."])

    for row in sessions:
        p, s = row["parliament"], row["session"]
        numbers = set(
            Sitting.objects.filter(parliament=p, session=s).values_list("number", flat=True)
        )
        gaps = sorted(set(range(row["first"], row["last"] + 1)) - numbers)
        no_fr = Sitting.objects.filter(parliament=p, session=s, has_french=False).count()
        with_issues = Sitting.objects.filter(parliament=p, session=s).exclude(issues=[]).count()
        lines += [
            f"Parliament {p}, session {s}",
            f"  sittings        : {row['n']} (No. {row['first']}–{row['last']}, "
            f"{row['d1']} to {row['d2']})",
            f"  missing numbers : {ranges(gaps)}",
            f"  without French  : {no_fr}",
            f"  with issues     : {with_issues}",
            "",
        ]

    ivs = Intervention.objects.all()
    total = ivs.count()
    by_kind = dict(ivs.values_list("kind").annotate(n=Count("id")).order_by())
    unlisted = sorted(set(by_kind) - set(Intervention.Kind.values))
    members = ivs.exclude(kind=Intervention.Kind.PROCEDURAL).filter(is_chair=False)
    n_members = members.count()
    no_person = members.filter(person__isnull=True).count()
    no_party = members.filter(party="").count()
    no_fr_text = ivs.exclude(text_en="").filter(text_fr="").count()
    words = ivs.aggregate(
        en=Sum("floor_words_en"), fr=Sum("floor_words_fr"), all=Sum("word_count_en")
    )
    paras = Paragraph.objects.count()
    unknown_floor = Paragraph.objects.filter(kind="speech", floor_language="").count()
    top_parties = (
        members.exclude(party="").values_list("party").annotate(n=Count("id")).order_by("-n")
    )

    lines += [
        "Interventions",
        f"  total                       : {total}",
        f"  by kind                     : {by_kind}",
        f"  types not yet in the model  : {unlisted or 'none'}",
        f"  member speeches             : {n_members}",
        f"    without a person          : {no_person} ({pct(no_person, n_members)})",
        f"    without a party           : {no_party} ({pct(no_party, n_members)})",
        f"  English text but no French  : {no_fr_text}",
        f"  by party                    : {dict(top_parties)}",
        "",
        "Paragraphs",
        f"  total                       : {paras}",
        f"  speech with unknown floor language: {unknown_floor}",
        "",
        "Language spoken on the floor (words in the original language)",
        f"  English : {words['en'] or 0:,}",
        f"  French  : {words['fr'] or 0:,}",
        f"  French share: {pct(words['fr'] or 0, (words['en'] or 0) + (words['fr'] or 0))}",
        "",
        f"People: {Person.objects.count()} "
        f"({Person.objects.filter(~Q(latest_party='')).count()} with a known party)",
    ]

    problem = Sitting.objects.exclude(issues=[]).order_by("date")[:10]
    if problem:
        lines += ["", "Sittings with issues (first 10)"]
        for sit in problem:
            lines.append(f"  {sit}: {'; '.join(sit.issues)[:200]}")
    return "\n".join(lines)
