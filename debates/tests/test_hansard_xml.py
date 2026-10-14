from pathlib import Path

import pytest
from defusedxml import EntitiesForbidden

from debates.hansard_xml import local_name, sitting_url, summarize

FIXTURE = Path(__file__).parent / "fixtures" / "mini_hansard.xml"


def test_sitting_url_english():
    assert sitting_url(44, 1, 1, "en") == (
        "https://www.ourcommons.ca/Content/House/441/Debates/001/HAN001-E.XML"
    )


def test_sitting_url_french_and_padding():
    assert sitting_url(44, 1, 123, "fr").endswith("/441/Debates/123/HAN123-F.XML")


def test_sitting_url_rejects_unknown_language():
    with pytest.raises(ValueError):
        sitting_url(44, 1, 1, "de")


def test_local_name_strips_namespace():
    assert local_name("{http://example.org/ns}Speaker") == "Speaker"
    assert local_name("Speaker") == "Speaker"


def test_summarize_counts_paths_attributes_and_text():
    summary = summarize(FIXTURE.read_bytes())

    assert summary.root_tag == "Hansard"
    assert summary.root_attrib == {"Parliament": "44", "Session": "1"}
    assert summary.element_count == 9
    assert summary.path_counts["/Hansard/Sitting/Intervention"] == 2
    assert summary.path_counts["/Hansard/Sitting/Intervention/Text"] == 3
    assert summary.attributes["Intervention"]["Type"] == 2
    assert summary.attribute_samples["Intervention@Type"] == ["Statement", "Question"]
    assert summary.text_samples["/Hansard/Sitting/Intervention/Speaker"] == [
        "Member One",
        "Member Two",
    ]
    # document order is preserved
    assert list(summary.path_counts)[0] == "/Hansard"


def test_summarize_rejects_malicious_entities():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    with pytest.raises(EntitiesForbidden):
        summarize(bomb)


def test_render_mentions_key_sections():
    text = summarize(FIXTURE.read_bytes()).render()
    assert "Element paths" in text
    assert "Intervention@Type" in text
