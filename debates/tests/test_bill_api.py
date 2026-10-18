import pytest

pytestmark = pytest.mark.django_db


def test_bills_api(client, bill):
    data = client.get("/api/v1/bills/", {"q": "C-37"}).json()
    assert data["count"] == 1 and data["results"][0]["long_title_fr"] == "Loi concernant l'eau"
    one = client.get("/api/v1/bills/45-1/c-37/").json()
    assert one["legisinfo_url"] == "https://www.parl.ca/legisinfo/en/bill/45-1/c-37"
    assert [e["stage"] for e in one["timeline"]] == ["second", "second"]
    assert one["divisions"][0]["number"] == 7 and one["divisions"][0]["stage"] == "second"
    assert client.get("/api/v1/bills/45-1/C-38/").status_code == 404


def test_bill_page_in_french(client, bill):
    html = client.get("/bills/45-1/C-37/", {"lang": "fr"}).content.decode()
    assert "Loi concernant l&#x27;eau" in html or "Loi concernant l'eau" in html
    assert "FR Clean Water Act" in html and "Deuxième lecture" in html
    assert "https://www.parl.ca/legisinfo/fr/bill/45-1/c-37" in html
    assert (
        "Débat sur le projet de loi C-37"
        in client.get("/speeches/777/", {"lang": "fr"}).content.decode()
    )
