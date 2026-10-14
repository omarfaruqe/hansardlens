"""Parse Hansard speaker labels such as:

"Mr. Marc Dalton (Pitt Meadows—Maple Ridge, CPC)"          member with riding
"Hon. Ahmed Hussen (Minister of Housing ..., Lib.)"          member with a role
"Hon. Adam van Koeverden (Secretary of State (Sport), Lib.)" nested parentheses
"The Assistant Deputy Speaker (Mrs. Carol Hughes)"           chair occupant
"The Deputy Speaker"                                          chair, no name
"Garnett Genuis"                                              short form, later speeches
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Order matters: longer prefixes first.
HONORIFICS = (
    "Right Hon.",
    "Le très hon.",
    "Hon.",
    "L'hon.",
    "L’hon.",
    "Mr.",
    "Mrs.",
    "Ms.",
    "Miss",
    "Dr.",
    "M.",
    "Mme",
    "Mlle",
)

# Party abbreviations as printed in English Hansard. Unknown short tokens are still
# accepted by PARTY_PATTERN so a new party does not break parsing.
KNOWN_PARTIES = {"Lib.", "CPC", "NDP", "BQ", "GP", "Ind.", "PPC"}
# French abbreviations occasionally appear in English labels.
PARTY_ALIASES = {"PCC": "CPC", "NPD": "NDP", "PV": "GP"}
PARTY_PATTERN = re.compile(r"^[A-Z][A-Za-z.]{0,5}$")

# House "Type" codes on <Affiliation> that denote an ordinary member sitting for a riding.
MEMBER_TYPE_CODES = {"2"}


@dataclass(frozen=True)
class SpeakerLabel:
    raw: str
    name: str = ""  # person's name without honorific; "" when unknown
    role: str = ""  # "The Deputy Speaker", "Minister of Finance", ...
    riding: str = ""
    party: str = ""
    is_chair: bool = False

    @property
    def is_full(self) -> bool:
        return bool(self.party or self.riding)


def strip_honorific(name: str) -> str:
    name = " ".join(name.split())
    changed = True
    while changed:
        changed = False
        for h in HONORIFICS:
            if name.startswith(h + " "):
                name = name[len(h) + 1 :].lstrip()
                changed = True
    return name


def _split_outer_parens(label: str) -> tuple[str, str]:
    """'A (B (C), D)' -> ('A', 'B (C), D'). Returns (label, '') when no parentheses."""
    start = label.find(" (")
    if start == -1 or not label.endswith(")"):
        return label, ""
    return label[:start].strip(), label[start + 2 : -1].strip()


def parse_label(raw: str, type_code: str | None = None) -> SpeakerLabel:
    label = " ".join((raw or "").split()).rstrip(":").strip()
    head, inside = _split_outer_parens(label)

    if head.startswith("The ") or head.startswith("Le ") or head.startswith("La "):
        # Chair occupant: "The Assistant Deputy Speaker (Mrs. Carol Hughes)"
        return SpeakerLabel(raw=label, name=strip_honorific(inside), role=head, is_chair=True)

    name = strip_honorific(head)
    if not inside:
        return SpeakerLabel(raw=label, name=name)

    rest, party = inside, ""
    if "," in inside:
        candidate_rest, candidate_party = (p.strip() for p in inside.rsplit(",", 1))
        if candidate_party in KNOWN_PARTIES or PARTY_PATTERN.match(candidate_party):
            rest, party = candidate_rest, PARTY_ALIASES.get(candidate_party, candidate_party)

    if type_code in MEMBER_TYPE_CODES:
        return SpeakerLabel(raw=label, name=name, riding=rest, party=party)
    return SpeakerLabel(raw=label, name=name, role=rest, party=party)
