"""Load the public meetings (evidence) of selected House committees.

    python manage.py load_committees                         # configured committees, every
                                                             # session with House sittings
    python manage.py load_committees --committee FINA --parliament 44 --session 1
    python manage.py load_committees --committee ETHI --parliament 44 --session 1 --from 1 --to 20
    python manage.py load_committees --no-cache              # do not keep the XML

Committees default to HANSARD_COMMITTEES (FINA, OGGO, ETHI). Without --from, each
committee continues after its last loaded meeting. Meetings held in camera have no
transcript and are skipped; the search for more stops after --max-misses meetings in a
row without one.
"""

import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Max

from debates.committees import MeetingNotFound, NoEvidence, load_meeting, raw_path
from debates.models import Meeting, Sitting


class Command(BaseCommand):
    help = "Load public committee meetings (evidence) in English and French."

    def add_arguments(self, parser):
        parser.add_argument("--committee", action="append", help="Acronym, e.g. FINA (repeatable)")
        parser.add_argument("--parliament", type=int)
        parser.add_argument("--session", type=int)
        parser.add_argument("--from", dest="start", type=int)
        parser.add_argument("--to", dest="end", type=int)
        parser.add_argument("--max-misses", type=int, default=15)
        parser.add_argument("--sleep", type=float, default=1.0)
        parser.add_argument("--no-cache", action="store_true", help="Do not keep the XML.")

    def handle(self, *args, **o):
        committees = [c.upper() for c in (o["committee"] or settings.HANSARD_COMMITTEES)]
        if o["parliament"] and o["session"]:
            sessions = [(o["parliament"], o["session"])]
        else:
            sessions = list(
                Sitting.objects.values_list("parliament", "session")
                .distinct()
                .order_by("parliament", "session")
            )
            if o["parliament"]:
                sessions = [s for s in sessions if s[0] == o["parliament"]]
        loaded = errors = 0
        for parliament, session in sessions:
            for acronym in committees:
                n, e = self._load(acronym, parliament, session, o)
                loaded, errors = loaded + n, errors + e
        style = self.style.SUCCESS if not errors else self.style.WARNING
        self.stdout.write(style(f"Done: {loaded} meeting(s) loaded, {errors} error(s)."))

    def _load(self, acronym, parliament, session, o):
        start = o["start"]
        if start is None:
            last = Meeting.objects.filter(
                committee__acronym=acronym, parliament=parliament, session=session
            ).aggregate(m=Max("number"))["m"]
            start = (last or 0) + 1
        self.stdout.write(f"{acronym} {parliament}-{session}: from meeting {start}")
        loaded = errors = misses = 0
        number = start
        while o["end"] is None or number <= o["end"]:
            cached = raw_path(parliament, session, acronym, number, "en").exists()
            try:
                result = load_meeting(parliament, session, acronym, number, keep=not o["no_cache"])
            except (MeetingNotFound, NoEvidence) as exc:
                misses += 1
                why = "no transcript (in camera?)" if isinstance(exc, NoEvidence) else "no meeting"
                self.stdout.write(f"  {number:03d}: {why}")
                if o["end"] is None and misses >= o["max_misses"]:
                    break
            except (requests.RequestException, ValueError) as exc:
                errors += 1
                misses += 1
                self.stderr.write(self.style.ERROR(f"  {number:03d}: failed: {exc}"))
                if o["end"] is None and misses >= o["max_misses"]:
                    break
            else:
                misses = 0
                loaded += 1
                m = result.meeting
                self.stdout.write(
                    f"  {number:03d}: {m.date}  {result.interventions} interventions, "
                    f"{result.witnesses} witness(es)"
                )
            if not cached and o["sleep"]:
                time.sleep(o["sleep"])
            number += 1
        return loaded, errors
