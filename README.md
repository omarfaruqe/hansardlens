# HansardLens

Search and analyse the debates of the House of Commons of Canada in English and French.

HansardLens loads the official Hansard every sitting day, pairs every paragraph with
its translation, and records which language was actually spoken on the floor. On top of
that record it offers bilingual full-text search, a side-by-side reading view, term
trends, the share of debate held in French, topics found by NMF, and the words rising
or fading in recent debate, bills, recorded votes, a page for every member, and the
transcripts of the standing committees with the witnesses they heard. Everything is available
through a documented REST API.
Every figure is a descriptive share with a stated denominator.

**Live site:** http://103.99.176.180/hansardlens/ (English and French, updated every
sitting day). **API docs:** http://103.99.176.180/hansardlens/api/docs/

![Search results for "clean water", with highlighted matches and filters](docs/screenshots/search.png)

| Bilingual reading view | French interface |
| ---------------------- | ---------------- |
| ![A speech in English and French side by side; the language actually spoken is marked](docs/screenshots/speech.png) | ![Search in the French interface](docs/screenshots/search-fr.png) |

| Recorded vote by party | Bill page |
| ---------------------- | --------- |
| ![A recorded vote with counts, a breakdown by party and each member's vote](docs/screenshots/vote.png) | ![A bill page with its stages in the House, speakers and debate days](docs/screenshots/bill.png) |

| Members | Votes in the French interface |
| ------- | ----------------------------- |
| ![The list of members with party, riding, speeches and last appearance](docs/screenshots/members.png) | ![The list of recorded votes in French](docs/screenshots/votes-fr.png) |

*Screenshots from a development database with a sample of sittings.*

**How it was built and why:** [docs/CASE_STUDY.md](docs/CASE_STUDY.md).

## Features

- **Search** either language at paragraph level: accent-insensitive with stemming,
  `"exact phrases"`, `OR` and `-exclude`, with filters for party, member, part of the
  sitting day, Parliament and dates.
- **Read** any speech with English and French side by side; the column marked in red
  is what was actually said, the other is the official translation.
- **Trends:** compare up to four terms month by month, per 1,000 speech paragraphs.
- **Members:** a page for everyone who has spoken: party, riding and roles over time,
  speeches by month and kind, the share spoken in French, main topics, and their
  speeches, with a search limited to them.
- **Recorded votes:** every division with the question, result, a breakdown by party
  at the time of the vote, the members who voted differently from most of their party,
  and every member's vote, linked to the debate and to the House's own page.
- **Bills:** each bill debated in the House, found from the motions that move it, with
  its titles in both languages, stages moved and completed, recorded votes, debate days
  and who spoke most, linked to LEGISinfo for status and text.
- **Committees:** the public meetings of the House's 25 standing committees in English
  and French, with the witnesses heard,
  their titles and organisations, a page for each witness, the committee work of each
  member, and a search of what was said in committee. **Who is heard:** witness
  appearances by kind (federal officials, oversight offices, business, unions,
  academics, civil society, individuals and more), compared across committees; each
  committee's main topics, measured with the House topics; and the members who spoke
  most.
- **Languages:** share of speech given in French, overall, by month, party and member,
  measured with one yardstick for both languages.
- **Topics:** 30 topics from TF-IDF and NMF, with each topic's share over time and
  within each party's own speeches.
- **What's new:** terms rising or fading in the last 60 days of sittings compared with the
  year before (log-odds ratio with an informative prior).
- **Accessible:** audited against WCAG 2.1 AA, keyboard-usable charts whose values are
  read out, and an accessibility statement at `/accessibility/`.
- **Bilingual interface** throughout, with House terminology, French dates and ordinals.
- **REST API** under `/api/v1/` with interactive OpenAPI docs.

How each number is computed, and its limits: **[docs/METHODS.md](docs/METHODS.md)**.
Accessibility (WCAG 2.1 AA audit, fixes and limits): **[docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md)**.
How the code is organised: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Stack

Python 3.12 · Django 5.2 LTS · PostgreSQL 16 (full-text search, generated columns) ·
scikit-learn · Django REST Framework + drf-spectacular · WhiteNoise · gunicorn ·
Docker Compose · pytest · Ruff · GitHub Actions

## Quick start

```bash
cp .env.example .env
docker compose up -d --build

# Load the 42nd to 45th Parliaments (about two hours; downloads are cached in
# data/raw unless you add --no-cache)
docker compose run --rm web python manage.py load_hansard --parliament 42 --session 1
docker compose run --rm web python manage.py load_hansard --parliament 43 --session 1
docker compose run --rm web python manage.py load_hansard --parliament 43 --session 2
docker compose run --rm web python manage.py load_hansard --parliament 44 --session 1
docker compose run --rm web python manage.py load_hansard --parliament 45 --session 1

# Committee transcripts for the same sessions (several hours for all 25 standing
# committees; HANSARD_COMMITTEES in .env chooses fewer, e.g. FINA,OGGO,ETHI)
docker compose run --rm web python manage.py load_committees

# Build the analysis (a few minutes)
docker compose run --rm web python manage.py build_topics
docker compose run --rm web python manage.py build_term_shifts

# Check the data
docker compose run --rm web python manage.py hansard_quality
```

Open http://localhost:8000/ (or http://localhost:8000/?lang=fr for French).

| Page | Address |
| ---- | ------- |
| Search | `/search/` |
| Members | `/members/`, `/members/<name>/` |
| Recorded votes | `/votes/`, `/votes/44-1/481/` |
| Bills | `/bills/`, `/bills/45-1/C-4/` |
| Committees | `/committees/`, `/committees/FINA/`, `/committees/FINA/44-1/100/` |
| Witnesses | `/committees/witnesses/`, `/committees/witnesses/<name>/` |
| Committee search | `/committees/search/` |
| Trends | `/trends/` |
| Topics | `/topics/` |
| What's new | `/new/` |
| Languages | `/language/` |
| Sittings | `/sittings/`, `/sittings/44-1/50/` |
| A speech | `/speeches/<House id>/` |
| API docs | `/api/docs/` |
| Health check | `/health/` |

`?lang=en|fr` sets the interface language (remembered in a cookie); `?text=en|fr` sets
which text is searched or shown first, so the French interface can search the English
record and the reverse.

## API

Read-only, anonymous, rate-limited (120 requests per minute by default, `API_RATE`),
paginated (`page`, `page_size` up to 200). Interactive docs at `/api/docs/`, OpenAPI
schema at `/api/schema/`.

| Endpoint | Returns |
| -------- | ------- |
| `GET /api/v1/sittings/` | Sittings, newest first; filters `parliament`, `session`, `date_from`, `date_to` |
| `GET /api/v1/sittings/44-1/50/` | One sitting with every intervention |
| `GET /api/v1/speeches/{house_id}/` | One speech, every paragraph in English and French with its floor language |
| `GET /api/v1/people/` | Speakers with latest party and riding |
| `GET /api/v1/people/{slug}/` | One member: speeches by kind and month, parties, ridings, roles, French share, main topics |
| `GET /api/v1/bills/` | Bills, most recently debated first; filters `parliament`, `session`, `q` |
| `GET /api/v1/bills/45-1/C-4/` | One bill: titles, stages in the House, recorded votes |
| `GET /api/v1/votes/` | Recorded votes, newest first; filters `parliament`, `session`, `result`, `member` |
| `GET /api/v1/votes/44-1/481/` | One vote with every member's vote, party and whether it differed from their party |
| `GET /api/v1/committees/` | Loaded committees with their meeting counts and dates |
| `GET /api/v1/committees/FINA/` | One committee: witness appearances by kind, main topics, members who spoke most; filter `session` |
| `GET /api/v1/committees/FINA/meetings/` | One committee's public meetings, newest first, with the witnesses; filters `parliament`, `session` |
| `GET /api/v1/committees/FINA/44-1/100/` | One meeting: every intervention with role, speaker and paragraphs in English and French |
| `GET /api/v1/witnesses/` | Witnesses, most recently heard first, with their kind; filters `q` (name, title or organisation), `committee`, `kind` |
| `GET /api/v1/witnesses/{slug}/` | One witness and every meeting where they gave evidence |
| `GET /api/v1/search/?q=…&text=en` | Paragraph search with highlighted snippets |
| `GET /api/v1/trends/?term=a&term=b` | Mentions per 1,000 paragraphs by month |
| `GET /api/v1/language/` | French share overall, by month, party and member |
| `GET /api/v1/topics/`, `/api/v1/topics/{n}/` | Topic model; one topic's shares over time and by party |
| `GET /api/v1/term-shifts/` | Latest rising and fading terms |

## Keeping it current

Both Docker stacks include a `scheduler` service that runs `refresh_data` Tuesday to
Saturday at 06:30, after the House publishes the previous day's Hansard. It catches up
when the computer was asleep or off at that time, retries hourly after a failure, and
reports its last run on `/health/` and in `docker compose logs scheduler`.

`refresh_data` loads new sittings, follows a new session or Parliament when the current
one ends, rebuilds term shifts and bill links when anything new arrived and refits
topics weekly. Run it
by hand at any time:

```bash
docker compose run --rm web python manage.py refresh_data
```

Recorded votes are stored as sittings load. A database loaded with version 1.4 or
earlier gets them once with `python manage.py load_divisions` (reads the cached XML in
`data/raw`, downloading what is missing; speeches are left untouched). Bill pages are
built with `python manage.py build_bills` (also run by `refresh_data`).

Committee meetings of the current session are loaded by `refresh_data` too. Committee
speeches get their topics when the topic model is fitted (`build_topics`, run weekly by
`refresh_data`). The first
load, for every session already in the database, is `python manage.py load_committees`;
it carries on from the last meeting loaded, so it can be stopped and restarted. Use
`--committee FINA --parliament 44 --session 1` to load one committee and session, and set
`HANSARD_COMMITTEES` in `.env` (comma-separated acronyms) to choose others. Meetings held
in camera have no transcript and are skipped.

## Production

```bash
cp .env.example .env    # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, POSTGRES_PASSWORD
docker compose -f docker-compose.prod.yml up -d --build
```

The production stack listens on `127.0.0.1:8010` for a reverse proxy, and can be served
under a sub-path (`DJANGO_SCRIPT_NAME`) next to other apps on the same server: see
**[deploy/DEPLOY.md](deploy/DEPLOY.md)**.

- gunicorn, `DEBUG` off; refuses to start with the development secret key.
- Hashed, compressed static files served by WhiteNoise.
- Security headers (`X-Frame-Options: DENY`, `nosniff`, same-origin referrer and opener
  policies); `DJANGO_HTTPS=1` adds secure cookies, HSTS and an HTTPS redirect.
- Shared file cache for analysis results and API rate limits; cache keys include the
  latest load time, so new data refreshes every figure.
- Non-root container with a health check on `/health/`, which also reports the last
  refresh and the newest backup.
- Nightly database backups with retention and a tested restore procedure; optional
  email alerts when the refresh or a backup fails (see deploy/DEPLOY.md).

## Development

```bash
docker compose run --rm web pytest -q            # 366 tests, against PostgreSQL
docker compose run --rm web ruff check .
docker compose run --rm web ruff format --check .
```

GitHub Actions runs the same checks on every push and pull request.

### Updating dependencies

`requirements.in` and `requirements-dev.in` list the version ranges the project accepts.
`requirements.txt` and `requirements-dev.txt` are generated from them with exact
versions and checksums, so every build installs the same packages. Dependabot proposes
updates weekly as pull requests, which CI tests before you merge. To regenerate by hand:

```bash
pip install pip-tools
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements.txt requirements.in
pip-compile --generate-hashes --strip-extras --allow-unsafe -o requirements-dev.txt requirements-dev.in
```

### Translations

Interface translations live in `locale/fr/LC_MESSAGES/`. After changing interface text:

```bash
docker compose run --rm web python manage.py makemessages -l fr
# translate the new entries in django.po, then
docker compose run --rm web python manage.py compilemessages
```

```
config/                 settings, URLs
debates/
  hansard_xml.py        fetch and inspect House XML
  parsing.py            XML -> records; English/French merge
  speakers.py           speaker labels
  loader.py             cache, store, backfill
  search.py             full-text search
  analysis.py           trends and language shares
  textmine.py           topics and term shifts
  api.py                REST API
  management/commands/  load_hansard, refresh_data, build_topics, ...
  tests/                pytest suite and invented fixtures
templates/, static/     pages, CSS, chart script
locale/fr/              French interface
docs/                   methods, architecture, screenshots
```

## Data source and terms

Debate text comes from the [House of Commons of Canada](https://www.ourcommons.ca/en/open-data)
and is reproduced under the
[Speaker's permission](https://www.ourcommons.ca/en/important-notices), which allows
reproduction provided it is accurate, is not presented as official, and is not for
commercial use. HansardLens is not an official publication of the House of Commons. Its
text is reproduced as published (whitespace normalized; recorded-vote name lists left
out of speech text).

This repository contains code only: Hansard files are downloaded at run time into
`data/` and are never committed. The test fixtures are invented text in the same XML
structure.

## Licence

Code: MIT (see [LICENSE](LICENSE)). Debate text: see above.
