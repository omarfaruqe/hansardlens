from django.urls import path

from . import api
from .urls import SessionConverter  # noqa: F401  (registers the "session" and "billcode" converters)

urlpatterns = [
    path("sittings/", api.SittingList.as_view(), name="api_sittings"),
    path("sittings/<session:ps>/<int:number>/", api.SittingDetail.as_view(), name="api_sitting"),
    path("speeches/<str:house_id>/", api.SpeechDetail.as_view(), name="api_speech"),
    path("people/", api.PersonList.as_view(), name="api_people"),
    path("people/<slug:slug>/", api.PersonDetail.as_view(), name="api_person"),
    path("bills/", api.BillList.as_view(), name="api_bills"),
    path("bills/<session:ps>/<billcode:code>/", api.BillDetail.as_view(), name="api_bill"),
    path("votes/", api.DivisionList.as_view(), name="api_votes"),
    path("votes/<session:ps>/<int:number>/", api.DivisionDetail.as_view(), name="api_vote"),
    path("search/", api.SearchView.as_view(), name="api_search"),
    path("trends/", api.TrendsView.as_view(), name="api_trends"),
    path("language/", api.LanguageView.as_view(), name="api_language"),
    path("topics/", api.TopicList.as_view(), name="api_topics"),
    path("topics/<int:number>/", api.TopicDetail.as_view(), name="api_topic"),
    path("term-shifts/", api.TermShiftView.as_view(), name="api_term_shifts"),
]
