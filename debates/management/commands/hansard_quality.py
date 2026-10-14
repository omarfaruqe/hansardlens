from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from debates.quality import build_report


class Command(BaseCommand):
    help = "Print a data-quality report and save it to data/reports/."

    def handle(self, *args, **opts):
        report = build_report()
        out_dir = Path(settings.DATA_DIR) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"quality_{datetime.now():%Y%m%d_%H%M}.txt"
        path.write_text(report + "\n", encoding="utf-8")
        self.stdout.write(report)
        self.stdout.write(self.style.SUCCESS(f"\nSaved to {path}"))
