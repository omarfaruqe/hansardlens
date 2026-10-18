from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.db.models import Func, IntegerField, TextField, Value
from django.db.models.functions import Coalesce, NullIf, Trim

# Accent-insensitive text search configurations, created in migration 0003.
SEARCH_CONFIG = {"en": "en_unaccent", "fr": "fr_unaccent"}


class Sitting(models.Model):
    """One sitting day of the House of Commons (one Hansard issue)."""

    parliament = models.PositiveSmallIntegerField()
    session = models.PositiveSmallIntegerField()
    number = models.PositiveIntegerField()
    date = models.DateField(db_index=True)
    volume = models.CharField(max_length=40, blank=True)
    house_doc_id = models.CharField(max_length=20, blank=True)
    speaker_of_house = models.CharField(max_length=120, blank=True)
    has_french = models.BooleanField(default=False)
    checksum_en = models.CharField(max_length=64, blank=True)
    checksum_fr = models.CharField(max_length=64, blank=True)
    issues = models.JSONField(default=list, blank=True)
    loaded_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["parliament", "session", "number"], name="unique_sitting_number"
            )
        ]

    def __str__(self):
        return f"{self.parliament}-{self.session} No. {self.number:03d} ({self.date})"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("sitting_detail", args=[(self.parliament, self.session), self.number])


def person_slug(name: str, taken=None) -> str:
    """URL name for a person: 'Rhéal Éloi Fortin' -> 'rheal-eloi-fortin'. `taken(slug)`
    says whether a slug is already used; a clash gets -2, -3, ..."""
    from django.utils.text import slugify

    base = slugify(name)[:170] or "member"
    slug, n = base, 1
    while taken is not None and taken(slug):
        n += 1
        slug = f"{base}-{n}"
    return slug


class Person(models.Model):
    """A person who spoke, identified by name without honorific (House speaker ids
    are tied to a role, so one person can have several)."""

    name = models.CharField(max_length=160, unique=True)
    # Stable address of the member page (/members/<slug>/); set once from the name.
    slug = models.SlugField(max_length=180, unique=True)
    latest_party = models.CharField(max_length=20, blank=True)
    latest_riding = models.CharField(max_length=160, blank=True)
    latest_seen = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            others = Person.objects.exclude(pk=self.pk)
            self.slug = person_slug(self.name, lambda s: others.filter(slug=s).exists())
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("member_detail", args=[self.slug])


class Intervention(models.Model):
    """One speech, question, answer or interjection, or a block of procedural text.

    `kind` keeps the House's own Type value; a type not listed in Kind is stored as is
    and shows up in the quality report rather than being hidden as "Other"."""

    class Kind(models.TextChoices):
        DEBATE = "Debate"
        QUESTION = "Question"
        QUESTION_SUPPLEMENTAL = "QuestionSupplemental"
        QUESTION_COMMENT = "QuestionComment"
        ANSWER = "Answer"
        ANSWER_SUPPLEMENTAL = "AnswerSupplemental"
        RULING = "Ruling"
        INTERJECTION = "Interjection"
        STATEMENT = "Statement"
        PROCEDURAL = "Procedural"
        OTHER = "Other"

    sitting = models.ForeignKey(Sitting, on_delete=models.CASCADE, related_name="interventions")
    sequence = models.PositiveIntegerField()
    house_id = models.CharField(max_length=20, blank=True, db_index=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    rubric = models.CharField(max_length=40, blank=True, db_index=True)
    order_title_en = models.CharField(max_length=300, blank=True)
    order_title_fr = models.CharField(max_length=300, blank=True)
    subject_title_en = models.CharField(max_length=500, blank=True)
    subject_title_fr = models.CharField(max_length=500, blank=True)
    time = models.TimeField(null=True, blank=True)

    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="interventions"
    )
    speaker_db_id = models.CharField(max_length=20, blank=True)
    speaker_type = models.CharField(max_length=10, blank=True)
    speaker_label_en = models.CharField(max_length=400, blank=True)
    speaker_label_fr = models.CharField(max_length=400, blank=True)
    speaker_role = models.CharField(max_length=300, blank=True)
    is_chair = models.BooleanField(default=False)
    party = models.CharField(max_length=20, blank=True, db_index=True)
    riding = models.CharField(max_length=160, blank=True)

    text_en = models.TextField(blank=True)
    text_fr = models.TextField(blank=True)
    word_count_en = models.PositiveIntegerField(default=0)
    word_count_fr = models.PositiveIntegerField(default=0)
    # Words actually spoken on the floor in each language, counted in the original text
    floor_words_en = models.PositiveIntegerField(default=0)
    floor_words_fr = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sitting", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["sitting", "sequence"], name="unique_intervention_seq")
        ]

    def __str__(self):
        who = self.person.name if self.person else self.speaker_role or self.kind
        return f"{self.sitting} #{self.sequence} {who}"

    def get_absolute_url(self):
        from django.urls import reverse

        if self.house_id:
            return reverse("speech_detail", args=[self.house_id])
        return f"{self.sitting.get_absolute_url()}#iv-{self.sequence}"

    @property
    def speaker_display(self) -> str:
        if self.is_chair:
            return f"{self.speaker_role} ({self.person.name})" if self.person else self.speaker_role
        return self.person.name if self.person else self.speaker_label_en


class Paragraph(models.Model):
    class FloorLanguage(models.TextChoices):
        ENGLISH = "en"
        FRENCH = "fr"
        TEXT = "text"
        UNKNOWN = ""

    intervention = models.ForeignKey(
        Intervention, on_delete=models.CASCADE, related_name="paragraphs"
    )
    sequence = models.PositiveIntegerField()
    house_id = models.CharField(max_length=20, blank=True)
    kind = models.CharField(max_length=12)  # speech | procedural
    floor_language = models.CharField(max_length=4, choices=FloorLanguage.choices, blank=True)
    text_en = models.TextField(blank=True)
    text_fr = models.TextField(blank=True)
    # Maintained by PostgreSQL itself (generated columns), so loads need no extra step.
    # Length of the English text in whitespace-separated words. Used as one common
    # yardstick for both languages: French runs longer than English for the same
    # content, so comparing raw French and English word counts would overstate French.
    words_en = models.GeneratedField(
        expression=Coalesce(
            Func(
                Func(
                    NullIf(Trim("text_en"), Value("")),
                    Value(r"\s+"),
                    function="regexp_split_to_array",
                    output_field=ArrayField(TextField()),
                ),
                Value(1),
                function="array_length",
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        output_field=IntegerField(),
        db_persist=True,
    )
    search_en = models.GeneratedField(
        expression=SearchVector("text_en", config=SEARCH_CONFIG["en"]),
        output_field=SearchVectorField(),
        db_persist=True,
    )
    search_fr = models.GeneratedField(
        expression=SearchVector("text_fr", config=SEARCH_CONFIG["fr"]),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        ordering = ["intervention", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["intervention", "sequence"], name="unique_paragraph_seq"
            )
        ]
        indexes = [
            GinIndex(fields=["search_en"], name="paragraph_search_en_gin"),
            GinIndex(fields=["search_fr"], name="paragraph_search_fr_gin"),
        ]


class TopicModel(models.Model):
    """One fitted NMF topic model. Only the active model per language is shown."""

    lang = models.CharField(max_length=2, default="en")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=False)
    n_topics = models.PositiveSmallIntegerField()
    n_documents = models.PositiveIntegerField()
    vocabulary_size = models.PositiveIntegerField()
    first_date = models.DateField(null=True)
    last_date = models.DateField(null=True)
    params = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.lang} model, {self.n_topics} topics ({self.created_at:%Y-%m-%d})"


class Topic(models.Model):
    model = models.ForeignKey(TopicModel, on_delete=models.CASCADE, related_name="topics")
    number = models.PositiveSmallIntegerField()  # 1-based, stable within a model
    terms = models.JSONField(default=list)  # [[term, weight], ...] strongest first
    share = models.FloatField(default=0)  # share of documents whose main topic this is
    title = models.CharField(
        max_length=120, blank=True, help_text="Optional human label; defaults to the top words."
    )

    class Meta:
        ordering = ["model", "number"]
        constraints = [
            models.UniqueConstraint(fields=["model", "number"], name="unique_topic_number")
        ]

    @property
    def label(self) -> str:
        return self.title or ", ".join(t for t, _ in self.terms[:4])

    def __str__(self):
        return f"{self.number}: {self.label}"


class InterventionTopic(models.Model):
    """The main topic of one speech, with its share of the speech's topic weights."""

    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="assignments")
    intervention = models.ForeignKey(
        Intervention, on_delete=models.CASCADE, related_name="topic_assignments"
    )
    weight = models.FloatField()

    class Meta:
        indexes = [models.Index(fields=["topic", "-weight"], name="topic_weight_idx")]


class TermShift(models.Model):
    """Words and phrases rising or fading in a recent window compared with a baseline."""

    lang = models.CharField(max_length=2, default="en")
    created_at = models.DateTimeField(auto_now_add=True)
    recent_start = models.DateField()
    recent_end = models.DateField()
    base_start = models.DateField()
    base_end = models.DateField()
    words_recent = models.PositiveBigIntegerField()
    words_base = models.PositiveBigIntegerField()
    rising = models.JSONField(default=list)
    fading = models.JSONField(default=list)
    params = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]
