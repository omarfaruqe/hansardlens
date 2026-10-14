from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api_docs"),
    path("api/v1/", include("debates.api_urls")),
    path("", include("debates.urls")),
]

handler404 = "debates.views.not_found"
handler500 = "debates.views.server_error"
