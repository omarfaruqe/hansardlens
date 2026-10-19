"""Read-only REST API (v1). Documented at /api/docs/ (OpenAPI schema at /api/schema/)."""

from __future__ import annotations

from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_field,
    inline_serializer,
)
from rest_framework import generics, serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from . import analysis, search
from .models import (
    Bill,
    Committee,
    Division,
    Intervention,
    Meeting,
    MeetingIntervention,
    Paragraph,
    Person,
    Sitting,
    TermShift,
    Vote,
    Witness,
)
from .textmine import active_model


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


# -- serializers ------------------------------------------------------------------------


class SittingSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    interventions = serializers.IntegerField(source="n", read_only=True)

    class Meta:
        model = Sitting
        fields = [
            "parliament",
            "session",
            "number",
            "date",
            "volume",
            "speaker_of_house",
            "has_french",
            "interventions",
            "url",
        ]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


class SpeakerSerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True)
    role = serializers.CharField(allow_blank=True)
    party = serializers.CharField(allow_blank=True)
    riding = serializers.CharField(allow_blank=True)
    is_chair = serializers.BooleanField()
    label_en = serializers.CharField(allow_blank=True)
    label_fr = serializers.CharField(allow_blank=True)


def speaker_of(iv: Intervention) -> dict:
    return {
        "name": iv.person.name if iv.person else "",
        "role": iv.speaker_role,
        "party": iv.party,
        "riding": iv.riding,
        "is_chair": iv.is_chair,
        "label_en": iv.speaker_label_en,
        "label_fr": iv.speaker_label_fr,
    }


class InterventionSummarySerializer(serializers.ModelSerializer):
    speaker = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()

    class Meta:
        model = Intervention
        fields = [
            "sequence",
            "house_id",
            "kind",
            "rubric",
            "order_title_en",
            "order_title_fr",
            "subject_title_en",
            "subject_title_fr",
            "time",
            "speaker",
            "word_count_en",
            "word_count_fr",
            "floor_words_en",
            "floor_words_fr",
            "url",
        ]

    @extend_schema_field(SpeakerSerializer)
    def get_speaker(self, obj) -> dict:
        return speaker_of(obj)

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


class ParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = Paragraph
        fields = [
            "sequence",
            "house_id",
            "kind",
            "floor_language",
            "words_en",
            "text_en",
            "text_fr",
        ]


class SpeechSerializer(InterventionSummarySerializer):
    sitting = SittingSerializer(read_only=True)
    paragraphs = ParagraphSerializer(many=True, read_only=True)

    class Meta(InterventionSummarySerializer.Meta):
        fields = InterventionSummarySerializer.Meta.fields + ["sitting", "paragraphs"]


class SittingDetailSerializer(SittingSerializer):
    items = InterventionSummarySerializer(source="interventions", many=True, read_only=True)

    class Meta(SittingSerializer.Meta):
        fields = SittingSerializer.Meta.fields + ["items"]


class PersonSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ["name", "slug", "latest_party", "latest_riding", "latest_seen", "url"]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


# -- views ------------------------------------------------------------------------------

DATE = OpenApiTypes.DATE


@extend_schema(
    tags=["Sittings"],
    parameters=[
        OpenApiParameter("parliament", int),
        OpenApiParameter("session", int),
        OpenApiParameter("date_from", DATE),
        OpenApiParameter("date_to", DATE),
    ],
)
class SittingList(generics.ListAPIView):
    """Sitting days, newest first."""

    serializer_class = SittingSerializer
    pagination_class = Pagination

    def get_queryset(self):
        qs = Sitting.objects.annotate(n=Count("interventions")).order_by("-date")
        p = self.request.query_params
        for field in ("parliament", "session"):
            if p.get(field, "").isdigit():
                qs = qs.filter(**{field: int(p[field])})
        if p.get("date_from"):
            qs = qs.filter(date__gte=_date(p["date_from"]))
        if p.get("date_to"):
            qs = qs.filter(date__lte=_date(p["date_to"]))
        return qs


@extend_schema(tags=["Sittings"])
class SittingDetail(generics.RetrieveAPIView):
    """One sitting with every intervention in order (without full text)."""

    serializer_class = SittingDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Sitting.objects.annotate(n=Count("interventions")).prefetch_related(
                "interventions__person"
            ),
            parliament=self.kwargs["ps"][0],
            session=self.kwargs["ps"][1],
            number=self.kwargs["number"],
        )


@extend_schema(tags=["Speeches"])
class SpeechDetail(generics.RetrieveAPIView):
    """One speech with every paragraph in English and French and the floor language."""

    serializer_class = SpeechSerializer

    def get_object(self):
        iv = (
            Intervention.objects.filter(house_id=self.kwargs["house_id"])
            .select_related("sitting", "person")
            .prefetch_related("paragraphs")
            .first()
        )
        if iv is None:
            raise Http404
        iv.sitting.n = iv.sitting.interventions.count()
        return iv


@extend_schema(
    tags=["People"],
    parameters=[
        OpenApiParameter("party", str),
        OpenApiParameter("name", str, description="Part of a name"),
    ],
)
class PersonList(generics.ListAPIView):
    """People who have spoken, with their most recent party and riding."""

    serializer_class = PersonSerializer
    pagination_class = Pagination

    def get_queryset(self):
        qs = Person.objects.order_by("name")
        p = self.request.query_params
        if p.get("party"):
            qs = qs.filter(latest_party=p["party"])
        if p.get("name"):
            qs = qs.filter(name__icontains=p["name"][:100])
        return qs


@extend_schema(
    tags=["People"],
    parameters=[
        OpenApiParameter("text", str, enum=["en", "fr"], description="Topic model language")
    ],
    responses=OpenApiTypes.OBJECT,
)
class PersonDetail(APIView):
    """One person: speech counts by kind and month, parties, ridings and roles over
    time, the share spoken in French, and their main topics."""

    def get(self, request, slug: str):
        person = get_object_or_404(Person, slug=slug)
        lang = request.query_params.get("text", "en")
        model = active_model(lang if lang in ("en", "fr") else "en")
        profile = analysis.member_profile(person)
        return Response(
            {
                **PersonSerializer(person).data,
                **profile,
                "topics": analysis.member_topics(person, model) if model else None,
            }
        )


# -- recorded votes ------------------------------------------------------------------


class DivisionSerializer(serializers.ModelSerializer):
    parliament = serializers.IntegerField(source="sitting.parliament")
    session = serializers.IntegerField(source="sitting.session")
    date = serializers.DateField(source="sitting.date")
    url = serializers.SerializerMethodField()
    official_url = serializers.SerializerMethodField()

    class Meta:
        model = Division
        fields = [
            "parliament",
            "session",
            "number",
            "date",
            "time",
            "order_title_en",
            "order_title_fr",
            "subject_title_en",
            "subject_title_fr",
            "qualifier_en",
            "qualifier_fr",
            "object_en",
            "object_fr",
            "result",
            "yeas",
            "nays",
            "paired",
            "url",
            "official_url",
        ]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()

    def get_official_url(self, obj) -> str:
        return obj.official_url("en")


class VoteSerializer(serializers.ModelSerializer):
    person = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        model = Vote
        fields = ["label", "name", "person", "party", "choice", "against_party"]

    def get_name(self, obj) -> str:
        return obj.person.name if obj.person else ""


class DivisionDetailSerializer(DivisionSerializer):
    votes = VoteSerializer(many=True, read_only=True)

    class Meta(DivisionSerializer.Meta):
        fields = DivisionSerializer.Meta.fields + ["votes"]


@extend_schema(
    tags=["Votes"],
    parameters=[
        OpenApiParameter("parliament", int),
        OpenApiParameter("session", int),
        OpenApiParameter("result", str, enum=["agreed", "negatived"]),
        OpenApiParameter("member", str, description="Member slug: only votes they took part in"),
    ],
)
class DivisionList(generics.ListAPIView):
    """Recorded votes (divisions), newest first."""

    serializer_class = DivisionSerializer
    pagination_class = Pagination

    def get_queryset(self):
        qs = Division.objects.select_related("sitting").order_by("-sitting__date", "-number")
        p = self.request.query_params
        for field in ("parliament", "session"):
            if p.get(field, "").isdigit():
                qs = qs.filter(**{f"sitting__{field}": int(p[field])})
        if p.get("result") in ("agreed", "negatived"):
            qs = qs.filter(result=p["result"])
        if p.get("member"):
            qs = qs.filter(votes__person__slug=p["member"][:180])
        return qs


@extend_schema(tags=["Votes"])
class DivisionDetail(generics.RetrieveAPIView):
    """One recorded vote with every member's vote, party at the time and whether it
    differed from most of their party."""

    serializer_class = DivisionDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Division.objects.select_related("sitting").prefetch_related("votes__person"),
            sitting__parliament=self.kwargs["ps"][0],
            sitting__session=self.kwargs["ps"][1],
            number=self.kwargs["number"],
        )


# -- bills ---------------------------------------------------------------------------


class BillSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    legisinfo_url = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            "parliament",
            "session",
            "code",
            "short_title_en",
            "short_title_fr",
            "long_title_en",
            "long_title_fr",
            "first_date",
            "last_date",
            "speeches",
            "mentions",
            "url",
            "legisinfo_url",
        ]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()

    def get_legisinfo_url(self, obj) -> str:
        return obj.legisinfo_url("en")


class BillDetailSerializer(BillSerializer):
    divisions = serializers.SerializerMethodField()

    class Meta(BillSerializer.Meta):
        fields = BillSerializer.Meta.fields + ["timeline", "divisions"]

    def get_divisions(self, obj) -> list[dict]:
        return [
            {**DivisionSerializer(d).data, "stage": d.bill_stage}
            for d in obj.divisions.select_related("sitting").order_by("sitting__date", "number")
        ]


@extend_schema(
    tags=["Bills"],
    parameters=[
        OpenApiParameter("parliament", int),
        OpenApiParameter("session", int),
        OpenApiParameter("q", str, description="Bill number or part of a title"),
    ],
)
class BillList(generics.ListAPIView):
    """Bills debated in the House, most recently debated first."""

    serializer_class = BillSerializer
    pagination_class = Pagination

    def get_queryset(self):
        from django.db.models import Q

        qs = Bill.objects.order_by("-last_date", "-parliament", "-session", "number")
        p = self.request.query_params
        for field in ("parliament", "session"):
            if p.get(field, "").isdigit():
                qs = qs.filter(**{field: int(p[field])})
        if p.get("q"):
            q = p["q"][:100]
            qs = qs.filter(
                Q(code__iexact=q.replace(" ", ""))
                | Q(short_title_en__icontains=q)
                | Q(short_title_fr__icontains=q)
            )
        return qs


@extend_schema(tags=["Bills"])
class BillDetail(generics.RetrieveAPIView):
    """One bill: titles, stages moved and completed in the House, recorded votes."""

    serializer_class = BillDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Bill,
            parliament=self.kwargs["ps"][0],
            session=self.kwargs["ps"][1],
            code=self.kwargs["code"].upper(),
        )


# -- committees ------------------------------------------------------------------------


class CommitteeSerializer(serializers.ModelSerializer):
    meetings = serializers.IntegerField(source="meetings_n", read_only=True)
    first_date = serializers.DateField(read_only=True)
    last_date = serializers.DateField(read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = Committee
        fields = ["acronym", "name_en", "name_fr", "meetings", "first_date", "last_date", "url"]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


class MeetingSerializer(serializers.ModelSerializer):
    committee = serializers.CharField(source="committee.acronym")
    witnesses = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    evidence_url_en = serializers.CharField(read_only=True)
    evidence_url_fr = serializers.CharField(read_only=True)

    class Meta:
        model = Meeting
        fields = [
            "committee",
            "parliament",
            "session",
            "number",
            "date",
            "chair",
            "witnesses",
            "url",
            "evidence_url_en",
            "evidence_url_fr",
        ]

    def get_witnesses(self, obj) -> list[dict]:
        seen, out = set(), []
        for i in obj.interventions.all():
            if i.witness_id and i.witness_id not in seen:
                seen.add(i.witness_id)
                out.append(
                    {
                        "name": i.witness.name,
                        "slug": i.witness.slug,
                        "title_en": i.detail_en,
                        "title_fr": i.detail_fr,
                    }
                )
        return out

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


class MeetingInterventionSerializer(serializers.ModelSerializer):
    person = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    witness = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    paragraphs = serializers.SerializerMethodField()

    class Meta:
        model = MeetingIntervention
        fields = [
            "sequence",
            "role",
            "name",
            "detail_en",
            "detail_fr",
            "party",
            "person",
            "witness",
            "time",
            "paragraphs",
        ]

    def get_paragraphs(self, obj) -> list[dict]:
        return [
            {
                "kind": p.kind,
                "floor_language": p.floor_language,
                "text_en": p.text_en,
                "text_fr": p.text_fr,
            }
            for p in obj.paragraphs.all()
        ]


class MeetingDetailSerializer(MeetingSerializer):
    committee_name_en = serializers.CharField(source="committee.name_en")
    committee_name_fr = serializers.CharField(source="committee.name_fr")
    interventions = MeetingInterventionSerializer(many=True, read_only=True)

    class Meta(MeetingSerializer.Meta):
        fields = MeetingSerializer.Meta.fields + [
            "committee_name_en",
            "committee_name_fr",
            "interventions",
        ]


class WitnessSerializer(serializers.ModelSerializer):
    meetings = serializers.IntegerField(source="meetings_n", read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = Witness
        fields = [
            "slug",
            "name",
            "title_en",
            "title_fr",
            "affiliation_en",
            "affiliation_fr",
            "as_individual",
            "latest_date",
            "meetings",
            "url",
        ]

    def get_url(self, obj) -> str:
        return obj.get_absolute_url()


class WitnessDetailSerializer(WitnessSerializer):
    appearances = serializers.SerializerMethodField()

    class Meta(WitnessSerializer.Meta):
        fields = WitnessSerializer.Meta.fields + ["appearances"]

    def get_appearances(self, obj) -> list[dict]:
        rows = {}
        for i in obj.interventions.select_related("meeting__committee").order_by(
            "-meeting__date", "meeting_id", "sequence"
        ):
            m = i.meeting
            row = rows.setdefault(
                m.id,
                {
                    "committee": m.committee.acronym,
                    "parliament": m.parliament,
                    "session": m.session,
                    "number": m.number,
                    "date": m.date,
                    "title_en": i.detail_en,
                    "title_fr": i.detail_fr,
                    "interventions": 0,
                    "url": m.get_absolute_url(),
                },
            )
            row["interventions"] += 1
        return list(rows.values())


@extend_schema(tags=["Committees"])
class CommitteeList(generics.ListAPIView):
    """Committees whose public meeting transcripts are loaded."""

    serializer_class = CommitteeSerializer
    pagination_class = None

    def get_queryset(self):
        from django.db.models import Max, Min

        return Committee.objects.annotate(
            meetings_n=Count("meetings"),
            first_date=Min("meetings__date"),
            last_date=Max("meetings__date"),
        ).order_by("acronym")


@extend_schema(
    tags=["Committees"],
    parameters=[OpenApiParameter("parliament", int), OpenApiParameter("session", int)],
)
class MeetingList(generics.ListAPIView):
    """Public meetings of one committee, most recent first, with the witnesses heard."""

    serializer_class = MeetingSerializer
    pagination_class = Pagination

    def get_queryset(self):
        committee = get_object_or_404(Committee, acronym=self.kwargs["acronym"].upper())
        qs = committee.meetings.select_related("committee").prefetch_related(
            "interventions__witness"
        )
        p = self.request.query_params
        for field in ("parliament", "session"):
            if p.get(field, "").isdigit():
                qs = qs.filter(**{field: int(p[field])})
        return qs.order_by("-date", "-number")


@extend_schema(tags=["Committees"])
class MeetingDetail(generics.RetrieveAPIView):
    """One meeting: who spoke, in order, with the English and French text of each paragraph."""

    serializer_class = MeetingDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Meeting.objects.select_related("committee").prefetch_related(
                "interventions__person", "interventions__witness", "interventions__paragraphs"
            ),
            committee__acronym=self.kwargs["acronym"].upper(),
            parliament=self.kwargs["ps"][0],
            session=self.kwargs["ps"][1],
            number=self.kwargs["number"],
        )


@extend_schema(
    tags=["Committees"],
    parameters=[
        OpenApiParameter("q", str, description="Part of a name, title or organisation"),
        OpenApiParameter("committee", str, description="Committee acronym, e.g. FINA"),
    ],
)
class WitnessList(generics.ListAPIView):
    """Witnesses heard by the loaded committees, most recently heard first."""

    serializer_class = WitnessSerializer
    pagination_class = Pagination

    def get_queryset(self):
        from .committee_views import find_witnesses

        p = self.request.query_params
        q = " ".join(p.get("q", "").split())[:100]
        return find_witnesses(q, p.get("committee", "").upper()[:8]).order_by(
            "-latest_date", "name"
        )


@extend_schema(tags=["Committees"])
class WitnessDetail(generics.RetrieveAPIView):
    """One witness and every meeting at which they gave evidence."""

    serializer_class = WitnessDetailSerializer

    def get_object(self):
        from .committee_views import find_witnesses

        return get_object_or_404(find_witnesses(), slug=self.kwargs["slug"])


SEARCH_PARAMS = [
    OpenApiParameter(
        "q", str, required=True, description='Web-style query: words, "phrases", OR, -exclude'
    ),
    OpenApiParameter(
        "text", str, enum=["en", "fr"], description="Which text to search (default en)"
    ),
    OpenApiParameter("party", str),
    OpenApiParameter("person", str),
    OpenApiParameter("rubric", str, enum=list(search.RUBRIC_LABELS)),
    OpenApiParameter("parliament", int),
    OpenApiParameter("date_from", DATE),
    OpenApiParameter("date_to", DATE),
    OpenApiParameter("sort", str, enum=list(search.SORTS)),
]


class SearchResultSerializer(serializers.Serializer):
    paragraph = serializers.IntegerField()
    speech = serializers.CharField()
    date = serializers.DateField()
    speaker = serializers.CharField()
    party = serializers.CharField()
    subject = serializers.CharField()
    floor_language = serializers.CharField()
    snippet_html = serializers.CharField(help_text="HTML-escaped, matches wrapped in <mark>")
    url = serializers.CharField()


@extend_schema(
    tags=["Search"], parameters=SEARCH_PARAMS, responses=SearchResultSerializer(many=True)
)
class SearchView(APIView):
    """Bilingual full-text search over speech paragraphs, paginated."""

    def get(self, request):
        data = request.query_params.copy()
        if "text" in data:
            data["lang"] = data["text"]
        params = search.SearchParams.from_query_dict(data, default_lang="en")
        if not params.q:
            raise serializers.ValidationError({"q": "Required."})
        if params.errors:
            raise serializers.ValidationError({"dates": [str(e) for e in params.errors]})
        ids = search.ordered(search.filtered(params), params.sort).values_list("id", flat=True)
        paginator = Pagination()
        page = paginator.paginate_queryset(ids, request, view=self)
        rows = search.page_results(list(page), params)
        results = [
            {
                "paragraph": p.id,
                "speech": p.intervention.house_id,
                "date": p.intervention.sitting.date,
                "speaker": p.intervention.speaker_display,
                "party": p.intervention.party,
                "subject": getattr(p.intervention, f"subject_title_{params.lang}"),
                "floor_language": p.floor_language,
                "snippet_html": str(p.snippet_html),
                "url": f"{p.intervention.get_absolute_url()}?text={params.lang}#p-{p.sequence}",
            }
            for p in rows
        ]
        return paginator.get_paginated_response(results)


SERIES = inline_serializer(
    "Series",
    {
        "months": serializers.ListField(child=serializers.CharField()),
        "denominators": serializers.ListField(child=serializers.IntegerField(allow_null=True)),
        "series": serializers.ListField(child=serializers.DictField()),
        "unit": serializers.CharField(),
    },
)


@extend_schema(
    tags=["Analysis"],
    parameters=[
        OpenApiParameter(
            "term", str, many=True, required=True, description="Up to 4; repeat the parameter"
        ),
        OpenApiParameter("text", str, enum=["en", "fr"]),
        OpenApiParameter("party", str),
        OpenApiParameter("parliament", int),
    ],
    responses=SERIES,
)
class TrendsView(APIView):
    """Paragraphs mentioning each term per 1,000 speech paragraphs, by month."""

    def get(self, request):
        p = request.query_params
        terms = [t[:120] for t in p.getlist("term")][: analysis.MAX_TERMS]
        if not any(t.strip() for t in terms):
            raise serializers.ValidationError({"term": "At least one term is required."})
        lang = p.get("text") if p.get("text") in search.LANGS else "en"
        parliament = int(p["parliament"]) if p.get("parliament", "").isdigit() else None
        return Response(
            analysis.term_trends(
                terms, lang=lang, party=p.get("party", "")[:20], parliament=parliament
            )
        )


@extend_schema(
    tags=["Analysis"],
    parameters=[OpenApiParameter("parliament", int)],
    responses=OpenApiTypes.OBJECT,
)
class LanguageView(APIView):
    """Share of speech given in French: overall, by month, by party and by member."""

    def get(self, request):
        p = request.query_params
        parliament = int(p["parliament"]) if p.get("parliament", "").isdigit() else None
        return Response(
            {
                "method": (
                    "Words measured on the English text of each paragraph, "
                    "whichever language was spoken."
                ),
                "overall": analysis.language_overall(parliament),
                "by_month": analysis.language_by_month(parliament),
                "by_party": analysis.language_by_party(parliament),
                "by_member": analysis.language_by_member(parliament),
            }
        )


def _topic_json(t) -> dict:
    return {
        "number": t.number,
        "label": t.label,
        "title": t.title,
        "share": t.share,
        "terms": t.terms,
    }


TEXT_PARAM = OpenApiParameter(
    "text", str, enum=["en", "fr"], description="Model language (default en)"
)


@extend_schema(tags=["Analysis"], parameters=[TEXT_PARAM], responses=OpenApiTypes.OBJECT)
class TopicList(APIView):
    """The active topic model and its topics."""

    def get(self, request):
        model = active_model(request.query_params.get("text", "en"))
        if model is None:
            raise Http404
        return Response(
            {
                "lang": model.lang,
                "created_at": model.created_at,
                "documents": model.n_documents,
                "first_date": model.first_date,
                "last_date": model.last_date,
                "params": model.params,
                "topics": [_topic_json(t) for t in model.topics.order_by("-share")],
            }
        )


@extend_schema(tags=["Analysis"], parameters=[TEXT_PARAM], responses=OpenApiTypes.OBJECT)
class TopicDetail(APIView):
    """One topic: words, monthly share, share of each party's speeches, top speeches."""

    def get(self, request, number: int):
        model = active_model(request.query_params.get("text", "en"))
        if model is None:
            raise Http404
        topic = get_object_or_404(model.topics, number=number)
        top = topic.assignments.select_related("intervention").order_by("-weight")[:20]
        return Response(
            {
                **_topic_json(topic),
                "by_month": analysis.topic_by_month(topic),
                "by_party": analysis.topic_by_party(topic),
                "top_speeches": [
                    {"speech": a.intervention.house_id, "weight": a.weight} for a in top
                ],
            }
        )


@extend_schema(tags=["Analysis"], parameters=[TEXT_PARAM], responses=OpenApiTypes.OBJECT)
class TermShiftView(APIView):
    """Terms rising and fading in the recent window (log-odds with informative prior)."""

    def get(self, request):
        shift = TermShift.objects.filter(lang=request.query_params.get("text", "en")).first()
        if shift is None:
            raise Http404
        return Response(
            {
                "recent": [shift.recent_start, shift.recent_end],
                "baseline": [shift.base_start, shift.base_end],
                "words_recent": shift.words_recent,
                "words_base": shift.words_base,
                "rising": shift.rising,
                "fading": shift.fading,
                "params": shift.params,
            }
        )


def _date(value: str):
    import datetime as dt

    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise serializers.ValidationError({"date": "Use YYYY-MM-DD."}) from exc
