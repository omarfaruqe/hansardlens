# HansardLens: case study

**A bilingual explorer of House of Commons of Canada debates.**
Live: http://103.99.176.180/hansardlens/ · Code: https://github.com/omarfaruqe/hansardlens

## Summary

The House of Commons publishes every sitting as Hansard, in English and French. The
record is complete and official, but it is published one sitting at a time, so it is
hard to search across years, to compare the two languages, or to see how a member
voted or how a bill moved through the House.

HansardLens loads that record every sitting day and turns it into a searchable,
bilingual website and open API: full-text search in either language, a side-by-side
reading view that shows which language was actually spoken, member pages, recorded
votes, bill pages, and descriptive analysis (term trends, the share of debate held in
French, topics, rising and fading terms). Every figure is a share with a stated
denominator; the site describes what was said and does not rate parties or members.

| | |
| --- | --- |
| Data | 540 sittings (44th and 45th Parliaments), about 184,000 interventions and 640,000 paragraphs, each in English and French; 1,106 recorded votes with 356,327 individual votes |
| Stack | Python 3.12, Django 5.2 LTS, PostgreSQL 16, scikit-learn, Django REST Framework, Docker Compose, Caddy, GitHub Actions |
| Quality | 238 automated tests on PostgreSQL in CI; data-quality report; checks against real sittings |
| Operations | Daily automatic refresh, nightly verified backups, failure alerts, pinned and hashed dependencies, weekly update proposals |
| Interface | Complete English and French interface; WCAG AA text contrast; charts with table views |

## The problem

- **Users:** people who follow Parliament closely: journalists, researchers, students,
  public servants, and people preparing for roles that work with the House.
- **Needs:** find what was said about a subject, by whom and when, in either official
  language; read a speech in both languages and know which one was spoken; see how a
  member voted and how a bill progressed; get the same data as an API.
- **Constraints:** the House permits reproduction of Hansard if it is accurate, is not
  presented as official and is not commercial. The site therefore stores the text as
  published, labels itself as unofficial, and links to the House and LEGISinfo for the
  official record and bill status.

## Data and what it took to trust it

- **Source:** one XML file per sitting and language from ourcommons.ca. Before writing
  a parser, the structure was established from real files with an inspection command,
  and every rule below is covered by tests on invented files with the same structure
  (real Hansard text is never committed).
- **Aligning the languages:** the two files of a sitting share paragraph ids, so they
  are paired by position when every id matches and by id otherwise, with any mismatch
  recorded. Across 540 sittings, one sitting has a mismatch (one speech split
  differently in French); no paragraph lost its translation.
- **Who spoke:** speaker labels are full only on a member's first intervention of the
  day. Within a sitting, the House's speaker id carries party and riding to the short
  labels; across sittings, people are matched by name, because House ids belong to a
  role (a minister speaks under a different id than as a member).
- **Language actually spoken:** Hansard marks passages as spoken in English or French;
  the marker applies until the next one, across speeches. Each paragraph stores it.
- **Recorded votes:** vote lists print surnames only ("Falk (Provencher)"). Each name
  carries the member id, which matches 98.75% of the 356,327 votes through speeches or
  by surname and riding; the rest keep their printed label and are retried after each
  load.
- **Data-quality report:** a command reports coverage, alignment issues, missing
  parties and unknown intervention types, so problems are visible rather than hidden.

## How it was delivered

Built in iterative releases, each one tested, documented in the changelog, committed
and deployed before the next began.

| Release | Delivered |
| --- | --- |
| 1.0 | Ingestion and data quality; bilingual search and reading view; trends, language shares, topics and term shifts; English and French interface; REST API; production Docker setup; CI |
| 1.1 | Automatic daily refresh with catch-up and retry; hosting under a sub-path next to another application on the same server |
| 1.2 | Canadian red visual identity with an original maple leaf; neutral data colours; phone navigation |
| 1.3 | Pinned, hashed dependencies; nightly verified backups with retention; failure alerts |
| 1.4 | Member pages: activity, roles over time, language spoken, main topics |
| 1.5 | Recorded votes: parsing, member matching, party lines, vote pages and API |
| 1.6 | Bill pages: stages in the House, votes, debates and speakers, linked to LEGISinfo |

## Decisions and trade-offs

- **Describe, never rate.** Counts of speeches reflect role and party size, not work
  done, and every page says so. Data marks are neutral grey because red, the site's
  Canadian frame colour, is also a party colour.
- **One yardstick for both languages.** French usually takes more words than English
  to say the same thing, so comparing raw word counts would overstate French. Every
  paragraph is measured by the length of its English text, whichever language was
  spoken.
- **Paragraphs as the unit for trends.** A phrase or an `OR` query then counts the same
  way as a single word, and months with too little debate are shown as gaps rather
  than extreme values.
- **Votes from Hansard itself.** The vote lists are already in the files the site
  loads, so votes need no second data source; the House's own vote page is linked for
  the motion text. The cost is name matching, handled with ids first and surname and
  riding second, with unmatched names kept rather than guessed.
- **Bills found from the motions that move them.** "Moved that Bill C-37, An Act …, be
  read the second time" gives the number and long title in both languages; the debate
  heading gives the short title. Shared headings ("Criminal Code") go to the bill a
  debate names most, and stay unlinked when that is unclear.
- **Stable addresses.** Speeches use the House's own ids, sittings their numbers,
  members a slug made once from the name, so links survive reloads.
- **Run next to an existing application.** The server already hosted another Django
  application. HansardLens runs as a separate Docker project on a loopback port, behind
  the existing Caddy gateway, under its own path and cookie names; the other
  application was not touched.
- **Boring, recoverable operations.** Dependencies are pinned with checksums; major
  upgrades (PostgreSQL, Django beyond the 5.2 LTS line) are planned by hand rather than
  merged from automated pull requests; backups are verified as readable when written.

## Quality

- **Tests:** 238 tests with pytest against PostgreSQL, run in GitHub Actions with
  linting, formatting and migration checks. They cover the parser, alignment, speaker
  parsing, ingestion against a fake House website (missing sittings, network failures,
  new sessions and Parliaments), search, analysis, topics on a synthetic corpus, votes,
  bills, the API, both interface languages and hosting under a sub-path.
- **Real data:** tests also run against real sittings when they have been downloaded.
- **Accessibility:** text contrast of 6.4:1 or more, skip link, keyboard-usable charts
  with table equivalents, `lang` attributes on every passage, layouts checked at phone
  width.

## Operations

- A scheduler service refreshes the data Tuesday to Saturday at 06:30, after the House
  publishes the previous day's Hansard; it catches up after downtime and retries hourly.
- A backup service writes a compressed, verified database dump every night and keeps
  the newest three; only one backup can run at a time.
- Optional Healthchecks.io alerts report failed refreshes or backups by email.
- `/health/` reports the database, version, last refresh and newest backup.

## Limits and next steps

- Three Parliaments are loaded, from December 2019; earlier ones are not yet checked.
- English and French are translations of each other, so a trend in French text partly
  reflects translators' choices.
- Topics are a statistical model and change somewhat with its settings.
- Next: an accessibility audit against WCAG 2.1 AA, earlier Parliaments, and committee
  evidence.

## Skills shown

| Area | Evidence in this project |
| --- | --- |
| Requirements and scope | Users, needs and licence constraints set before building; scope delivered in releases with a changelog |
| Data engineering | XML ingestion with caching and retries, bilingual alignment, idempotent loads, data-quality reporting |
| Databases | PostgreSQL full-text search configurations, generated columns, GIN indexes, migrations with data backfills |
| Analysis and machine learning | Rates with stated denominators, TF-IDF and NMF topics, log-odds term shifts, methods note with limits |
| Official languages | Complete French interface, French data side by side, language actually spoken recorded |
| Accessibility | Contrast, keyboard use, table equivalents for charts, phone layouts |
| Security and operations | Production settings, non-root containers, pinned dependencies, backups, alerts, health checks, side-by-side deployment |
| Testing and documentation | 238 tests in CI; README, architecture, methods note, deployment runbook |
