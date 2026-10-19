"""Committee evidence: the transcripts of public committee meetings.

Each meeting has a page on ourcommons.ca that links to its transcript:

    /DocumentViewer/en/44-1/FINA/meeting-100/evidence
      -> /Content/Committee/441/FINA/Evidence/EV12578528/FINAEV100-E.XML (and -F.XML)

The transcripts use the same XML format as the House Hansard, so they are parsed and
aligned (English with French, paragraph by paragraph) with the House parser. What
differs is who speaks: committee members (with riding and party), the chair (whose
name and riding sit inside the label: "The Chair (Mr. Peter Fonseca (Mississauga
East—Cooksville, Lib.))"), ministers (with their portfolio), witnesses (with their
title and organisation) and the clerk. Witnesses are identified by the House's person
id, so the same person keeps one page across meetings.

Meetings held in camera have no transcript and are skipped.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import requests
from defusedxml import ElementTree as ET
from django.conf import settings
from django.db import transaction

from .hansard_xml import fetch
from .loader import _person_for, word_count
from .models import (
    Committee,
    Meeting,
    MeetingIntervention,
    MeetingParagraph,
    Person,
    Witness,
)
from .parsing import _metadata, merge, parse_document
from .speakers import parse_label

BASE = "https://www.ourcommons.ca"
LINK = re.compile(
    r"(?:https?://www\.ourcommons\.ca)?(/Content/Committee/[^\"'<>\s]+?)-E\.XML", re.IGNORECASE
)
# House affiliation types seen in committee evidence
WITNESS, MINISTER, CHAIR, CLERK = "28", "4", "35", "27"
MEMBER_TYPES = {"1", "2", "40", "47", "9", "18", "20", "22", "23"}
INDIVIDUAL = ("as an individual", "à titre personnel")
HONORIFICS = re.compile(r"^(?:Mr|Mrs|Ms|Miss|Dr|Prof|Hon|M|Mme|L'hon)\.?\s+", re.IGNORECASE)


class MeetingNotFound(Exception):
    """No meeting page at this number (not held yet, or past the last one)."""


class NoEvidence(Exception):
    """The meeting exists but has no published transcript (in camera, or not yet)."""


def raw_path(parliament: int, session: int, acronym: str, number: int, lang: str) -> Path:
    return (
        Path(settings.DATA_DIR)
        / "raw"
        / "committees"
        / f"{parliament}-{session}-{acronym}-{number:03d}-{lang}.xml"
    )


def page_url(parliament: int, session: int, acronym: str, number: int) -> str:
    return f"{BASE}/DocumentViewer/en/{parliament}-{session}/{acronym}/meeting-{number}/evidence"


def get_meeting_xml(
    parliament: int, session: int, acronym: str, number: int, keep: bool = True
) -> tuple[bytes, bytes | None, str]:
    """-> (English XML, French XML or None, source page). Cached in data/raw/committees."""
    en_path = raw_path(parliament, session, acronym, number, "en")
    fr_path = raw_path(parliament, session, acronym, number, "fr")
    source = page_url(parliament, session, acronym, number)
    if en_path.exists():
        return en_path.read_bytes(), fr_path.read_bytes() if fr_path.exists() else None, source
    try:
        html = fetch(source, settings.HANSARD_USER_AGENT).decode("utf-8", "replace")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise MeetingNotFound(source) from exc
        raise
    match = LINK.search(html)
    if not match:
        if f"meeting-{number}" not in html and "Meeting" not in html:
            raise MeetingNotFound(source)
        raise NoEvidence(source)
    stem = BASE + match.group(1)
    en = fetch(stem + "-E.XML", settings.HANSARD_USER_AGENT)
    try:
        fr = fetch(stem + "-F.XML", settings.HANSARD_USER_AGENT)
    except requests.HTTPError:
        fr = None
    if keep:
        en_path.parent.mkdir(parents=True, exist_ok=True)
        en_path.write_bytes(en)
        if fr:
            fr_path.write_bytes(fr)
    return en, fr, source


# -- speakers --------------------------------------------------------------------------


@dataclass
class Speaker:
    role: str
    name: str
    detail_en: str = ""  # riding, portfolio or title and organisation
    detail_fr: str = ""
    party: str = ""
    riding: str = ""
    title_en: str = ""
    title_fr: str = ""
    affiliation_en: str = ""
    affiliation_fr: str = ""
    individual: bool = False


def _inner(label: str) -> str:
    """'The Chair (Mr. Peter Fonseca (Mississauga East, Lib.))' -> 'Mr. Peter Fonseca (...)'"""
    start = label.find("(")
    return label[start + 1 : -1].strip() if start >= 0 and label.endswith(")") else ""


def _plain_name(name: str) -> str:
    return HONORIFICS.sub("", " ".join(name.split()))


def _split_title(text: str) -> tuple[str, str, bool]:
    """'President, Canadian Labour Congress' -> (title, affiliation, as an individual)."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    individual = bool(parts) and parts[-1].lower() in INDIVIDUAL
    if individual:
        parts = parts[:-1]
    if not parts:
        return "", "", individual
    return parts[0], ", ".join(parts[1:]), individual


def read_speaker(type_: str, label_en: str, label_fr: str) -> Speaker:
    if type_ == CHAIR:
        inner = parse_label(_inner(label_en), "2") if _inner(label_en) else None
        return Speaker(
            role=MeetingIntervention.Role.CHAIR,
            name=inner.name if inner else "",
            party=inner.party if inner else "",
            riding=inner.riding if inner else "",
            detail_en=label_en.split("(")[0].strip(),
            detail_fr=label_fr.split("(")[0].strip(),
        )
    if type_ == CLERK:
        return Speaker(
            role=MeetingIntervention.Role.CLERK,
            name=_plain_name(_inner(label_en)),
            detail_en=label_en.split("(")[0].strip(),
            detail_fr=label_fr.split("(")[0].strip(),
        )
    label = parse_label(label_en, type_)
    if type_ == WITNESS:
        title_en, aff_en, individual = _split_title(label.role)
        title_fr, aff_fr, _ = _split_title(_inner(label_fr)) if "(" in label_fr else ("", "", 0)
        return Speaker(
            role=MeetingIntervention.Role.WITNESS,
            name=_plain_name(label.raw.split("(")[0])
            if "(" in label.raw
            else _plain_name(label.raw),
            detail_en=label.role,
            detail_fr=_inner(label_fr),
            title_en=title_en,
            title_fr=title_fr,
            affiliation_en=aff_en,
            affiliation_fr=aff_fr,
            individual=individual,
        )
    if type_ == MINISTER or (label.role and not label.party):
        return Speaker(
            role=MeetingIntervention.Role.MINISTER,
            name=label.name,
            detail_en=label.role,
            detail_fr=_inner(label_fr),
        )
    if type_ in MEMBER_TYPES or label.party:
        return Speaker(
            role=MeetingIntervention.Role.MEMBER,
            name=label.name,
            party=label.party,
            riding=label.riding,
            detail_en=label.riding,
        )
    return Speaker(role=MeetingIntervention.Role.OTHER, name=label.name or label.raw)


# -- storing --------------------------------------------------------------------------


@dataclass
class MeetingResult:
    meeting: Meeting
    interventions: int
    witnesses: int


def _full_labels(merged) -> dict[str, tuple[str, str]]:
    """Speaker id -> the first label of the meeting that carries details in parentheses
    (later labels are short: "The Chair", "Mr. Lawrence")."""
    out: dict[str, tuple[str, str]] = {}
    for iv in merged.interventions:
        if iv.speaker_db_id and "(" in iv.speaker_label_en and iv.speaker_db_id not in out:
            out[iv.speaker_db_id] = (iv.speaker_label_en, iv.speaker_label_fr)
    return out


@transaction.atomic
def store_meeting(en_xml: bytes, fr_xml: bytes | None, source: str) -> MeetingResult:
    en, fr = parse_document(en_xml), parse_document(fr_xml) if fr_xml else None
    meta = _metadata(ET.fromstring(en_xml))
    meta_fr = _metadata(ET.fromstring(fr_xml)) if fr_xml else {}
    merged = merge(en, fr)
    if fr is None:
        merged.issues.append("French version not available")

    acronym = (meta.get("Acronyme") or "").upper() or source.split("/")[-3]
    committee, _ = Committee.objects.get_or_create(acronym=acronym)
    name_en = meta.get("InstitutionDebateEn") or meta.get("InstitutionDebate", "")
    name_fr = meta.get("InstitutionDebateFr") or meta_fr.get("InstitutionDebate", "")
    if (committee.name_en, committee.name_fr) != (name_en, name_fr):
        committee.name_en, committee.name_fr = name_en, name_fr
        committee.save()

    meeting, _ = Meeting.objects.update_or_create(
        committee=committee,
        parliament=merged.parliament,
        session=merged.session,
        number=merged.number,
        defaults={
            "date": merged.date,
            "house_doc_id": merged.house_doc_id,
            "chair": _plain_name(meta.get("SpeakerName", "")),
            "source_url": source,
            "checksum_en": hashlib.sha256(en_xml).hexdigest(),
            "checksum_fr": hashlib.sha256(fr_xml).hexdigest() if fr_xml else "",
            "issues": merged.issues,
        },
    )
    meeting.interventions.all().delete()

    full = _full_labels(merged)
    speakers: dict[str, Speaker] = {}
    witnesses: dict[str, Witness] = {}
    people: dict[str, Person | None] = {}
    rows = []
    for seq, iv in enumerate(merged.interventions, start=1):
        if iv.speaker_db_id:
            if iv.speaker_db_id not in speakers:
                label_en, label_fr = full.get(
                    iv.speaker_db_id, (iv.speaker_label_en, iv.speaker_label_fr)
                )
                speakers[iv.speaker_db_id] = read_speaker(iv.speaker_type, label_en, label_fr)
            sp = speakers[iv.speaker_db_id]
        elif iv.speaker_label_en:
            sp = read_speaker(iv.speaker_type, iv.speaker_label_en, iv.speaker_label_fr)
        else:
            sp = Speaker(role=MeetingIntervention.Role.OTHER, name="")

        person = witness = None
        party = sp.party
        if sp.role == MeetingIntervention.Role.WITNESS and iv.speaker_db_id:
            if iv.speaker_db_id not in witnesses:
                witnesses[iv.speaker_db_id] = _witness(iv.speaker_db_id, sp, merged.date)
            witness = witnesses[iv.speaker_db_id]
        elif (
            sp.role
            in (
                MeetingIntervention.Role.MEMBER,
                MeetingIntervention.Role.CHAIR,
                MeetingIntervention.Role.MINISTER,
            )
            and sp.name
        ):
            if sp.name not in people:
                people[sp.name] = (
                    _person_for(sp.name, sp.party, sp.riding, merged.date)
                    if sp.role != MeetingIntervention.Role.MINISTER
                    else Person.objects.filter(name=sp.name).first()
                )
            person = people[sp.name]
            if person and not party:
                party = person.latest_party

        speech = [p for p in iv.paragraphs if p.kind == "speech"]
        obj = MeetingIntervention(
            meeting=meeting,
            sequence=seq,
            house_id=iv.house_id,
            role=sp.role,
            person=person,
            witness=witness,
            name=sp.name[:200],
            detail_en=sp.detail_en[:400],
            detail_fr=sp.detail_fr[:400],
            party=party[:20],
            time=iv.time,
            words_en=sum(word_count(p.text_en) for p in speech),
        )
        rows.append((obj, iv.paragraphs))

    MeetingIntervention.objects.bulk_create([obj for obj, _ in rows], batch_size=500)
    MeetingParagraph.objects.bulk_create(
        [
            MeetingParagraph(
                intervention=obj,
                sequence=i,
                kind=p.kind,
                floor_language=p.floor_language,
                text_en=p.text_en,
                text_fr=p.text_fr,
            )
            for obj, paras in rows
            for i, p in enumerate(paras, start=1)
        ],
        batch_size=1000,
    )
    return MeetingResult(meeting=meeting, interventions=len(rows), witnesses=len(witnesses))


def _witness(db_id: str, sp: Speaker, date) -> Witness:
    witness = Witness.objects.filter(house_db_id=db_id).first()
    if witness is None:
        witness = Witness(house_db_id=db_id, name=sp.name[:200] or "Witness")
    if witness.latest_date is None or date >= witness.latest_date:
        witness.name = sp.name[:200] or witness.name
        witness.title_en, witness.title_fr = sp.title_en[:300], sp.title_fr[:300]
        witness.affiliation_en = sp.affiliation_en[:400]
        witness.affiliation_fr = sp.affiliation_fr[:400]
        witness.as_individual = sp.individual
        witness.latest_date = date
        witness.save()
    return witness


def load_meeting(
    parliament: int, session: int, acronym: str, number: int, keep: bool = True
) -> MeetingResult:
    en, fr, source = get_meeting_xml(parliament, session, acronym, number, keep)
    return store_meeting(en, fr, source)
