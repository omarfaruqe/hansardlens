"""Accent-insensitive full-text search configurations for English and French.

`unaccent` runs before stemming, so "economie" matches "économie" and "Quebec" matches
"Québec". Generated search columns (next migration) use these configurations.
"""

from django.db import migrations

SQL = """
CREATE EXTENSION IF NOT EXISTS unaccent;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'en_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION en_unaccent (COPY = english);
        ALTER TEXT SEARCH CONFIGURATION en_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, english_stem;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'fr_unaccent') THEN
        CREATE TEXT SEARCH CONFIGURATION fr_unaccent (COPY = french);
        ALTER TEXT SEARCH CONFIGURATION fr_unaccent
            ALTER MAPPING FOR hword, hword_part, word WITH unaccent, french_stem;
    END IF;
END $$;
"""

REVERSE = """
DROP TEXT SEARCH CONFIGURATION IF EXISTS en_unaccent;
DROP TEXT SEARCH CONFIGURATION IF EXISTS fr_unaccent;
"""

PARTY_FIX = """
UPDATE debates_intervention SET party = 'CPC' WHERE party = 'PCC';
UPDATE debates_intervention SET party = 'NDP' WHERE party = 'NPD';
UPDATE debates_person SET latest_party = 'CPC' WHERE latest_party = 'PCC';
UPDATE debates_person SET latest_party = 'NDP' WHERE latest_party = 'NPD';
"""


class Migration(migrations.Migration):
    dependencies = [("debates", "0002_intervention_statement_kind")]

    operations = [
        migrations.RunSQL(SQL, REVERSE),
        migrations.RunSQL(PARTY_FIX, migrations.RunSQL.noop),
    ]
