"""Load House of Commons sittings into the database.

Examples:
    # Incremental: continue after the last loaded sitting until the House has no more
    python manage.py load_hansard --parliament 45 --session 1

    # An explicit range
    python manage.py load_hansard --parliament 44 --session 1 --from 1 --to 50

    # Re-parse already downloaded files (no network) after a parser change
    python manage.py load_hansard --parliament 44 --session 1 --from 1 --to 50
    # ...add --refresh to download again from the House website
"""

import time

import requests
from django.core.management.base import BaseCommand
from django.db.models import Max

from debates.loader import SittingNotFound, backfill_missing_parties, load_sitting, raw_path
from debates.models import Sitting


class Command(BaseCommand):
    help = "Download, parse and store Hansard sittings (English and French)."

    def add_arguments(self, parser):
        parser.add_argument("--parliament", type=int, required=True)
        parser.add_argument("--session", type=int, required=True)
        parser.add_argument(
            "--from",
            dest="start",
            type=int,
            help="First sitting number (default: one after the last loaded).",
        )
        parser.add_argument(
            "--to",
            dest="end",
            type=int,
            help="Last sitting number (default: keep going until the House has no more).",
        )
        parser.add_argument(
            "--max-misses",
            type=int,
            default=3,
            help="Without --to, stop after this many missing sittings in a row (default 3).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help="Seconds to wait after each download, to be polite to the House (default 1).",
        )
        parser.add_argument(
            "--refresh", action="store_true", help="Download again even if cached in data/raw."
        )

    def handle(self, *args, **opts):
        p, s = opts["parliament"], opts["session"]
        start = opts["start"]
        if start is None:
            last = Sitting.objects.filter(parliament=p, session=s).aggregate(m=Max("number"))["m"]
            start = (last or 0) + 1
        end = opts["end"]
        self.stdout.write(f"Loading {p}-{s} from sitting {start} to {end or 'the latest'}")

        loaded = errors = misses = failures = 0
        number = start
        while end is None or number <= end:
            cached = raw_path(p, s, number, "en").exists() and not opts["refresh"]
            try:
                result = load_sitting(p, s, number, refresh=opts["refresh"])
            except SittingNotFound:
                misses += 1
                self.stdout.write(f"  {number:03d}: not published")
                if end is None and misses >= opts["max_misses"]:
                    break
            except (requests.RequestException, ValueError) as exc:
                errors += 1
                failures += 1
                self.stderr.write(self.style.ERROR(f"  {number:03d}: failed: {exc}"))
                if end is None and failures >= opts["max_misses"]:
                    self.stderr.write("  stopping: several failures in a row (network down?)")
                    break
            else:
                misses = failures = 0
                loaded += 1
                sit = result.sitting
                flag = "" if sit.has_french else "  (no French)"
                note = f"  [{len(sit.issues)} issue(s)]" if sit.issues else ""
                self.stdout.write(
                    f"  {number:03d}: {sit.date}  {result.interventions} interventions, "
                    f"{result.paragraphs} paragraphs{flag}{note}"
                )
            if not cached and opts["sleep"]:
                time.sleep(opts["sleep"])
            number += 1

        if loaded:
            fixed = backfill_missing_parties()
            if fixed:
                self.stdout.write(f"Filled the party for {fixed} short-label intervention(s).")
            from debates.votes import link_votes

            linked = link_votes()
            if linked:
                self.stdout.write(f"Matched {linked} earlier vote(s) to members.")

        style = self.style.SUCCESS if not errors else self.style.WARNING
        self.stdout.write(style(f"Done: {loaded} sitting(s) loaded, {errors} error(s)."))
