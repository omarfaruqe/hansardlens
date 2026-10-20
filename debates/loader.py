"""Download (with a local cache), parse, merge and store Hansard sittings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import requests
from django.conf import settings
from django.db import transaction

from .hansard_xml import fetch, sitting_url
from .models import Intervention, Paragraph, Person, Sitting
from .parsing import MergedSitting, merge, parse_document

WORD_RE = re.compile(r"\w+(?:['’-]\w+)*", re.UNICODE)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


class SittingNotFound(Exception):
    """The House has no document at this address (sitting not held or not yet published)."""


def raw_path(parliament: int, session: int, number: int, lang: str) -> Path:
    return Path(settings.DATA_DIR) / "raw" / f"P{parliament}S{session}-{number:03d}-{lang}.xml"


def get_xml(
    parliament: int, session: int, number: int, lang: str, refresh: bool = False, keep: bool = True
) -> bytes:
    """Return the XML for one language, from the cache in data/raw or the House website.
    `keep=False` does not save a download in the cache (to spare disk space)."""
    path = raw_path(parliament, session, number, lang)
    if path.exists() and not refresh:
        return path.read_bytes()
    url = sitting_url(parliament, session, number, lang)
    try:
        content = fetch(url, settings.HANSARD_USER_AGENT)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise SittingNotFound(url) from exc
        raise
    if not content.lstrip().startswith(b"<?xml") and b"<Hansard" not in content[:2000]:
        raise SittingNotFound(url)  # an HTML page instead of XML
    if keep:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return content


@dataclass
class LoadResult:
    sitting: Sitting
    interventions: int
    paragraphs: int
    created: bool


def _person_for(name: str, party: str, riding: str, date) -> Person | None:
    if not name:
        return None
    person, _ = Person.objects.get_or_create(name=name)
    if person.latest_seen is None or date >= person.latest_seen:
        changed = False
        if party and party != person.latest_party:
            person.latest_party, changed = party, True
        if riding and riding != person.latest_riding:
            person.latest_riding, changed = riding, True
        if person.latest_seen != date:
            person.latest_seen, changed = date, True
        if changed:
            person.save()
    return person


@transaction.atomic
def store(merged: MergedSitting) -> LoadResult:
    """Insert or fully replace one sitting. Re-running is safe (idempotent)."""
    sitting, created = Sitting.objects.update_or_create(
        parliament=merged.parliament,
        session=merged.session,
        number=merged.number,
        defaults={
            "date": merged.date,
            "volume": merged.volume,
            "house_doc_id": merged.house_doc_id,
            "speaker_of_house": merged.speaker_of_house,
            "has_french": merged.has_french,
            "checksum_en": merged.checksum_en,
            "checksum_fr": merged.checksum_fr,
            "issues": merged.issues,
        },
    )
    sitting.interventions.all().delete()

    people: dict[str, Person | None] = {}
    rows: list[tuple[Intervention, list]] = []
    for seq, iv in enumerate(merged.interventions, start=1):
        sp = iv.speaker
        party = sp.party if sp else ""
        riding = sp.riding if sp else ""
        person = None
        if sp and sp.name:
            if sp.name not in people:
                # Chairs carry no party: never let a chair label overwrite a member's party.
                people[sp.name] = _person_for(
                    sp.name,
                    "" if sp.is_chair else party,
                    "" if sp.is_chair else riding,
                    merged.date,
                )
            person = people[sp.name]
            if not sp.is_chair and not party and person:
                party, riding = person.latest_party, riding or person.latest_riding

        speech = [p for p in iv.paragraphs if p.kind == "speech"]
        obj = Intervention(
            sitting=sitting,
            sequence=seq,
            house_id=iv.house_id,
            kind=(iv.kind or Intervention.Kind.OTHER)[:20],
            house_type=(iv.kind or "")[:20],
            rubric=iv.rubric,
            order_title_en=iv.order_title_en[:300],
            order_title_fr=iv.order_title_fr[:300],
            subject_title_en=iv.subject_title_en[:500],
            subject_title_fr=iv.subject_title_fr[:500],
            time=iv.time,
            person=person,
            speaker_db_id=iv.speaker_db_id,
            speaker_type=iv.speaker_type,
            speaker_label_en=iv.speaker_label_en[:400],
            speaker_label_fr=iv.speaker_label_fr[:400],
            speaker_role=(sp.role if sp else "")[:300],
            is_chair=bool(sp and sp.is_chair),
            party=party,
            riding=riding[:160],
            text_en="\n\n".join(p.text_en for p in iv.paragraphs),
            text_fr="\n\n".join(p.text_fr for p in iv.paragraphs),
            word_count_en=sum(word_count(p.text_en) for p in speech),
            word_count_fr=sum(word_count(p.text_fr) for p in speech),
            floor_words_en=sum(word_count(p.text_en) for p in speech if p.floor_language == "en"),
            floor_words_fr=sum(word_count(p.text_fr) for p in speech if p.floor_language == "fr"),
        )
        rows.append((obj, iv.paragraphs))

    Intervention.objects.bulk_create([obj for obj, _ in rows], batch_size=500)
    paragraphs = [
        Paragraph(
            intervention=obj,
            sequence=pseq,
            house_id=p.house_id,
            kind=p.kind,
            floor_language=p.floor_language,
            text_en=p.text_en,
            text_fr=p.text_fr,
        )
        for obj, paras in rows
        for pseq, p in enumerate(paras, start=1)
    ]
    Paragraph.objects.bulk_create(paragraphs, batch_size=1000)
    from .votes import store_divisions

    store_divisions(sitting, merged)
    from . import kinds

    kinds.apply(Intervention, [sitting.id])
    return LoadResult(
        sitting=sitting, interventions=len(rows), paragraphs=len(paragraphs), created=created
    )


def backfill_missing_parties() -> int:
    """Members who only appear with a short label in a sitting get the party shown for
    them in the nearest sitting where their full label appears."""
    fixed = 0
    missing = Intervention.objects.filter(
        party="", is_chair=False, person__isnull=False
    ).select_related("sitting")
    for iv in missing:
        known = (
            Intervention.objects.filter(person_id=iv.person_id)
            .exclude(party="")
            .select_related("sitting")
        )
        nearest = min(
            known, key=lambda k: abs((k.sitting.date - iv.sitting.date).days), default=None
        )
        if nearest:
            iv.party, iv.riding = nearest.party, iv.riding or nearest.riding
            iv.save(update_fields=["party", "riding"])
            fixed += 1
    return fixed


def load_sitting(
    parliament: int, session: int, number: int, refresh: bool = False, keep: bool = True
) -> LoadResult:
    """Fetch EN (required) and FR (optional), merge and store one sitting. `keep=False`
    does not save downloads in data/raw."""
    en_doc = parse_document(get_xml(parliament, session, number, "en", refresh, keep))
    try:
        fr_doc = parse_document(get_xml(parliament, session, number, "fr", refresh, keep))
    except SittingNotFound:
        fr_doc = None
    merged = merge(en_doc, fr_doc)
    if fr_doc is None:
        merged.issues.append("French version not available")
    return store(merged)
