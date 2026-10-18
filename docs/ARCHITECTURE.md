# HansardLens architecture

## Data flow

```mermaid
flowchart LR
    H["ourcommons.ca<br/>Hansard XML (EN + FR)"] -->|fetch with retries,<br/>cached in data/raw| P["parsing.py<br/>document walk + EN/FR merge"]
    P -->|one transaction per sitting| DB[("PostgreSQL 16<br/>sittings, interventions,<br/>paragraphs + generated<br/>search columns")]
    DB --> S["search.py<br/>full-text search"]
    DB --> A["analysis.py<br/>trends, language shares"]
    DB --> T["textmine.py<br/>NMF topics, term shifts"]
    T -->|stored results| DB
    S & A & DB --> W["Django views<br/>EN/FR pages"]
    S & A & DB --> R["REST API /api/v1<br/>OpenAPI docs"]
    A -.->|cached until next load| C[("file cache")]
```

## Components

| Path | Responsibility |
| ---- | -------------- |
| `debates/hansard_xml.py` | URL pattern, polite fetch with retries (2, 4, 8 s), structure report |
| `debates/parsing.py` | Walk one XML document in order (agenda, time and floor language as running state); merge English and French |
| `debates/speakers.py` | Parse speaker labels: name, honorific, riding, role, party, chair occupants |
| `debates/loader.py` | Cache, download, store a sitting atomically, backfill parties |
| `debates/search.py` | Query parsing, filters, ranking, safe highlighted snippets |
| `debates/analysis.py` | Monthly term rates, language shares, topic shares, member profiles; cached by data version |
| `debates/textmine.py` | TF-IDF + NMF topics; log-odds term shifts |
| `debates/votes.py` | Store recorded votes, match printed names to members, mark party lines |
| `debates/api.py` | Read-only DRF endpoints and OpenAPI schema |
| `debates/middleware.py` | Interface language from `?lang=`, remembered in a cookie |
| `debates/templatetags/hansard.py` | Locale-aware dates, ordinals, party abbreviations |
| `static/js/linechart.js` | Dependency-free SVG line chart with keyboard crosshair |

## Data model

```mermaid
erDiagram
    Sitting ||--o{ Intervention : has
    Person |o--o{ Intervention : speaks
    Intervention ||--o{ Paragraph : has
    TopicModel ||--o{ Topic : has
    Topic ||--o{ InterventionTopic : assigns
    Intervention ||--o| InterventionTopic : "main topic"
    Sitting ||--o{ Division : holds
    Division ||--o{ Vote : records
    Person |o--o{ Vote : casts
```

- `Paragraph.search_en`, `search_fr` and `words_en` are PostgreSQL generated columns,
  so a load never needs a separate indexing step.
- A sitting is replaced as a whole in one transaction, so reloading is idempotent.
- Speeches are addressed by the House's own id (`/speeches/12601257/`), sittings by
  number (`/sittings/44-1/50/`) and members by a name-based slug set once
  (`/members/bernard-genereux/`), so links survive reloads.

## Commands

| Command | Purpose |
| ------- | ------- |
| `inspect_sitting` | Download one sitting and report its XML structure |
| `load_hansard` | Load a range of sittings, or continue to the latest |
| `hansard_quality` | Data-quality report |
| `build_topics` | Fit the topic model |
| `build_term_shifts` | Compute rising and fading terms |
| `load_divisions` | Add recorded votes to sittings loaded before version 1.5 |
| `refresh_data` | Daily: load new sittings (following a new session or Parliament), then update the analysis |

## Testing

- 204 tests with pytest against PostgreSQL (CI uses a PostgreSQL service).
- The parser is tested on invented XML with the real structure (real Hansard text is
  never committed), and on real sittings when they have been downloaded locally.
- The ingestion commands are tested against a fake House website: missing sittings,
  network failures, missing French versions, new sessions and new Parliaments.
- The text-mining methods are tested on a synthetic corpus with two known subjects.
