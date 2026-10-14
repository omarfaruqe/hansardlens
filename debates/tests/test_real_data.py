"""Checks against real Hansard files, when present in data/raw (they are never committed).
Skipped in CI. Run `python manage.py inspect_sitting --parliament 44 --session 1 --sitting 50`
first to download them."""

from pathlib import Path

import pytest
from django.conf import settings

from debates.parsing import merge, parse_document

CASES = [("P44S1-050", 332), ("P45S1-010", 232)]


@pytest.mark.parametrize("stem, expected_interventions", CASES)
def test_real_sitting_parses_and_aligns(stem, expected_interventions):
    raw = Path(settings.DATA_DIR) / "raw"
    en_path, fr_path = raw / f"{stem}-en.xml", raw / f"{stem}-fr.xml"
    if not (en_path.exists() and fr_path.exists()):
        pytest.skip(f"{stem} not downloaded")
    m = merge(parse_document(en_path.read_bytes()), parse_document(fr_path.read_bytes()))
    assert m.issues == []
    assert len(m.interventions) == expected_interventions
    paragraphs = [p for iv in m.interventions for p in iv.paragraphs]
    assert all(p.text_fr for p in paragraphs)
    members = [iv for iv in m.interventions if iv.speaker and not iv.speaker.is_chair]
    assert all(iv.speaker.party for iv in members)
