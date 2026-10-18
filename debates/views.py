from itertools import groupby

from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Max, Min
from django.http import Http404, HttpResponse, HttpResponseServerError, JsonResponse
from django.shortcuts import get_object_or_404, render
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
    iv = Intervention.objects.filter(house_id=house_id).select_related("sitting", "person").first()
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
