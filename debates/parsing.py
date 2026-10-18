"""Turn one Hansard XML document (English or French) into plain Python objects,
then merge the two language versions of a sitting.

Structure confirmed on real sittings (44-1 #1, 44-1 #50, 45-1 #10):

    Hansard
      ExtractedInformation/ExtractedItem[@Name]   metadata (date, numbers, Speaker)
      HansardBody
        Intro/ParaText
        OrderOfBusiness[@Rubric]/OrderOfBusinessTitle
          SubjectOfBusiness/SubjectOfBusinessTitle
            SubjectOfBusinessContent
              Intervention[@Type,@id]/PersonSpeaking/Affiliation[@DbId,@Type]
                                     /Content/(ParaText|ProceduralText|FloorLanguage|Timestamp)
              ParaText | ProceduralText              loose procedural text
              Division[@DivisionNumber]/DivisionType[@vote-type]/Affiliation[@DbId]
                                                     recorded vote (names as printed)

FloorLanguage and Timestamp are switches: they apply to everything after them in
document order until the next one, across interventions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field

from defusedxml import ElementTree as ET

from .speakers import SpeakerLabel, parse_label

FLOOR_LANGUAGES = {"EN": "en", "FR": "fr", "TEXT": "text"}
PROCEDURAL = "Procedural"


def clean_text(el) -> str:
    return " ".join("".join(el.itertext()).split())


@dataclass
class Paragraph:
    house_id: str
    kind: str  # "speech" or "procedural"
    floor_language: str  # "en", "fr", "text" or ""
    text: str


@dataclass
class Intervention:
    house_id: str  # "" for loose procedural blocks
    kind: str  # Debate, Interjection, Question, Answer, Procedural
    rubric: str
    order_title: str
    subject_title: str
    time: dt.time | None
    speaker_db_id: str = ""
    speaker_type: str = ""
    speaker_raw: str = ""
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Division:
    """One recorded vote ("division") as printed in Hansard."""

    number: int
    house_id: str
    rubric: str
    order_title: str
    subject_title: str
    qualifier: str  # e.g. "Opposition Motion—Carbon Tax on Farmers"
    time: dt.time | None
    position: int  # index of the intervention holding "(The House divided on ...)"
    heading: str  # that sentence, e.g. "(The House divided on Motion No. 3, which was ...)"
    votes: dict[str, list[tuple[str, str]]]  # yea/nay/paired -> [(House id, name)]
    after: str = ""  # text of the next intervention ("Motion negatived. I declare ...")


VOTE_TYPES = {"yeas": "yea", "nays": "nay", "paired": "paired"}


@dataclass
class Document:
    lang: str
    house_doc_id: str
    parliament: int
    session: int
    number: int
    date: dt.date
    volume: str
    speaker_of_house: str  # e.g. "Anthony Rota", from the masthead
    checksum: str
    interventions: list[Intervention]
    divisions: list[Division] = field(default_factory=list)


def _metadata(root) -> dict[str, str]:
    info = root.find("ExtractedInformation")
    if info is None:
        return {}
    return {item.get("Name"): clean_text(item) for item in info.findall("ExtractedItem")}


def _speaker_of_house(meta: dict[str, str]) -> str:
    # EN: "Speaker: The Honourable Anthony Rota"; FR: "Présidence de l'honorable Anthony Rota"
    raw = meta.get("SpeakerName", "")
    for marker in ("The Honourable ", "l'honorable ", "l’honorable "):
        if marker in raw:
            return raw.split(marker, 1)[1].strip()
    return ""


class _Walker:
    """Walks HansardBody in document order, carrying the running state."""

    def __init__(self):
        self.rubric = ""
        self.order_title = ""
        self.subject_title = ""
        self.last_subject = ""  # latest non-empty subject in this order of business
        self.last_qualifier = ""  # and its qualifier ("Opposition Motion—...")
        self.time: dt.time | None = None
        self.floor = ""
        self.interventions: list[Intervention] = []
        self.divisions: list[Division] = []
        self._awaiting: Division | None = None  # division whose outcome comes next
        self._loose: Intervention | None = None  # open block of loose procedural text

    # -- state switches -------------------------------------------------------
    def _floor_language(self, el):
        self.floor = FLOOR_LANGUAGES.get((el.get("language") or "").upper(), "")

    def _timestamp(self, el):
        try:
            self.time = dt.time(int(el.get("Hr")), int(el.get("Mn")))
        except (TypeError, ValueError):
            pass

    # -- containers -------------------------------------------------------------
    def walk(self, el):
        tag = el.tag
        if tag == "OrderOfBusiness":
            self._close_loose()
            self.rubric = el.get("Rubric") or ""
            title = el.find("OrderOfBusinessTitle")
            self.order_title = clean_text(title) if title is not None else ""
            self.subject_title = self.last_subject = self.last_qualifier = ""
            self._children(el)
        elif tag == "SubjectOfBusiness":
            self._close_loose()
            title = el.find("SubjectOfBusinessTitle")
            self.subject_title = clean_text(title) if title is not None else ""
            qualifier = el.find("SubjectOfBusinessQualifier")
            qualifier = clean_text(qualifier) if qualifier is not None else ""
            if self.subject_title:
                self.last_subject, self.last_qualifier = self.subject_title, qualifier
            elif qualifier:  # e.g. each estimates vote: "Concurrence in Vote 5b—..."
                self.last_qualifier = qualifier
            self._children(el)
        elif tag in ("HansardBody", "SubjectOfBusinessContent", "Intro"):
            self._children(el)
        elif tag == "Intervention":
            self._close_loose()
            self._intervention(el)
        elif tag in ("ParaText", "ProceduralText"):
            self._loose_paragraph(el)
        elif tag == "FloorLanguage":
            self._floor_language(el)
        elif tag == "Timestamp":
            self._timestamp(el)
        elif tag == "Division":
            self._division(el)
        # Titles and catchlines are not speech: skipped.

    def _division(self, el):
        try:
            number = int(el.get("DivisionNumber") or "")
        except ValueError:
            return
        # The sentence announcing the vote is the last loose paragraph before it.
        if self._loose is not None and self._loose.paragraphs:
            position, heading = len(self.interventions), self._loose.paragraphs[-1].text
        else:
            position, heading = len(self.interventions) - 1, ""
        votes: dict[str, list[tuple[str, str]]] = {"yea": [], "nay": [], "paired": []}
        for group in el.findall("DivisionType"):
            choice = VOTE_TYPES.get((group.get("vote-type") or "").lower())
            if choice:
                votes[choice] += [
                    (a.get("DbId") or "", clean_text(a)) for a in group.findall("Affiliation")
                ]
        self.divisions.append(
            Division(
                number=number,
                house_id=el.get("id") or "",
                rubric=self.rubric,
                order_title=self.order_title,
                # A vote often sits in an untitled continuation of the debate's subject.
                subject_title=self.subject_title or self.last_subject,
                qualifier=self.last_qualifier,
                time=self.time,
                position=max(position, 0),
                heading=heading,
                votes=votes,
            )
        )
        # A qualifier names one question; later votes in the same subject (bill
        # stages after estimates, say) must not inherit it.
        self.last_qualifier = ""
        self._awaiting = self.divisions[-1]

    def _children(self, el):
        for child in el:
            self.walk(child)

    def _new(self, house_id: str, kind: str) -> Intervention:
        return Intervention(
            house_id=house_id,
            kind=kind,
            rubric=self.rubric,
            order_title=self.order_title,
            subject_title=self.subject_title,
            time=self.time,
        )

    def _intervention(self, el):
        iv = self._new(el.get("id") or "", el.get("Type") or "")
        person = el.find("PersonSpeaking/Affiliation")
        if person is not None:
            iv.speaker_db_id = person.get("DbId") or ""
            iv.speaker_type = person.get("Type") or ""
            iv.speaker_raw = clean_text(person)
        content = el.find("Content")
        for child in content if content is not None else []:
            if child.tag == "ParaText":
                self._add(iv, child, "speech")
            elif child.tag == "ProceduralText":
                self._add(iv, child, "procedural")
            elif child.tag == "FloorLanguage":
                self._floor_language(child)
            elif child.tag == "Timestamp":
                self._timestamp(child)
        self.interventions.append(iv)
        if self._awaiting is not None:
            self._awaiting.after = " ".join(p.text for p in iv.paragraphs)[:500]
            self._awaiting = None

    def _add(self, iv: Intervention, el, kind: str):
        text = clean_text(el)
        if text:
            iv.paragraphs.append(
                Paragraph(
                    house_id=el.get("id") or "", kind=kind, floor_language=self.floor, text=text
                )
            )

    def _loose_paragraph(self, el):
        if self._loose is None:
            self._loose = self._new("", PROCEDURAL)
        self._add(self._loose, el, "procedural")

    def _close_loose(self):
        if self._loose is not None and self._loose.paragraphs:
            self.interventions.append(self._loose)
        self._loose = None

    def finish(self) -> list[Intervention]:
        self._close_loose()
        return self.interventions


def parse_document(xml_bytes: bytes) -> Document:
    root = ET.fromstring(xml_bytes)
    if root.tag != "Hansard":
        raise ValueError(f"Not a Hansard document (root element {root.tag!r})")
    meta = _metadata(root)
    try:
        date = dt.date(
            int(meta["MetaDateNumYear"]), int(meta["MetaDateNumMonth"]), int(meta["MetaDateNumDay"])
        )
        parliament = int(meta["ParliamentNumber"])
        session = int(meta["SessionNumber"])
        number = int(meta["MetaNumberNumber"])
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Missing or invalid sitting metadata: {exc}") from exc

    lang_attr = next((v for k, v in root.attrib.items() if k.endswith("lang")), "")
    walker = _Walker()
    body = root.find("HansardBody")
    if body is not None:
        walker.walk(body)

    return Document(
        lang=lang_attr.lower(),
        house_doc_id=root.get("id") or "",
        parliament=parliament,
        session=session,
        number=number,
        date=date,
        volume=meta.get("MetaVolumeNumber", ""),
        speaker_of_house=_speaker_of_house(meta),
        checksum=hashlib.sha256(xml_bytes).hexdigest(),
        interventions=walker.finish(),
        divisions=walker.divisions,
    )


# What was put to the vote and the outcome, from the sentence before the vote list:
#   (The House divided on Motion No. 3, which was agreed to on the following division:)
#   (La motion no 3, mise aux voix, est adoptée par le vote suivant :)
#   Some sittings (2020) state no outcome there: "(The House divided on the motion:)"
#   and "(La motion est mise aux voix.)"; the Speaker announces it just after.
HEADING_EN = re.compile(
    r"divided on (?P<object>.+?)(?:,\s+which was (?P<result>agreed to|negatived|carried|"
    r"defeated)|\s*:)",
    re.IGNORECASE,
)
HEADING_FR = re.compile(
    r"^\(?(?P<object>.+?),\s+mise?s? aux voix,\s+(?:est|sont)\s+(?P<result>adopt|rejet)"
    r"|^\(?(?P<object2>.+?)\s+(?:est|sont)\s+mise?s? aux voix",
    re.IGNORECASE,
)
# The Speaker's announcement after the vote: "Motion negatived. I declare the motion
# defeated." / "Je déclare la motion adoptée."
OUTCOME = re.compile(
    r"(?P<agreed>(?:motion|amendment|bill)s? agreed to|declare the (?:motion|amendment)s? "
    r"carried|motion adoptée|déclare la motion adoptée)|(?P<negatived>(?:motion|amendment)s? "
    r"negatived|declare the (?:motion|amendment)s? (?:defeated|lost)|déclare la motion rejetée)",
    re.IGNORECASE,
)


def read_heading(text: str, lang: str) -> tuple[str, str]:
    """-> (object, result) with result "agreed", "negatived" or "" when not stated."""
    match = (HEADING_EN if lang == "en" else HEADING_FR).search(text or "")
    if not match:
        return "", ""
    groups = match.groupdict()
    obj = (groups.get("object") or groups.get("object2") or "").strip()
    obj = obj[:1].upper() + obj[1:]
    word = (groups.get("result") or "").lower()
    if not word:
        return obj, ""
    return obj, "agreed" if word in ("agreed to", "carried", "adopt") else "negatived"


def read_outcome(text: str) -> str:
    """Outcome announced after a vote, or "" when the text does not state one."""
    match = OUTCOME.search(text or "")
    if not match:
        return ""
    return "agreed" if match.group("agreed") else "negatived"


# ---------------------------------------------------------------------------------
# Merging English and French
# ---------------------------------------------------------------------------------


@dataclass
class MergedParagraph:
    house_id: str
    kind: str
    floor_language: str
    text_en: str
    text_fr: str


@dataclass
class MergedIntervention:
    house_id: str
    kind: str
    rubric: str
    order_title_en: str
    order_title_fr: str
    subject_title_en: str
    subject_title_fr: str
    time: dt.time | None
    speaker_db_id: str
    speaker_type: str
    speaker_label_en: str
    speaker_label_fr: str
    speaker: SpeakerLabel | None
    paragraphs: list[MergedParagraph]


@dataclass
class MergedDivision:
    number: int
    house_id: str
    rubric: str
    order_title_en: str
    order_title_fr: str
    subject_title_en: str
    subject_title_fr: str
    qualifier_en: str
    qualifier_fr: str
    object_en: str
    object_fr: str
    result: str  # "agreed", "negatived" or "" (not stated)
    time: dt.time | None
    position: int  # index into MergedSitting.interventions
    votes: dict[str, list[tuple[str, str]]]


@dataclass
class MergedSitting:
    parliament: int
    session: int
    number: int
    date: dt.date
    volume: str
    house_doc_id: str
    speaker_of_house: str
    checksum_en: str
    checksum_fr: str
    has_french: bool
    interventions: list[MergedIntervention]
    issues: list[str]
    divisions: list[MergedDivision] = field(default_factory=list)


def _merge_paragraphs(en: Intervention, fr: Intervention | None, issues: list[str]):
    fr_paras = fr.paragraphs if fr else []
    aligned = len(fr_paras) == len(en.paragraphs) and all(
        a.house_id == b.house_id for a, b in zip(en.paragraphs, fr_paras, strict=True)
    )
    if fr is not None and not aligned:
        issues.append(
            f"intervention {en.house_id or '(procedural)'}: paragraphs differ "
            f"(en={len(en.paragraphs)}, fr={len(fr_paras)})"
        )
    by_id = {p.house_id: p for p in fr_paras if p.house_id}
    merged = []
    for i, p in enumerate(en.paragraphs):
        if aligned:
            other = fr_paras[i]
        else:
            other = by_id.get(p.house_id) if p.house_id else None
        merged.append(
            MergedParagraph(
                house_id=p.house_id,
                kind=p.kind,
                floor_language=p.floor_language,
                text_en=p.text,
                text_fr=other.text if other else "",
            )
        )
    return merged


def merge(en: Document, fr: Document | None) -> MergedSitting:
    """Combine the two language versions. English drives the structure; French text is
    attached by position when the House ids line up (the normal case) and by id if not.

    The intervention Type is taken from English: on real sittings the French file
    sometimes types the same intervention differently (Question vs Debate)."""
    issues: list[str] = []
    fr_ivs = fr.interventions if fr else []
    if fr is not None:
        if (en.parliament, en.session, en.number, en.date) != (
            fr.parliament,
            fr.session,
            fr.number,
            fr.date,
        ):
            raise ValueError("English and French documents describe different sittings")
    positional = len(fr_ivs) == len(en.interventions) and all(
        a.house_id == b.house_id for a, b in zip(en.interventions, fr_ivs, strict=True)
    )
    if fr is not None and not positional:
        issues.append(
            f"interventions differ between languages (en={len(en.interventions)}, fr={len(fr_ivs)})"
        )
    fr_by_id = {iv.house_id: iv for iv in fr_ivs if iv.house_id}

    # Within one sitting a speaker id keeps the same person: carry party/riding/role
    # from the full first label over to later short labels.
    full_labels: dict[str, SpeakerLabel] = {}
    for iv in en.interventions:
        if iv.speaker_db_id:
            label = parse_label(iv.speaker_raw, iv.speaker_type)
            if label.is_full and iv.speaker_db_id not in full_labels:
                full_labels[iv.speaker_db_id] = label

    merged = []
    for i, iv in enumerate(en.interventions):
        other = fr_ivs[i] if positional else fr_by_id.get(iv.house_id) if iv.house_id else None
        speaker = None
        if iv.speaker_raw:
            speaker = parse_label(iv.speaker_raw, iv.speaker_type)
            full = full_labels.get(iv.speaker_db_id)
            if full and not speaker.is_full and not speaker.is_chair:
                speaker = SpeakerLabel(
                    raw=speaker.raw,
                    name=speaker.name or full.name,
                    role=full.role,
                    riding=full.riding,
                    party=full.party,
                )
            if speaker.is_chair and not speaker.name and speaker.role == "The Speaker":
                speaker = SpeakerLabel(
                    raw=speaker.raw, name=en.speaker_of_house, role=speaker.role, is_chair=True
                )
        merged.append(
            MergedIntervention(
                house_id=iv.house_id,
                kind=iv.kind,
                rubric=iv.rubric,
                order_title_en=iv.order_title,
                order_title_fr=other.order_title if other else "",
                subject_title_en=iv.subject_title,
                subject_title_fr=other.subject_title if other else "",
                time=iv.time,
                speaker_db_id=iv.speaker_db_id,
                speaker_type=iv.speaker_type,
                speaker_label_en=iv.speaker_raw,
                speaker_label_fr=other.speaker_raw if other else "",
                speaker=speaker,
                paragraphs=_merge_paragraphs(iv, other, issues),
            )
        )

    return MergedSitting(
        parliament=en.parliament,
        session=en.session,
        number=en.number,
        date=en.date,
        volume=en.volume,
        house_doc_id=en.house_doc_id,
        speaker_of_house=en.speaker_of_house,
        checksum_en=en.checksum,
        checksum_fr=fr.checksum if fr else "",
        has_french=fr is not None,
        interventions=merged,
        issues=issues,
        divisions=_merge_divisions(en, fr),
    )


def _merge_divisions(en: Document, fr: Document | None) -> list[MergedDivision]:
    """Vote lists and structure come from English; French adds titles and the object."""
    fr_by_number = {d.number: d for d in fr.divisions} if fr else {}
    out = []
    for d in en.divisions:
        other = fr_by_number.get(d.number)
        object_en, result = read_heading(d.heading, "en")
        object_fr, result_fr = read_heading(other.heading, "fr") if other else ("", "")
        yeas, nays = len(d.votes["yea"]), len(d.votes["nay"])
        if not result:
            # stated in French, announced after the vote (a tie decided by the Speaker's
            # casting vote, say), or else from the counts
            result = (
                result_fr
                or read_outcome(d.after)
                or ("agreed" if yeas > nays else "negatived" if nays > yeas else "")
            )
        out.append(
            MergedDivision(
                number=d.number,
                house_id=d.house_id,
                rubric=d.rubric,
                order_title_en=d.order_title,
                order_title_fr=other.order_title if other else "",
                subject_title_en=d.subject_title,
                subject_title_fr=other.subject_title if other else "",
                qualifier_en=d.qualifier,
                qualifier_fr=other.qualifier if other else "",
                object_en=object_en,
                object_fr=object_fr,
                result=result,
                time=d.time,
                position=d.position,
                votes=d.votes,
            )
        )
    return out
