"""Download one Hansard sitting (EN and/or FR) and print its XML structure.

Examples:
    python manage.py inspect_sitting --parliament 44 --session 1 --sitting 1
    python manage.py inspect_sitting --parliament 44 --session 1 --sitting 1 --lang fr
    python manage.py inspect_sitting --file data/raw/HAN001-E.XML
"""

from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from debates.hansard_xml import fetch, sitting_url, summarize


class Command(BaseCommand):
    help = "Download one Hansard sitting and report its XML structure (Sprint 0 discovery)."

    def add_arguments(self, parser):
        parser.add_argument("--parliament", type=int, default=44)
        parser.add_argument("--session", type=int, default=1)
        parser.add_argument("--sitting", type=int, default=1)
        parser.add_argument(
            "--lang",
            choices=["en", "fr", "both"],
            default="both",
            help="Which language version(s) to inspect (default: both).",
        )
        parser.add_argument("--file", help="Inspect a local XML file instead of downloading.")
        parser.add_argument("--max-paths", type=int, default=400)

    def handle(self, *args, **opts):
        raw_dir = Path(settings.DATA_DIR) / "raw"
        report_dir = Path(settings.DATA_DIR) / "reports"
        raw_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        if opts["file"]:
            path = Path(opts["file"])
            if not path.exists():
                raise CommandError(f"File not found: {path}")
            self._report(
                path.read_bytes(),
                label=path.name,
                source=str(path),
                report_dir=report_dir,
                max_paths=opts["max_paths"],
            )
            return

        langs = ["en", "fr"] if opts["lang"] == "both" else [opts["lang"]]
        p, s, n = opts["parliament"], opts["session"], opts["sitting"]
        for lang in langs:
            url = sitting_url(p, s, n, lang)
            self.stdout.write(f"Fetching {url}")
            try:
                content = fetch(url, settings.HANSARD_USER_AGENT)
            except requests.RequestException as exc:
                self.stderr.write(self.style.ERROR(f"  {lang}: download failed: {exc}"))
                continue

            label = f"P{p}S{s}-{n:03d}-{lang}"
            raw_path = raw_dir / f"{label}.xml"
            raw_path.write_bytes(content)
            self.stdout.write(f"  saved {len(content):,} bytes to {raw_path}")
            self._report(
                content, label=label, source=url, report_dir=report_dir, max_paths=opts["max_paths"]
            )

    def _report(self, content, *, label, source, report_dir, max_paths):
        try:
            summary = summarize(content)
        except Exception as exc:  # malformed XML or an HTML error page
            head = content[:300].decode("utf-8", errors="replace")
            raise CommandError(
                f"Could not parse XML from {source}: {exc}\nStart of body:\n{head}"
            ) from exc

        text = f"Source: {source}\n\n{summary.render(max_paths=max_paths)}\n"
        report_path = report_dir / f"structure_{label}.txt"
        report_path.write_text(text, encoding="utf-8")
        self.stdout.write(text)
        self.stdout.write(self.style.SUCCESS(f"Report written to {report_path}"))
