import pytest

pytestmark = pytest.mark.django_db


def test_bill_list(client, bill):
    html = client.get("/bills/").content.decode()
    assert "1 bill" in html and 'href="/bills/45-1/C-37/?text=en"' in html
    assert "Clean Water Act" in html
    assert "1 bill" in client.get("/bills/", {"q": "c-37"}).content.decode()
    assert "1 bill" in client.get("/bills/", {"q": "eau"}).content.decode()  # French title
    assert "0 bills" in client.get("/bills/", {"session": "44-1"}).content.decode()


def test_bill_page(client, bill):
    html = client.get("/bills/45-1/C-37/").content.decode()
    assert "<h1" in html and "Clean Water Act" in html and "An Act respecting water" in html
    assert "https://www.parl.ca/legisinfo/en/bill/45-1/c-37" in html
    assert "Second reading" in html and "agreed to" in html
    assert "/sittings/45-1/10/#iv-1" in html  # stage links to the debate
    assert 'href="/votes/45-1/7/?text=en"' in html
    assert 'href="/members/ana-test/"' in html
    assert "%22Bill+C-37%22" in html


def test_bill_code_case_redirects(client, bill):
    response = client.get("/bills/45-1/c-37/")
    assert response.status_code == 301 and response["Location"] == "/bills/45-1/C-37/"
    assert client.get("/bills/45-1/C-38/").status_code == 404


def test_speech_and_vote_link_to_bill(client, bill):
    assert 'href="/bills/45-1/C-37/?text=en"' in client.get("/speeches/777/").content.decode()
    html = client.get("/votes/45-1/7/").content.decode()
    assert 'href="/bills/45-1/C-37/?text=en"' in html and "Second reading" in html
