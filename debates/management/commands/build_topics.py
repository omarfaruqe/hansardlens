"""Fit an NMF topic model over member speeches and make it the active one.

    python manage.py build_topics                 # English, 30 topics
    python manage.py build_topics --lang fr --topics 25

Takes a few minutes on the full record. Re-run after loading new sittings; the new
model replaces the previous one for that language. Human titles set in the admin are
not carried over, because topic numbers can change between fits.
"""

import time

from django.core.management.base import BaseCommand, CommandError

from debates.textmine import TopicParams, fit_topics


class Command(BaseCommand):
    help = "Fit the TF-IDF + NMF topic model over member speeches."

    def add_arguments(self, parser):
        d = TopicParams()
        parser.add_argument("--lang", choices=["en", "fr"], default=d.lang)
        parser.add_argument("--topics", type=int, default=d.n_topics)
        parser.add_argument(
            "--min-df",
            type=int,
            default=d.min_df,
            help="Ignore terms used in fewer speeches than this.",
        )
        parser.add_argument(
            "--max-df",
            type=float,
            default=d.max_df,
            help="Ignore terms used in more than this share of speeches.",
        )
        parser.add_argument("--max-features", type=int, default=d.max_features)
        parser.add_argument(
            "--min-words",
            type=int,
            default=d.min_words,
            help="Skip speeches shorter than this many words.",
        )
        parser.add_argument("--seed", type=int, default=d.random_state)

    def handle(self, *args, **o):
        params = TopicParams(
            lang=o["lang"],
            n_topics=o["topics"],
            min_df=o["min_df"],
            max_df=o["max_df"],
            max_features=o["max_features"],
            min_words=o["min_words"],
            random_state=o["seed"],
        )
        start = time.monotonic()
        try:
            model = fit_topics(params, log=self.stdout.write)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("")
        for topic in model.topics.order_by("-share"):
            self.stdout.write(f"{topic.number:>3}  {100 * topic.share:5.1f}%  {topic.label}")
        self.stdout.write(
            self.style.SUCCESS(
                f"\nModel with {model.n_topics} topics over {model.n_documents:,} speeches "
                f"in {time.monotonic() - start:.0f} s."
            )
        )
