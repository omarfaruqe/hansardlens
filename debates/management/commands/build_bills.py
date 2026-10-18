"""Find the bills debated in the House and link them to their debates and votes.

    python manage.py build_bills

Rebuilds everything from the loaded debates in a minute or two; refresh_data runs it
whenever new sittings arrive. See debates/bills.py for the method.
"""

from django.core.management.base import BaseCommand

from debates.bills import build_bills


class Command(BaseCommand):
    help = "Find bills and link them to their debates and recorded votes."

    def handle(self, *args, **options):
        result = build_bills()
        self.stdout.write(
            self.style.SUCCESS(
                f"{result['bills']} bill(s); {result['linked']} intervention(s) in bill debates."
            )
        )
