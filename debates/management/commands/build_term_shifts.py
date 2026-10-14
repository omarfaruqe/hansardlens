"""Find words and phrases rising or fading in recent debate.

    python manage.py build_term_shifts                       # last 60 days vs the year before
    python manage.py build_term_shifts --recent-days 90 --lang fr

The recent window ends at the last loaded sitting.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from debates.models import Sitting
from debates.textmine import ShiftParams, compute_shifts


class Command(BaseCommand):
    help = "Compute rising and fading terms (log-odds ratio with an informative prior)."

    def add_arguments(self, parser):
        d = ShiftParams()
        parser.add_argument("--lang", choices=["en", "fr"], default=d.lang)
        parser.add_argument("--recent-days", type=int, default=d.recent_days)
        parser.add_argument("--base-days", type=int, default=d.base_days)
        parser.add_argument(
            "--min-count",
            type=int,
            default=d.min_count,
            help="Minimum occurrences in the window where the term is listed.",
        )
        parser.add_argument("--top", type=int, default=d.top)

    def handle(self, *args, **o):
        end = Sitting.objects.aggregate(m=Max("date"))["m"]
        if end is None:
            raise CommandError("No sittings loaded.")
        params = ShiftParams(
            lang=o["lang"],
            recent_days=o["recent_days"],
            base_days=o["base_days"],
            min_count=o["min_count"],
            top=o["top"],
        )
        try:
            shift = compute_shifts(params, end, log=self.stdout.write)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"\nRecent {shift.recent_start} to {shift.recent_end} "
            f"vs {shift.base_start} to {shift.base_end}"
        )
        self.stdout.write("Rising: " + ", ".join(r["term"] for r in shift.rising[:15]))
        self.stdout.write("Fading: " + ", ".join(r["term"] for r in shift.fading[:15]))
        self.stdout.write(self.style.SUCCESS("Saved."))
