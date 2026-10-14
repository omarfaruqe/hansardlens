"""Daily refresh: load new sittings, then update the analysis.

    python manage.py refresh_data              # new sittings + term shifts
    python manage.py refresh_data --topics     # also refit the topic model
    python manage.py refresh_data --sleep 0.5

Continues the most recent session. When it has nothing new, it checks whether a new
session (prorogation) or a new Parliament (election) has started, and follows it.
The topic model is refit when --topics is given or when it is more than 7 days old.
Exits with an error status if any sitting failed to load, so a scheduler can alert.
"""

import datetime as dt
import io

import requests
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.utils import timezone

from debates.loader import SittingNotFound, load_sitting
from debates.models import Sitting, TopicModel

FIRST_SESSION = (44, 1)  # where an empty database starts
TOPIC_MAX_AGE = dt.timedelta(days=7)


class Command(BaseCommand):
    help = "Load new sittings and refresh term shifts (and topics weekly)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)
        parser.add_argument("--topics", action="store_true", help="Refit the topic model now.")
        parser.add_argument("--skip-analysis", action="store_true")

    def _load(self, parliament, session, sleep) -> tuple[int, int]:
        before = Sitting.objects.filter(parliament=parliament, session=session).count()
        out = io.StringIO()
        call_command(
            "load_hansard",
            parliament=parliament,
            session=session,
            sleep=sleep,
            stdout=out,
            stderr=out,
        )
        text = out.getvalue()
        for line in text.splitlines():
            if "failed" in line or "Done" in line:
                self.stdout.write(f"  {line.strip()}")
        loaded = Sitting.objects.filter(parliament=parliament, session=session).count() - before
        errors = text.count("failed:")
        return loaded, errors

    def _exists(self, parliament, session) -> bool:
        """Is sitting 1 of this session published? Loads it if so."""
        try:
            load_sitting(parliament, session, 1)
            return True
        except SittingNotFound:
            return False

    def handle(self, *args, **o):
        latest = (
            Sitting.objects.order_by("-parliament", "-session")
            .values_list("parliament", "session")
            .first()
        ) or FIRST_SESSION
        parliament, session = latest
        new = errors = 0

        self.stdout.write(f"Checking {parliament}-{session} for new sittings")
        loaded, failed = self._load(parliament, session, o["sleep"])
        new, errors = new + loaded, errors + failed

        if loaded == 0 and not failed:
            for candidate in ((parliament, session + 1), (parliament + 1, 1)):
                try:
                    found = self._exists(*candidate)
                except (requests.RequestException, ValueError) as exc:
                    self.stderr.write(f"  could not check {candidate[0]}-{candidate[1]}: {exc}")
                    errors += 1
                    break
                if found:
                    self.stdout.write(f"New session found: {candidate[0]}-{candidate[1]}")
                    new += 1
                    loaded, failed = self._load(*candidate, o["sleep"])
                    new, errors = new + loaded, errors + failed
                    break

        self.stdout.write(
            f"{new} new sitting(s); latest is {Sitting.objects.aggregate(d=Max('date'))['d']}"
        )

        if not o["skip_analysis"] and Sitting.objects.exists():
            if new:
                self._run("build_term_shifts")
            model = TopicModel.objects.filter(lang="en", is_active=True).first()
            stale = model is None or timezone.now() - model.created_at > TOPIC_MAX_AGE
            if o["topics"] or (new and stale):
                self._run("build_topics")

        if errors:
            raise CommandError(f"{errors} sitting(s) failed to load; run again later.")
        self.stdout.write(self.style.SUCCESS("Refresh complete."))

    def _run(self, name):
        self.stdout.write(f"Running {name}")
        out = io.StringIO()
        try:
            call_command(name, stdout=out)
        except CommandError as exc:
            self.stderr.write(f"  {name} skipped: {exc}")
            return
        last = [line for line in out.getvalue().splitlines() if line.strip()][-1:]
        for line in last:
            self.stdout.write(f"  {line}")
