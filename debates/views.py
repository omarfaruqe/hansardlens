import datetime as dt
from itertools import groupby

from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Max, Min
from django.http import Http404, HttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from config import __version__

from . import search
from .models import Intervention, Person, Sitting

PAGE_SIZE = 20


def ui_lang() -> str:
    return "fr" if (get_language() or "en").startswith("fr") else "en"


def content_lang(request) -> str:
    """Language of the debate text searched or shown first: ?text=, else the interface
    language (?lang= sets the interface language; see middleware)."""
    text = request.GET.get("text")
    return text if text in search.LANGS else ui_lang()


def home(request):
    stats = Sitting.objects.aggregate(n=Count("id"), first=Min("date"), last=Max("date"))
    context = {
        "stats": stats,
        "interventions": Intervention.objects.count() if stats["n"] else 0,
        "latest": Sitting.objects.order_by("-date")[:6],
        "lang": content_lang(request),
    }
    return render(request, "home.html", context)


def search_view(request):
    lang = content_lang(request)
    data = request.GET.copy()
    data["lang"] = lang  # SearchParams reads the text language from "lang"
    params = search.SearchParams.from_query_dict(data, default_lang=lang)
    context = {
        "params": params,
        "sorts": search.SORTS,
        "rubrics": search.RUBRIC_LABELS,
        "parties": (
            Intervention.objects.exclude(party="")
            .values_list("party", flat=True)
            .distinct()
            .order_by("party")
        ),
        "parliaments": Sitting.objects.values_list("parliament", flat=True)
        .distinct()
        .order_by("parliament"),
        "people": Person.objects.values_list("name", flat=True),
        "lang": params.lang,
    }
    if params.q and not params.errors:
        qs = search.filtered(params)
        paginator = Paginator(
            search.ordered(qs, params.sort).values_list("id", flat=True), PAGE_SIZE
        )
        page = paginator.get_page(request.GET.get("page"))
        query = request.GET.copy()
        query.pop("page", None)
        query.pop("lang", None)
        context.update(
            page=page,
            total=paginator.count,
            results=search.page_results(list(page.object_list), params),
            party_counts=search.party_counts(qs) if paginator.count else [],
            querystring=query.urlencode(),
        )
    return render(request, "search.html", context)


def speech_detail(request, house_id: str):
    iv = (
        Intervention.objects.filter(house_id=house_id)
        .select_related("sitting", "person", "bill")
        .first()
    )
    if iv is None:
        raise Http404("No such speech")
    lang = content_lang(request)
    siblings = Intervention.objects.filter(sitting=iv.sitting).exclude(house_id="")
    context = {
        "iv": iv,
        "lang": lang,
        "other_lang": "fr" if lang == "en" else "en",
        "paragraphs": iv.paragraphs.all(),
        "previous": siblings.filter(sequence__lt=iv.sequence).order_by("-sequence").first(),
        "next": siblings.filter(sequence__gt=iv.sequence).order_by("sequence").first(),
    }
    return render(request, "speech.html", context)


def sitting_list(request):
    sittings = Sitting.objects.order_by("-date").annotate(n=Count("interventions"))
    groups = [
        (key, list(rows))
        for key, rows in groupby(sittings, key=lambda s: (s.parliament, s.session))
    ]
    return render(request, "sitting_list.html", {"groups": groups, "lang": content_lang(request)})


def sitting_detail(request, parliament: int, session: int, number: int):
    sitting = get_object_or_404(Sitting, parliament=parliament, session=session, number=number)
    lang = content_lang(request)
    interventions = sitting.interventions.select_related("person").order_by("sequence")
    order_field = f"order_title_{lang}"
    subject_field = f"subject_title_{lang}"
    sections = []
    for (order, subject), rows in groupby(
        interventions, key=lambda iv: (getattr(iv, order_field), getattr(iv, subject_field))
    ):
        sections.append({"order": order, "subject": subject, "interventions": list(rows)})
    neighbours = Sitting.objects.filter(parliament=parliament, session=session)
    context = {
        "sitting": sitting,
        "sections": sections,
        "divisions": sitting.divisions.all(),
        "lang": lang,
        "other_lang": "fr" if lang == "en" else "en",
        "previous": neighbours.filter(number__lt=number).order_by("-number").first(),
        "next": neighbours.filter(number__gt=number).order_by("number").first(),
    }
    return render(request, "sitting_detail.html", context)


def not_found(request, exception=None):
    return render(request, "404.html", {"lang": ui_lang()}, status=404)


def server_error(request):
    # Rendered without context processors or database access.
    from django.template import loader
    from django.urls import get_script_prefix

    return HttpResponseServerError(
        loader.get_template("500.html").render({"home": get_script_prefix()})
    )


def robots_txt(request):
    from django.urls import get_script_prefix

    prefix = get_script_prefix()
    lines = ["User-agent: *", f"Disallow: {prefix}admin/", f"Disallow: {prefix}api/", ""]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def _refresh_status() -> dict:
    """Last scheduled refresh, from the scheduler service's state file."""
    from .management.commands.run_scheduler import load_state

    state = load_state()
    keys = ("status", "last_success", "last_attempt", "last_error")
    return {k: state.get(k) for k in keys} if state else {"status": "never run"}


def _backup_status() -> dict:
    """Newest finished database dump written by the backup service (data/backups)."""
    import time
    from pathlib import Path

    from django.conf import settings

    folder = Path(settings.DATA_DIR) / "backups"
    dumps = sorted(folder.glob("hansardlens-*.dump")) if folder.is_dir() else []
    if not dumps:
        return {"latest": None, "count": 0}
    latest = max(dumps, key=lambda p: p.stat().st_mtime)
    age = (time.time() - latest.stat().st_mtime) / 3600
    return {"latest": latest.name, "count": len(dumps), "age_hours": round(age, 1)}


def health(request):
    """Liveness check that also confirms the database answers."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse(
        {
            "status": "ok" if db_ok else "error",
            "database": db_ok,
            "vendor": connection.vendor,
            "version": __version__,
            "refresh": _refresh_status(),
            "backup": _backup_status(),
        },
        status=status,
    )


def _parliament(request):
    value = request.GET.get("parliament", "")
    return int(value) if value.isdigit() else None


def trends_view(request):
    from . import analysis

    lang = content_lang(request)
    terms = [request.GET.get(f"t{i}", "")[:120] for i in range(1, analysis.MAX_TERMS + 1)]
    party = request.GET.get("party", "")[:20]
    parliament = _parliament(request)
    data = analysis.term_trends(terms, lang=lang, party=party, parliament=parliament)
    context = {
        "lang": lang,
        "terms": terms,
        "party": party,
        "parliament": parliament,
        "parties": Intervention.objects.exclude(party="")
        .values_list("party", flat=True)
        .distinct()
        .order_by("party"),
        "parliaments": Sitting.objects.values_list("parliament", flat=True)
        .distinct()
        .order_by("parliament"),
        "data": data,
        "has_data": any(s["total_hits"] for s in data["series"]),
        "table": [
            {
                "month": month,
                "total": data["denominators"][i],
                "values": [
                    {"value": s["values"][i], "count": s["counts"][i]} for s in data["series"]
                ],
            }
            for i, month in enumerate(data["months"])
        ],
        "examples": ("housing", "inflation", "carbon tax")
        if lang == "en"
        else ("logement", "inflation", "taxe carbone"),
    }
    return render(request, "trends.html", context)


def language_view(request):
    from . import analysis

    parliament = _parliament(request)
    sort = request.GET.get("sort", "french")
    if sort not in analysis.MEMBER_SORTS:
        sort = "french"
    context = {
        "lang": content_lang(request),
        "parliament": parliament,
        "parliaments": Sitting.objects.values_list("parliament", flat=True)
        .distinct()
        .order_by("parliament"),
        "overall": analysis.language_overall(parliament),
        "by_month": analysis.language_by_month(parliament),
        "by_party": analysis.language_by_party(parliament),
        "members": analysis.language_by_member(parliament, sort=sort),
        "sort": sort,
        "member_sorts": [
            ("french", _("French share")),
            ("words", _("Words")),
            ("name", _("Name")),
        ],
        "min_member_words": analysis.MIN_MEMBER_WORDS,
    }
    by_month = context["by_month"]
    context["month_table"] = (
        list(
            zip(
                by_month["months"],
                by_month["series"][0]["values"],
                by_month["denominators"],
                strict=True,
            )
        )
        if by_month["series"]
        else []
    )
    peak = max((v for v in by_month["series"][0]["values"] if v is not None), default=0)
    context["y_max"] = 50 if peak <= 50 else 100
    return render(request, "language.html", context)


def _model_for(request):
    from .textmine import active_model

    lang = content_lang(request)
    model = active_model(lang) or active_model("fr" if lang == "en" else "en")
    return lang, model


def topics_view(request):
    lang, model = _model_for(request)
    topics = list(model.topics.order_by("-share")) if model else []
    peak = max((t.share for t in topics), default=0) or 1
    for t in topics:
        t.bar = round(100 * t.share / peak)
        t.percent = round(100 * t.share, 1)
    return render(request, "topics.html", {"lang": lang, "model": model, "topics": topics})


def topic_detail(request, number: int):
    from . import analysis

    lang, model = _model_for(request)
    if model is None:
        raise Http404("No topic model yet")
    topic = get_object_or_404(model.topics, number=number)
    examples = (
        topic.assignments.filter(**{f"intervention__word_count_{lang}__gte": 120})
        .select_related("intervention__sitting", "intervention__person")
        .order_by("-weight")[:8]
    )
    by_month = analysis.topic_by_month(topic)
    context = {
        "lang": lang,
        "model": model,
        "topic": topic,
        "topic_percent": round(100 * topic.share, 1),
        "terms": [(t, round(100 * w)) for t, w in topic.terms],
        "by_month": by_month,
        "by_party": analysis.topic_by_party(topic),
        "examples": examples,
        "month_table": list(
            zip(
                by_month["months"],
                by_month["series"][0]["values"],
                by_month["series"][0]["counts"],
                by_month["denominators"],
                strict=True,
            )
        ),
    }
    return render(request, "topic_detail.html", context)


def whats_new(request):
    from .models import TermShift

    lang = content_lang(request)
    shift = (
        TermShift.objects.filter(lang=lang).first()
        or TermShift.objects.filter(lang="fr" if lang == "en" else "en").first()
    )
    lists = []
    if shift:
        peak = max((abs(r["z"]) for r in shift.rising + shift.fading), default=1) or 1
        for rows in (shift.rising, shift.fading):
            for r in rows:
                r["width"] = max(4, round(100 * abs(r["z"]) / peak))
        lists = [
            (_("Used more"), shift.rising, "up"),
            (_("Used less"), shift.fading, "down"),
        ]
    return render(request, "whats_new.html", {"lang": lang, "shift": shift, "shift_lists": lists})


def _fold(text: str) -> str:
    """Lower case without accents, so 'genereux' finds 'Généreux'."""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def members_view(request):
    from . import analysis

    parliament = _parliament(request)
    q = " ".join(request.GET.get("q", "").split())[:100]
    party = request.GET.get("party", "")[:20]
    sort = request.GET.get("sort", "name")
    if sort not in analysis.MEMBER_LIST_SORTS:
        sort = "name"
    everyone = analysis.member_list(parliament)
    rows = everyone
    if q:
        needle = _fold(q)
        rows = [r for r in rows if needle in _fold(r["name"]) or needle in _fold(r["riding"])]
    if party:
        rows = [r for r in rows if r["party"] == party]
    if sort == "speeches":
        rows = sorted(rows, key=lambda r: (-r["speeches"], _fold(r["name"])))
    elif sort == "recent":
        rows = sorted(rows, key=lambda r: (r["last"], -r["speeches"]), reverse=True)
    else:
        rows = sorted(rows, key=lambda r: _fold(r["name"]))
    query = request.GET.copy()
    query.pop("sort", None)
    query.pop("lang", None)
    context = {
        "lang": content_lang(request),
        "rows": rows,
        "total": len(everyone),
        "q": q,
        "party": party,
        "parliament": parliament,
        "sort": sort,
        "sorts": [("name", _("Name")), ("speeches", _("Speeches")), ("recent", _("Most recent"))],
        "querystring": query.urlencode(),
        "parties": sorted({r["party"] for r in everyone if r["party"]}),
        "parliaments": Sitting.objects.values_list("parliament", flat=True)
        .distinct()
        .order_by("parliament"),
    }
    return render(request, "members.html", context)


def member_detail(request, slug: str):
    from . import analysis

    person = get_object_or_404(Person, slug=slug)
    lang, model = _model_for(request)
    profile = analysis.member_profile(person)
    # The chart legend in the interface language (the cached profile is shared).
    profile = {**profile, "by_month": {**profile["by_month"]}}
    profile["by_month"]["series"] = [
        {**profile["by_month"]["series"][0], "name": str(_("Speeches"))}
    ]
    speeches = (
        analysis.member_speeches(person)
        .select_related("sitting")
        .order_by("-sitting__date", "-sequence")
    )
    page = Paginator(speeches, 10).get_page(request.GET.get("page"))
    kinds = profile["by_kind"]
    from django.db.models import Q

    from .models import Vote

    member_votes = Vote.objects.filter(person=person)
    vote_summary = member_votes.aggregate(
        total=Count("id"),
        yea=Count("id", filter=Q(choice="yea")),
        nay=Count("id", filter=Q(choice="nay")),
        paired=Count("id", filter=Q(choice="paired")),
        with_line=Count("id", filter=Q(against_party__isnull=False)),
        against=Count("id", filter=Q(against_party=True)),
    )
    recent_votes = member_votes.select_related("division__sitting").order_by(
        "-division__sitting__date", "-division__number"
    )[:8]
    from .models import Meeting

    committee_meetings = (
        Meeting.objects.filter(interventions__person=person)
        .distinct()
        .select_related("committee")
        .annotate(
            n=Count("interventions", filter=Q(interventions__person=person)),
            first=Min("interventions__sequence", filter=Q(interventions__person=person)),
        )
        .order_by("-date")
    )
    committee_total = committee_meetings.count()
    committee_by = list(
        committee_meetings.order_by()
        .values("committee__acronym")
        .annotate(meetings=Count("id", distinct=True))
        .order_by("-meetings")
    )
    context = {
        "lang": lang,
        "person": person,
        "profile": profile,
        "kind_rows": [
            (_("Debate"), kinds["debate"]),
            (_("Questions"), kinds["questions"]),
            (_("Answers"), kinds["answers"]),
            (_("Members' statements"), kinds["statements"]),
        ],
        "topics": analysis.member_topics(person, model) if model else None,
        "vote_summary": vote_summary,
        "committee_meetings": committee_meetings[:8],
        "committee_total": committee_total,
        "committee_by": committee_by,
        "recent_votes": recent_votes,
        "model": model,
        "page": page,
        "min_language_words": analysis.MIN_MEMBER_LANGUAGE_WORDS,
        "min_topic_speeches": analysis.MIN_MEMBER_TOPIC_SPEECHES,
        "month_table": list(
            zip(
                profile["by_month"]["months"],
                profile["by_month"]["series"][0]["values"],
                profile["by_month"]["denominators"],
                strict=True,
            )
        ),
    }
    return render(request, "member_detail.html", context)


# -- recorded votes ----------------------------------------------------------------------

VOTE_PAGE_SIZE = 50


def _session(request):
    """?session=44-1 -> (44, 1)"""
    value = request.GET.get("session", "")
    parts = value.split("-")
    if len(parts) == 2 and all(p.isdigit() for p in parts):
        return int(parts[0]), int(parts[1])
    return None


def votes_view(request):
    from django.db.models import Q

    from .models import Division, Vote

    lang = content_lang(request)
    session = _session(request)
    result = request.GET.get("result", "")
    q = " ".join(request.GET.get("q", "").split())[:100]
    member = None
    if request.GET.get("member"):
        member = Person.objects.filter(slug=request.GET["member"][:180]).first()

    divisions = Division.objects.select_related("sitting").order_by("-sitting__date", "-number")
    if session:
        divisions = divisions.filter(sitting__parliament=session[0], sitting__session=session[1])
    if result in ("agreed", "negatived"):
        divisions = divisions.filter(result=result)
    if q:
        text = Q()
        for field in ("subject_title", "qualifier", "order_title", "object"):
            text |= Q(**{f"{field}_en__icontains": q}) | Q(**{f"{field}_fr__icontains": q})
        divisions = divisions.filter(text)
    if member:
        divisions = divisions.filter(votes__person=member)
    page = Paginator(divisions, VOTE_PAGE_SIZE).get_page(request.GET.get("page"))
    if member:
        choices = dict(
            Vote.objects.filter(person=member, division__in=list(page.object_list)).values_list(
                "division", "choice"
            )
        )
        for d in page.object_list:
            d.member_choice = choices.get(d.id)
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("lang", None)
    context = {
        "lang": lang,
        "page": page,
        "total": page.paginator.count,
        "session": f"{session[0]}-{session[1]}" if session else "",
        "sessions": [
            f"{p}-{s}"
            for p, s in Sitting.objects.filter(divisions__isnull=False)
            .values_list("parliament", "session")
            .distinct()
            .order_by("-parliament", "-session")
        ],
        "result": result,
        "q": q,
        "member": member,
        "querystring": query.urlencode(),
    }
    return render(request, "votes.html", context)


def division_detail(request, parliament: int, session: int, number: int):
    from .models import Division

    division = get_object_or_404(
        Division.objects.select_related("sitting", "bill"),
        sitting__parliament=parliament,
        sitting__session=session,
        number=number,
    )
    lang = content_lang(request)
    votes = list(division.votes.select_related("person").order_by("label"))
    parties: dict[str, dict] = {}
    for v in votes:
        row = parties.setdefault(v.party, {"party": v.party, "yea": 0, "nay": 0, "paired": 0})
        row[v.choice] += 1
    party_rows = sorted(
        parties.values(), key=lambda r: (r["party"] == "", -(r["yea"] + r["nay"] + r["paired"]))
    )
    groups = [
        ("yea", _("Yea"), [v for v in votes if v.choice == "yea"]),
        ("nay", _("Nay"), [v for v in votes if v.choice == "nay"]),
        ("paired", _("Paired"), [v for v in votes if v.choice == "paired"]),
    ]
    others = type(division).objects.filter(sitting__parliament=parliament, sitting__session=session)
    context = {
        "lang": lang,
        "division": division,
        "party_rows": party_rows,
        "groups": groups,
        "against": [v for v in votes if v.against_party],
        "unmatched": sum(1 for v in votes if v.person_id is None),
        "stage": STAGE_LABELS.get(division.bill_stage, ""),
        "previous": others.filter(number__lt=number).order_by("-number").first(),
        "next": others.filter(number__gt=number).order_by("number").first(),
    }
    return render(request, "division_detail.html", context)


# -- bills -------------------------------------------------------------------------------

STAGE_LABELS = {
    "introduction": _("Introduction and first reading"),
    "second": _("Second reading"),
    "committee": _("Referral to committee"),
    "report": _("Report stage"),
    "third": _("Third reading"),
}


def bills_view(request):
    from django.db.models import Q

    from .models import Bill

    lang = content_lang(request)
    session = _session(request)
    q = " ".join(request.GET.get("q", "").split())[:100]
    bills = Bill.objects.annotate(
        days=Count("interventions__sitting", distinct=True),
        votes=Count("divisions", distinct=True),
    ).order_by("-last_date", "-parliament", "-session", "number")
    if session:
        bills = bills.filter(parliament=session[0], session=session[1])
    if q:
        code = q.upper().replace(" ", "")
        bills = bills.filter(
            Q(code__iexact=code)
            | Q(short_title_en__icontains=q)
            | Q(short_title_fr__icontains=q)
            | Q(long_title_en__icontains=q)
            | Q(long_title_fr__icontains=q)
        )
    page = Paginator(bills, VOTE_PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("lang", None)
    context = {
        "lang": lang,
        "page": page,
        "total": page.paginator.count,
        "q": q,
        "session": f"{session[0]}-{session[1]}" if session else "",
        "sessions": [
            f"{p}-{s}"
            for p, s in Bill.objects.values_list("parliament", "session")
            .distinct()
            .order_by("-parliament", "-session")
        ],
        "querystring": query.urlencode(),
    }
    return render(request, "bills.html", context)


def bill_detail(request, parliament: int, session: int, code: str):
    from django.db.models import Q

    from .models import Bill

    bill = get_object_or_404(Bill, parliament=parliament, session=session, code=code.upper())
    if code != bill.code:
        from django.shortcuts import redirect

        return redirect(bill.get_absolute_url(), permanent=True)
    lang = content_lang(request)

    # One row per stage and day: moved, and completed when the House records it.
    steps: dict[tuple, dict] = {}
    for e in bill.timeline:
        row = steps.setdefault(
            (e["date"], e["stage"]),
            {
                "date": dt.date.fromisoformat(e["date"]),
                "stage": STAGE_LABELS.get(e["stage"], e["stage"]),
                "moved": False,
                "done": False,
                "passed": False,
                "url": None,
            },
        )
        row[e["event"]] = True
        row["passed"] = row["passed"] or e["passed"]
        if row["url"] is None:
            p, s, n = e["sitting"]
            row["url"] = f"{reverse('sitting_detail', args=[(p, s), n])}#iv-{e['sequence']}"

    speeches = bill.interventions.filter(person__isnull=False, is_chair=False)
    days = (
        bill.interventions.values(
            "sitting__parliament", "sitting__session", "sitting__number", "sitting__date"
        )
        .annotate(
            first=Min("sequence"),
            n=Count("id", filter=Q(person__isnull=False, is_chair=False)),
        )
        .order_by("sitting__date")
    )
    for d in days:
        d["url"] = (
            reverse(
                "sitting_detail",
                args=[(d["sitting__parliament"], d["sitting__session"]), d["sitting__number"]],
            )
            + f"#iv-{d['first']}"
        )
    speakers = list(
        speeches.values("person__name", "person__slug")
        .annotate(n=Count("id"), party=Max("party"))
        .order_by("-n", "person__name")[:12]
    )
    parties = list(
        speeches.exclude(party="").values("party").annotate(n=Count("id")).order_by("-n")
    )
    context = {
        "lang": lang,
        "bill": bill,
        "steps": sorted(steps.values(), key=lambda r: r["date"]),
        "divisions": bill.divisions.select_related("sitting").order_by("sitting__date", "number"),
        "days": days,
        "speakers": speakers,
        "parties": parties,
        "party_total": sum(p["n"] for p in parties),
        "stage_labels": STAGE_LABELS,
        "search_url": f"{reverse('search')}?text=en&q=%22Bill+{bill.code}%22",
    }
    return render(request, "bill_detail.html", context)


ACCESSIBILITY_REVIEWED = dt.date(2026, 10, 18)


def accessibility(request):
    return render(
        request,
        "accessibility.html",
        {"lang": ui_lang(), "reviewed": ACCESSIBILITY_REVIEWED},
    )
