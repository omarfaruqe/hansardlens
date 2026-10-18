from pathlib import Path

import pytest

from debates.loader import store
from debates.models import Division
from debates.parsing import merge, parse_document

FIXTURES = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.django_db


@pytest.fixture
def sitting():
    en = parse_document((FIXTURES / "votes_en.xml").read_bytes())
    fr = parse_document((FIXTURES / "votes_fr.xml").read_bytes())
    return store(merge(en, fr)).sitting


def test_division_url(sitting):
    assert Division.objects.get(number=54).get_absolute_url() == "/votes/44-1/54/"


def test_vote_list(client, sitting):
    html = client.get("/votes/").content.decode()
    assert "3 recorded votes" in html
    assert 'href="/votes/44-1/54/?text=en"' in html
    assert "Opposition Motion—Example Rents" in html and "Motion No. 1" in html


def test_vote_list_filters(client, sitting):
    html = client.get("/votes/", {"result": "negatived"}).content.decode()
    assert "1 recorded vote" in html and "Example Rents" in html
    html = client.get("/votes/", {"q": "agency"}).content.decode()  # qualifier text
    assert "1 recorded vote" in html and "Concurrence in Vote 1" in html
    html = client.get("/votes/", {"q": "agence"}).content.decode()  # French text too
    assert "1 recorded vote" in html
    assert "0 recorded votes" in client.get("/votes/", {"session": "45-1"}).content.decode()


def test_vote_list_for_member_shows_their_vote(client, sitting):
    html = client.get("/votes/", {"member": "tom-reed"}).content.decode()
    assert "Recorded votes: Tom Reed" in html
    assert "2 recorded votes" in html  # Tom Reed voted in 54 and 55, not 56
    assert "<strong>Yea</strong>" in html


def test_division_page(client, sitting):
    html = client.get("/votes/44-1/54/").content.decode()
    assert "Opposition Motion—Example Rents" in html
    assert "Negatived" in html
    assert "https://www.ourcommons.ca/members/en/votes/44/1/54" in html
    assert 'href="/members/tom-reed/"' in html
    # Tom Reed (Lib.) voted yea while the other Liberals voted nay
    against = html.split("Voted differently from most of their party")[1].split("</ul>")[0]
    assert "Tom Reed" in against and "Paul Bell" not in against
    assert "1 name in the list could not be matched" in html  # Zed
    seq = Division.objects.get(number=54).sequence
    assert f"/sittings/44-1/51/?text=en#iv-{seq}" in html


def test_division_page_by_party(client, sitting):
    html = client.get("/votes/44-1/54/").content.decode()
    table = html.split('class="data-table party-votes"')[1].split("</table>")[0]
    assert "<tr><td>Lib.</td><td>1</td><td>4</td><td>1</td></tr>" in table
    assert "<tr><td>CPC</td><td>1</td><td>1</td><td>0</td></tr>" in table


def test_unknown_division_is_404(client, sitting):
    assert client.get("/votes/44-1/999/").status_code == 404


def test_sitting_page_lists_votes(client, sitting):
    html = client.get(sitting.get_absolute_url()).content.decode()
    assert "Recorded votes" in html and 'href="/votes/44-1/55/?text=en"' in html


def test_member_page_shows_votes(client, sitting):
    html = client.get("/members/tom-reed/").content.decode()
    assert "2 recorded votes in the loaded debates: 2 yea, 0 nay, 0 paired." in html
    assert "in 1 of 2 votes" in html
    assert "differs from party" in html
    assert 'href="/votes/?member=tom-reed"' in html
