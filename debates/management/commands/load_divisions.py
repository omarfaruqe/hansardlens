"""Add recorded votes to sittings that are already loaded.

    python manage.py load_divisions                      # every loaded sitting
    python manage.py load_divisions --parliament 45 --session 1
    python manage.py load_divisions --no-cache           # do not keep the downloads

New sittings get their votes when they are loaded; this command is for sittings loaded
before votes were recorded (HansardLens 1.4 and earlier). It reads the XML from the
cache in data/raw, downloading what is missing, and only replaces the votes: speeches
are left as they are. Safe to run again.
"""

import time

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from debates.loader import SittingNotFound, get_xml, raw_path
from debates.models import Sitting
from debates.parsing import merge, parse_document
from debates.votes import link_votes, store_divisions


class Command(BaseCommand):
    help = "Record the votes (divisions) of sittings already in the database."

    def add_arguments(self, parser):
        parser.add_argument("--parliament", type=int)
        parser.add_argument("--session", type=int)
        parser.add_argument("--sleep", type=float, default=1.0, help="Pause after downloads.")
        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Do not save downloaded XML in data/raw (about 1.5 MB per sitting).",
        )

    def handle(self, *args, **o):
        sittings = Sitting.objects.order_by("parliament", "session", "number")
        if o["parliament"]:
            sittings = sittings.filter(parliament=o["parliament"])
        if o["session"]:
            sittings = sittings.filter(session=o["session"])
        cache: dict = {}
        total = divisions = errors = 0
        for s in sittings:
            cached = raw_path(s.parliament, s.session, s.number, "en").exists()
            try:
                keep = not o["no_cache"]
                en = parse_document(get_xml(s.parliament, s.session, s.number, "en", keep=keep))
                try:
                    fr = parse_document(get_xml(s.parliament, s.session, s.number, "fr", keep=keep))
                except SittingNotFound:
                    fr = None
                with transaction.atomic():
                    n = store_divisions(s, merge(en, fr), cache=cache)
            except (SittingNotFound, requests.RequestException, ValueError) as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"  {s}: failed: {exc}"))
            else:
                total += 1
                divisions += n
                if n:
                    self.stdout.write(f"  {s}: {n} vote(s)")
            if not cached and o["sleep"]:
                time.sleep(o["sleep"])
        linked = link_votes(cache=cache)
        if linked:
            self.stdout.write(f"Matched {linked} more vote(s) to members.")
        style = self.style.SUCCESS if not errors else self.style.WARNING
        self.stdout.write(
            style(f"Done: {divisions} division(s) in {total} sitting(s), {errors} error(s).")
        )
