"""Structural accessibility checks on every type of page, in both languages (WCAG 2.1:
1.1.1, 1.3.1, 2.4.1, 2.4.2, 3.1.1, 3.1.2, 3.3.2, 4.1.2). The full audit, with axe-core
and keyboard testing in a browser, is described in docs/ACCESSIBILITY.md."""

from html.parser import HTMLParser
from pathlib import Path

import pytest

from debates.loader import store
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.html_lang = None
        self.title = ""
        self._in_title = False
        self.h1 = 0
        self.mains = 0
        self.ids = set()
        self.label_for = set()
        self.fields = []  # (attrs, inside a <label>)
        self.label_depth = 0
        self.images = []
        self.first_link = None
        self.langs = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "lang" in a and tag != "html":
            self.langs.append(a["lang"])
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "main":
            self.mains += 1
        elif tag == "label":
            self.label_depth += 1
            if a.get("for"):
                self.label_for.add(a["for"])
        elif tag in ("input", "select", "textarea"):
            if a.get("type") not in ("hidden", "submit", "button"):
                self.fields.append((a, self.label_depth > 0))
        elif tag == "img":
            self.images.append(a)
        elif tag == "a" and self.first_link is None:
            self.first_link = a

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "label":
            self.label_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data


@pytest.fixture
def data():
    for name in ("sitting", "votes"):
        en = parse_document((FIXTURES / f"{name}_en.xml").read_bytes())
        fr = parse_document((FIXTURES / f"{name}_fr.xml").read_bytes())
        store(merge(en, fr))
    from debates.bills import build_bills

    build_bills()


PAGES = [
    "/",
    "/search/",
    "/search/?q=bridge",
    "/sittings/",
    "/sittings/44-1/50/",
    "/speeches/1001/",
    "/members/",
    "/members/luc-martel/",
    "/votes/",
    "/votes/44-1/54/",
    "/bills/",
    "/trends/?t1=bridge",
    "/language/",
    "/topics/",
    "/new/",
    "/accessibility/",
    "/no-such-page/",
]


@pytest.mark.parametrize("lang", ["en", "fr"])
@pytest.mark.parametrize("url", PAGES)
def test_page_structure(client, data, url, lang):
    sep = "&" if "?" in url else "?"
    response = client.get(f"{url}{sep}lang={lang}")
    assert response.status_code in (200, 404)
    page = Page()
    page.feed(response.content.decode())

    assert page.html_lang == lang  # 3.1.1 language of page
    assert page.title.strip() and "HansardLens" in page.title  # 2.4.2 page titled
    assert page.h1 == 1  # one main heading
    assert page.mains == 1 and "main" in page.ids  # main landmark, skip-link target
    assert page.first_link.get("href") == "#main"  # 2.4.1 bypass blocks: skip link first
    for attrs, wrapped in page.fields:  # 3.3.2 / 4.1.2 every field has a name
        named = wrapped or attrs.get("aria-label") or attrs.get("id") in page.label_for
        assert named, f"unlabelled field {attrs}"
    for img in page.images:  # 1.1.1 text alternatives
        assert "alt" in img
    assert set(page.langs) <= {"en", "fr"}  # 3.1.2 language of parts


def test_accessibility_statement(client):
    html = client.get("/accessibility/").content.decode()
    assert "WCAG 2.1" in html and "Known limitations" in html
    assert 'href="/accessibility/"' in html  # linked from the footer
    assert "Accessibilité" in client.get("/accessibility/", {"lang": "fr"}).content.decode()


def test_api_docs_page_has_language_and_heading(client):
    page = Page()
    page.feed(client.get("/api/docs/").content.decode())
    assert page.html_lang == "en" and page.h1 == 1 and page.mains == 1
