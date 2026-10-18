"""Serving under a URL prefix, as behind nginx at /maplemetrics/hansardlens/.

The proxy strips the prefix, so requests arrive as /search/; FORCE_SCRIPT_NAME makes
Django put the prefix back on every link, static file and cookie."""

from pathlib import Path

import pytest
from django.test import override_settings

from debates.loader import store
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
PREFIX = "/maplemetrics/hansardlens"
pytestmark = pytest.mark.django_db

subpath = override_settings(
    FORCE_SCRIPT_NAME=PREFIX,
    LANGUAGE_COOKIE_PATH=f"{PREFIX}/",
    STATIC_URL=f"{PREFIX}/static/",  # computed once at startup in production
)


@pytest.fixture(autouse=True)
def script_prefix():
    """The real WSGI handler sets the prefix on each request from FORCE_SCRIPT_NAME;
    Django's test client does not, so set it here (the end-to-end check covers the
    real server)."""
    from django.urls import set_script_prefix

    set_script_prefix(f"{PREFIX}/")
    yield
    set_script_prefix("/")


@pytest.fixture
def sitting():
    en = parse_document((FIXTURES / "sitting_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "sitting_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


@subpath
def test_links_and_static_files_carry_the_prefix(client, sitting):
    html = client.get("/search/", {"q": "bridge"}).content.decode()
    assert f'href="{PREFIX}/static/css/site' in html
    assert f'href="{PREFIX}/trends/"' in html
    assert f"{PREFIX}/speeches/1001/?text=en#p-1" in html
    assert f'href="{PREFIX}/search/?q=bridge&amp;lang=fr"' in html  # language switch
    assert 'href="/search/' not in html and 'href="/static/' not in html


@subpath
def test_api_urls_and_docs_carry_the_prefix(client, sitting):
    data = client.get("/api/v1/sittings/").json()
    assert data["results"][0]["url"] == f"{PREFIX}/sittings/44-1/50/"
    assert f"{PREFIX}/api/schema/" in client.get("/api/docs/").content.decode()


@subpath
def test_language_cookie_is_scoped_to_the_prefix(client):
    response = client.get("/", {"lang": "fr"})
    assert response.cookies["hansardlens_language"]["path"] == f"{PREFIX}/"


@subpath
def test_robots_and_error_pages(client):
    assert f"Disallow: {PREFIX}/api/".encode() in client.get("/robots.txt").content
    from debates.views import server_error

    assert f'href="{PREFIX}/"'.encode() in server_error(None).content


def test_cookie_names_do_not_clash_with_other_django_apps(settings):
    assert settings.SESSION_COOKIE_NAME == "hansardlens_sessionid"
    assert settings.CSRF_COOKIE_NAME == "hansardlens_csrftoken"
