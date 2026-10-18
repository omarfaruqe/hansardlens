"""Give every person a stable URL name (slug) for the member pages."""

from django.db import migrations, models


def fill_slugs(apps, schema_editor):
    from debates.models import person_slug

    Person = apps.get_model("debates", "Person")
    used: set[str] = set()
    for person in Person.objects.order_by("id"):
        person.slug = person_slug(person.name, used.__contains__)
        used.add(person.slug)
        person.save(update_fields=["slug"])


class Migration(migrations.Migration):
    dependencies = [("debates", "0006_topics_and_term_shifts")]

    operations = [
        migrations.AddField(
            model_name="person",
            name="slug",
            field=models.SlugField(max_length=180, default="", blank=True, db_index=False),
            preserve_default=False,
        ),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="person",
            name="slug",
            field=models.SlugField(max_length=180, unique=True),
        ),
    ]
