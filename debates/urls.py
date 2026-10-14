from django.urls import path, register_converter

from . import views


class SessionConverter:
    """'44-1' -> (44, 1)"""

    regex = r"\d{1,3}-\d{1,2}"

    def to_python(self, value):
        parliament, session = value.split("-")
        return int(parliament), int(session)

    def to_url(self, value):
        return f"{value[0]}-{value[1]}"


register_converter(SessionConverter, "session")


def sitting_detail(request, ps, number):
    return views.sitting_detail(request, ps[0], ps[1], number)


urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search_view, name="search"),
    path("sittings/", views.sitting_list, name="sitting_list"),
    path("sittings/<session:ps>/<int:number>/", sitting_detail, name="sitting_detail"),
    path("speeches/<str:house_id>/", views.speech_detail, name="speech_detail"),
    path("trends/", views.trends_view, name="trends"),
    path("language/", views.language_view, name="language"),
    path("topics/", views.topics_view, name="topics"),
    path("topics/<int:number>/", views.topic_detail, name="topic_detail"),
    path("new/", views.whats_new, name="whats_new"),
    path("health/", views.health, name="health"),
    path("robots.txt", views.robots_txt, name="robots"),
]
