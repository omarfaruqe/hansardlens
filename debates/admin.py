from django.contrib import admin

from .models import Intervention, Paragraph, Person, Sitting, Topic, TopicModel


@admin.register(Sitting)
class SittingAdmin(admin.ModelAdmin):
    list_display = ("parliament", "session", "number", "date", "has_french", "loaded_at")
    list_filter = ("parliament", "session", "has_french")
    date_hierarchy = "date"


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("name", "latest_party", "latest_riding", "latest_seen")
    list_filter = ("latest_party",)
    search_fields = ("name", "latest_riding")


class ParagraphInline(admin.TabularInline):
    model = Paragraph
    extra = 0
    fields = ("sequence", "kind", "floor_language", "text_en", "text_fr")
    readonly_fields = fields


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ("sitting", "sequence", "kind", "person", "party", "rubric", "time")
    list_filter = ("kind", "rubric", "party", "sitting__parliament")
    search_fields = ("person__name", "subject_title_en", "subject_title_fr")
    raw_id_fields = ("sitting", "person")
    inlines = [ParagraphInline]


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 0
    fields = ("number", "title", "share", "top_words")
    readonly_fields = ("number", "share", "top_words")

    @admin.display(description="Top words")
    def top_words(self, obj):
        return ", ".join(t for t, _ in obj.terms[:8])


@admin.register(TopicModel)
class TopicModelAdmin(admin.ModelAdmin):
    list_display = ("lang", "n_topics", "n_documents", "created_at", "is_active")
    readonly_fields = ("params",)
    inlines = [TopicInline]
