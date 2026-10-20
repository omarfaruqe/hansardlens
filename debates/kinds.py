"""What kind of speech each intervention is, when the House's own Type does not say.

Hansard types most interventions "Debate", including most members' statements and many
questions and answers in Question Period (in the 42nd Parliament, all of them). The
part of the sitting day is reliable, so:

- an intervention typed "Debate" during Statements by Members is a statement;
- one typed "Debate" during Oral Questions is an answer when the speaker answers in that
  Question Period (the House typed one of their interventions "Answer", or their label
  gives a ministerial role: minister, parliamentary secretary, Government House
  Leader...), and a question otherwise.

Anything said from the chair, and every other Type, is left as the House typed it. The
House's Type is kept in `Intervention.house_type`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

STATEMENTS = "StatementsByMembers"
QUESTION_PERIOD = "OralQuestionPeriod"
ANSWER_TYPES = {"Answer", "AnswerSupplemental"}
MINISTERIAL = re.compile(
    r"\b(?:minister|parliamentary secretary|leader of the government|secretary of state|"
    r"president of the (?:treasury board|queen's privy council|king's privy council))\b",
    re.I,
)


def _speaker(row: dict):
    if row["person_id"]:
        return ("person", row["person_id"])
    if row["speaker_db_id"]:
        return ("db", row["speaker_db_id"])
    return ("row", row["id"])


def infer(rows: Iterable[dict]) -> dict[int, str]:
    """rows: the interventions of one sitting during Statements by Members and Oral
    Questions, as dicts with id, house_type, rubric, is_chair, person_id, speaker_db_id
    and speaker_role. Returns {id: kind} for the ones whose kind changes."""
    rows = [r for r in rows if not r["is_chair"]]
    answerers = {
        _speaker(r)
        for r in rows
        if r["rubric"] == QUESTION_PERIOD
        and (r["house_type"] in ANSWER_TYPES or MINISTERIAL.search(r["speaker_role"] or ""))
    }
    out = {}
    for r in rows:
        if r["house_type"] != "Debate":
            continue
        if r["rubric"] == STATEMENTS:
            out[r["id"]] = "Statement"
        elif r["rubric"] == QUESTION_PERIOD:
            out[r["id"]] = "Answer" if _speaker(r) in answerers else "Question"
    return out


FIELDS = ("id", "house_type", "rubric", "is_chair", "person_id", "speaker_db_id", "speaker_role")


def apply(intervention_model, sitting_ids: Iterable[int] | None = None) -> int:
    """Set inferred kinds for the given sittings (all when None). Works with the real
    model or a migration's historical one. Returns the number of interventions changed."""
    qs = intervention_model.objects.filter(rubric__in=[STATEMENTS, QUESTION_PERIOD])
    if sitting_ids is not None:
        qs = qs.filter(sitting_id__in=list(sitting_ids))
    by_sitting: dict[int, list[dict]] = {}
    for row in qs.values("sitting_id", *FIELDS).iterator(chunk_size=5000):
        by_sitting.setdefault(row["sitting_id"], []).append(row)
    changes: dict[str, list[int]] = {}
    for rows in by_sitting.values():
        for pk, kind in infer(rows).items():
            changes.setdefault(kind, []).append(pk)
    changed = 0
    for kind, ids in changes.items():
        for i in range(0, len(ids), 5000):
            changed += intervention_model.objects.filter(id__in=ids[i : i + 5000]).update(kind=kind)
    return changed
