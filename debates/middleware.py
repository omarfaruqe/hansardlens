"""Interface language from ?lang=en|fr, remembered in a cookie.

LocaleMiddleware already reads the cookie and the browser's Accept-Language; this lets a
plain link switch language and keeps the choice. The language of debate *text* being
searched or shown is a separate parameter (?text=), so the interface can be French while
reading English text.
"""

from django.conf import settings
from django.utils import translation


class LanguageParameterMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.GET.get("lang")
        chosen = lang if lang in dict(settings.LANGUAGES) else None
        if chosen:
            translation.activate(chosen)
            request.LANGUAGE_CODE = chosen
        response = self.get_response(request)
        if chosen and request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) != chosen:
            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME,
                chosen,
                max_age=settings.LANGUAGE_COOKIE_AGE,
                path=settings.LANGUAGE_COOKIE_PATH,
                samesite=settings.LANGUAGE_COOKIE_SAMESITE,
                secure=getattr(settings, "LANGUAGE_COOKIE_SECURE", False),
            )
        return response
