"""Bilingual full-text search over paragraphs.

Queries use PostgreSQL websearch syntax: words, "exact phrases", OR, and -excluded.
English text is searched with the en_unaccent configuration, French with fr_unaccent,
both accent-insensitive with stemming.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank
from django.db.models import Count, F, QuerySet
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import SEARCH_CONFIG, Paragraph

LANGS = ("en", "fr")
SORTS = {
    "relevance": _("Most relevant"),
    "newest": _("Newest first"),
    "oldest": _("Oldest first"),
}
RUBRIC_LABELS = {
    "OralQuestionPeriod": _("Oral Questions"),
    "StatementsByMembers": _("Statements by Members"),
    "RoutineProceedings": _("Routine Proceedings"),
    "PrivateMembersBusiness": _("Private Members' Business"),
    "LateShow": _("Adjournment Proceedings"),
    "Divisions": _("Recorded divisions"),
    "Other": _("Government Orders and other business"),
}
# Markers that cannot occur in Hansard text; swapped for <mark> after HTML-escaping.
_START, _STOP = "\u0002", "\u0003"


@dataclass
class SearchParams:
    q: str = ""
    lang: str = "en"
    party: str = ""
    person: str = ""
    rubric: str = ""
    parliament: int | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    sort: str = "relevance"
    errors: list[str] = field(default_factory=list)

    @classmethod
    def from_query_dict(cls, data, default_lang: str = "en") -> SearchParams:
        p = cls(
            q=" ".join(data.get("q", "").split())[:300],
            lang=data.get("lang") if data.get("lang") in LANGS else default_lang,
            party=data.get("party", "")[:20],
            person=" ".join(data.get("person", "").split())[:160],
            rubric=data.get("rubric", "")[:40],
            sort=data.get("sort") if data.get("sort") in SORTS else "relevance",
        )
        if data.get("parliament", "").isdigit():
            p.parliament = int(data["parliament"])
        for name in ("date_from", "date_to"):
            raw = data.get(name, "")
            if raw:
                try:
                    setattr(p, name, dt.date.fromisoformat(raw))
                except ValueError:
                    p.errors.append(_("Dates must look like 2024-03-31."))
        if p.date_from and p.date_to and p.date_from > p.date_to:
            p.date_from, p.date_to = p.date_to, p.date_from
        return p

    @property
    def config(self) -> str:
        return SEARCH_CONFIG[self.lang]

    @property
    def text_field(self) -> str:
        return f"text_{self.lang}"

    def query(self) -> SearchQuery:
        return SearchQuery(self.q, config=self.config, search_type="websearch")


def filtered(params: SearchParams) -> QuerySet:
    """Speech paragraphs matching the query and filters, annotated with rank."""
    query = params.query()
    vector = f"search_{params.lang}"
    qs = Paragraph.objects.filter(kind="speech", **{vector: query})
    if params.party:
        qs = qs.filter(intervention__party=params.party)
    if params.person:
        qs = qs.filter(intervention__person__name__iexact=params.person)
    if params.rubric:
        qs = qs.filter(intervention__rubric=params.rubric)
    if params.parliament:
        qs = qs.filter(intervention__sitting__parliament=params.parliament)
    if params.date_from:
        qs = qs.filter(intervention__sitting__date__gte=params.date_from)
    if params.date_to:
        qs = qs.filter(intervention__sitting__date__lte=params.date_to)
    return qs.annotate(rank=SearchRank(F(vector), query))


def ordered(qs: QuerySet, sort: str) -> QuerySet:
    date = "intervention__sitting__date"
    order = {
        "newest": [f"-{date}", "-intervention__sequence", "sequence"],
        "oldest": [date, "intervention__sequence", "sequence"],
    }.get(sort, ["-rank", f"-{date}", "id"])
    return qs.order_by(*order)


def party_counts(qs: QuerySet) -> list[tuple[str, int]]:
    """Matching paragraphs per party ("None" = chair occupants and the like)."""
    rows = qs.order_by().values_list("intervention__party").annotate(n=Count("id")).order_by("-n")
    return [(party or _("None"), n) for party, n in rows]


def _safe_highlight(text: str) -> str:
    return mark_safe(escape(text).replace(_START, "<mark>").replace(_STOP, "</mark>"))


def page_results(ids: list[int], params: SearchParams) -> list[Paragraph]:
    """Load one page of hits with highlighted snippets, keeping the given order.
    Headlines are computed only for this page, which keeps search fast."""
    rows = (
        Paragraph.objects.filter(id__in=ids)
        .select_related("intervention__sitting", "intervention__person")
        .annotate(
            snippet=SearchHeadline(
                params.text_field,
                params.query(),
                config=params.config,
                start_sel=_START,
                stop_sel=_STOP,
                max_words=45,
                min_words=20,
                max_fragments=2,
                fragment_delimiter=" … ",
            )
        )
    )
    by_id = {row.id: row for row in rows}
    results = []
    for pid in ids:
        row = by_id.get(pid)
        if row is not None:
            row.snippet_html = _safe_highlight(row.snippet)
            results.append(row)
    return results
