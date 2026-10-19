"""Pages for committee meetings, witnesses and committee evidence search."""

from __future__ import annotations

from django.contrib.postgres.search import SearchHeadline, SearchRank
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Min, Q
from django.shortcuts import get_object_or_404, redirect, render

from . import search
from .models import Committee, Meeting, MeetingIntervention, MeetingParagraph, Witness
from .views import _fold, content_lang

PAGE_SIZE = 50
SPOKEN = ("member", "chair", "minister", "witness")


def committees_view(request):
    committees = Committee.objects.annotate(
        meetings_n=Count("meetings", distinct=True),
        first=Min("meetings__date"),
        last=Max("meetings__date"),
    ).order_by("acronym")
    stats = {
        c["meeting__committee"]: c["n"]
        for c in MeetingIntervention.objects.filter(witness__isnull=False)
        .values("meeting__committee")
        .annotate(n=Count("witness", distinct=True))
    }
    for c in committees:
        c.witnesses_n = stats.get(c.id, 0)
    return render(
        request,
        "committees.html",
        {
            "lang": content_lang(request),
            "committees": committees,
            "witnesses_total": Witness.objects.count(),
        },
    )


def _sessions(meetings):
    return [
        f"{p}-{s}"
        for p, s in meetings.values_list("parliament", "session")
        .distinct()
        .order_by("-parliament", "-session")
    ]


def committee_detail(request, acronym: str):
    committee = get_object_or_404(Committee, acronym=acronym.upper())
    if acronym != committee.acronym:
        return redirect(committee.get_absolute_url(), permanent=True)
    lang = content_lang(request)
    meetings = committee.meetings.order_by("-date", "-number")
    session = request.GET.get("session", "")
    sessions = _sessions(committee.meetings)
    if session in sessions:
        p, s = session.split("-")
        meetings = meetings.filter(parliament=int(p), session=int(s))
    page = Paginator(meetings, PAGE_SIZE).get_page(request.GET.get("page"))
    # Witnesses of the meetings on this page, in order of appearance.
    rows = (
        MeetingIntervention.objects.filter(
            meeting__in=list(page.object_list), witness__isnull=False
        )
        .values("meeting", "witness__name", "witness__slug", f"witness__affiliation_{lang}")
        .annotate(first=Min("sequence"))
        .order_by("meeting", "first")
    )
    by_meeting: dict[int, list] = {}
    for r in rows:
        by_meeting.setdefault(r["meeting"], []).append(r)
    for m in page.object_list:
        m.witness_rows = by_meeting.get(m.id, [])
        affiliations = []
        for r in m.witness_rows:
            a = r[f"witness__affiliation_{lang}"]
            if a and a not in affiliations:
                affiliations.append(a)
        m.affiliations = affiliations[:3]
    top = (
        MeetingIntervention.objects.filter(meeting__committee=committee, witness__isnull=False)
        .values(f"witness__affiliation_{lang}")
        .exclude(**{f"witness__affiliation_{lang}": ""})
        .annotate(n=Count("meeting", distinct=True))
        .order_by("-n")[:10]
    )
    return render(
        request,
        "committee_detail.html",
        {
            "lang": lang,
            "committee": committee,
            "page": page,
            "total": page.paginator.count,
            "session": session if session in sessions else "",
            "sessions": sessions,
            "top_affiliations": [(r[f"witness__affiliation_{lang}"], r["n"]) for r in top],
        },
    )


def meeting_detail(request, acronym: str, parliament: int, session: int, number: int):
    meeting = get_object_or_404(
        Meeting.objects.select_related("committee"),
        committee__acronym=acronym.upper(),
        parliament=parliament,
        session=session,
        number=number,
    )
    if acronym != meeting.committee.acronym:
        return redirect(meeting.get_absolute_url(), permanent=True)
    lang = content_lang(request)
    interventions = list(
        meeting.interventions.select_related("person", "witness")
        .prefetch_related("paragraphs")
        .order_by("sequence")
    )
    witnesses, seen = [], set()
    for iv in interventions:
        if iv.witness_id and iv.witness_id not in seen:
            seen.add(iv.witness_id)
            witnesses.append(iv)
    neighbours = Meeting.objects.filter(
        committee=meeting.committee, parliament=parliament, session=session
    )
    return render(
        request,
        "meeting_detail.html",
        {
            "lang": lang,
            "other_lang": "fr" if lang == "en" else "en",
            "meeting": meeting,
            "interventions": interventions,
            "witnesses": witnesses,
            "previous": neighbours.filter(number__lt=number).order_by("-number").first(),
            "next": neighbours.filter(number__gt=number).order_by("number").first(),
        },
    )


def find_witnesses(q: str = "", committee: str = ""):
    """Witnesses with their meeting count, optionally filtered by a folded name, title or
    organisation search and by committee. Shared by the page and the API."""
    qs = Witness.objects.annotate(meetings_n=Count("interventions__meeting", distinct=True))
    if committee:
        qs = qs.filter(interventions__meeting__committee__acronym=committee).distinct()
    if q:
        needle = _fold(q)
        ids = [
            w.id
            for w in Witness.objects.only(
                "id", "name", "affiliation_en", "affiliation_fr", "title_en", "title_fr"
            )
            if needle
            in _fold(f"{w.name} {w.title_en} {w.affiliation_en} {w.title_fr} {w.affiliation_fr}")
        ]
        qs = qs.filter(id__in=ids)
    return qs


def witnesses_view(request):
    lang = content_lang(request)
    q = " ".join(request.GET.get("q", "").split())[:100]
    committee = request.GET.get("committee", "").upper()[:8]
    qs = find_witnesses(q, committee)
    sort = request.GET.get("sort", "recent")
    qs = qs.order_by({"name": "name", "meetings": "-meetings_n"}.get(sort, "-latest_date"), "name")
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("lang", None)
    return render(
        request,
        "witnesses.html",
        {
            "lang": lang,
            "page": page,
            "total": page.paginator.count,
            "q": q,
            "committee": committee,
            "committees": Committee.objects.order_by("acronym"),
            "sort": sort if sort in ("name", "meetings") else "recent",
            "querystring": query.urlencode(),
        },
    )


def witness_detail(request, slug: str):
    witness = get_object_or_404(Witness, slug=slug)
    lang = content_lang(request)
    appearances = (
        Meeting.objects.filter(interventions__witness=witness)
        .select_related("committee")
        .annotate(
            n=Count("interventions", filter=Q(interventions__witness=witness)),
            first=Min("interventions__sequence", filter=Q(interventions__witness=witness)),
        )
        .order_by("-date")
    )
    titles = (
        MeetingIntervention.objects.filter(witness=witness)
        .values(f"detail_{lang}")
        .exclude(**{f"detail_{lang}": ""})
        .annotate(last=Max("meeting__date"))
        .order_by("-last")
    )
    return render(
        request,
        "witness_detail.html",
        {
            "lang": lang,
            "witness": witness,
            "appearances": appearances,
            "titles": [t[f"detail_{lang}"] for t in titles],
        },
    )


def committee_search(request):
    lang = content_lang(request)
    q = " ".join(request.GET.get("q", "").split())[:200]
    committee = request.GET.get("committee", "").upper()[:8]
    role = request.GET.get("role", "")
    context = {
        "lang": lang,
        "q": q,
        "committee": committee,
        "committees": Committee.objects.order_by("acronym"),
        "role": role if role in SPOKEN else "",
    }
    if q:
        params = search.SearchParams(q=q, lang=lang)
        query = params.query()
        vector = f"search_{lang}"
        qs = MeetingParagraph.objects.filter(kind="speech", **{vector: query})
        if committee:
            qs = qs.filter(intervention__meeting__committee__acronym=committee)
        if context["role"]:
            qs = qs.filter(intervention__role=context["role"])
        qs = qs.annotate(rank=SearchRank(F(vector), query)).order_by(
            "-rank", "-intervention__meeting__date", "id"
        )
        paginator = Paginator(qs.values_list("id", flat=True), 20)
        page = paginator.get_page(request.GET.get("page"))
        ids = list(page.object_list)
        rows = {
            r.id: r
            for r in MeetingParagraph.objects.filter(id__in=ids)
            .select_related(
                "intervention__meeting__committee",
                "intervention__person",
                "intervention__witness",
            )
            .annotate(
                snippet=SearchHeadline(
                    params.text_field,
                    query,
                    config=params.config,
                    start_sel=search._START,
                    stop_sel=search._STOP,
                    max_words=45,
                    min_words=20,
                    max_fragments=2,
                    fragment_delimiter=" … ",
                )
            )
        }
        results = []
        for pid in ids:
            if pid in rows:
                rows[pid].snippet_html = search._safe_highlight(rows[pid].snippet)
                results.append(rows[pid])
        query_string = request.GET.copy()
        query_string.pop("page", None)
        query_string.pop("lang", None)
        context.update(
            page=page,
            total=paginator.count,
            results=results,
            querystring=query_string.urlencode(),
        )
    return render(request, "committee_search.html", context)
