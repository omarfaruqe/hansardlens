from django import template
from django.contrib.humanize.templatetags.humanize import ordinal
from django.utils import dateformat
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from django.utils.translation import get_language, gettext

register = template.Library()

DATE_FORMATS = {
    # style: (English, French)
    "long": ("l, F j, Y", "l j F Y"),  # Wednesday, October 14, 2026 / mercredi 14 octobre 2026
    "date": ("F j, Y", "j F Y"),  # October 14, 2026 / 14 octobre 2026
    "short": ("D, M j, Y", "D j M Y"),  # Wed, Oct 14, 2026 / mer 14 oct 2026
    "day": ("F j", "j F"),
    "month": ("F Y", "F Y"),
}
PARTY_FR = {"CPC": "PCC", "NDP": "NPD", "GP": "PV"}


def _is_fr() -> bool:
    return (get_language() or "en").startswith("fr")


@register.filter
def ldate(value, style="date"):
    """Locale-aware date: {{ sitting.date|ldate:"long" }}"""
    if not value:
        return ""
    en, fr = DATE_FORMATS.get(style, DATE_FORMATS["date"])
    if not _is_fr():
        return dateformat.format(value, en)
    text = dateformat.format(value, fr)
    if value.day == 1 and "j" in fr:  # French writes the first of the month as "1er"
        text = text.replace(" 1 ", " 1er ", 1) if " 1 " in f" {text} " else text
        if text.startswith("1 "):
            text = "1er " + text[2:]
    return text


@register.filter
def party(code):
    """Party abbreviation in the interface language (data keeps the English codes)."""
    if not code:
        return ""
    return PARTY_FR.get(code, code) if _is_fr() else code


@register.filter
def ordinal_parliament(number):
    """44 -> '44th Parliament' / '44<sup>e</sup> législature' (French ordinals are HTML)."""
    label = conditional_escape(gettext("%(nth)s Parliament"))
    return mark_safe(label % {"nth": ordinal(number)})


@register.simple_tag
def field(obj, name: str, lang: str):
    """{% field iv "subject_title" lang %} -> iv.subject_title_en / _fr"""
    return getattr(obj, f"{name}_{lang}", "")


@register.simple_tag(takes_context=True)
def switch_language_url(context):
    """Current page in the other interface language (debate text follows it)."""
    request = context["request"]
    query = request.GET.copy()
    query.pop("text", None)
    query.pop("page", None)
    query["lang"] = "en" if _is_fr() else "fr"
    return f"{request.path}?{query.urlencode()}"


@register.simple_tag(takes_context=True)
def with_text(context, lang):
    """Current page with the debate text in `lang`, keeping other parameters."""
    request = context["request"]
    query = request.GET.copy()
    query.pop("page", None)
    query["text"] = lang
    return f"{request.path}?{query.urlencode()}"


@register.filter
def pct_of(value, total):
    try:
        return round(100 * value / total)
    except (TypeError, ZeroDivisionError):
        return 0
