# Changelog

## 1.13.0 – 2026-10-20 (branch `tailwind`)

- **New look on Tailwind CSS 4.3 and daisyUI 5.7.** A two-level header: a white top row
  with the maple leaf in the flag's red, the name and a tagline, a search box on every
  page, and the language and theme switches; below it the sections as tabs on a dark red
  band, in Poppins (served with the site, SIL Open Font License). Content sits in
  rounded cards: search results and filters, tables, charts, figures, bar charts,
  agendas, the side-by-side text of speeches and transcripts.
- **Home page:** a large search panel with an English/French switch, headline figures
  (sittings, speeches, recorded votes, people, committee meetings), an "Explore" grid
  describing each section, and the latest sittings.
- **Dark theme:** follows the system setting; the moon button switches and remembers
  the choice in the browser.
- **Phones and tablets:** below 1,200 px the sections fold into a "Menu" that opens
  and closes with the keyboard.
- **Accessibility:** every colour pair checked for WCAG 2.1 AA in both themes; the
  axe-core audit runs all 31 pages at two widths in both themes, with no failures.
- The built stylesheet is committed, so running and deploying need no Node.js; CI
  checks it matches its source. README screenshots retaken.

## 1.12.0 – 2026-10-20

- **French in committee:** each committee page shows the share of what was said in
  French, overall and for members, ministers and witnesses (by session); the Languages
  page compares committees, next to the House; member pages give the share of their
  committee speech in French. Measured as for the House: each paragraph by the length
  of its English text, using the floor language the transcript marks.
- **API:** `/api/v1/committees/{acronym}/` and `/api/v1/language/` include these figures.
- Migration 0013 adds the word count to committee paragraphs (it rewrites that table,
  so it takes a few minutes on a full database).

## 1.11.1 – 2026-10-19

- **Votes:** a division number printed twice in one sitting (42-1 No. 194 prints
  division 334 twice) no longer stops the load. The first list is kept, and a repeat
  with different names is recorded as an issue on the sitting.

## 1.11.0 – 2026-10-19

- **42nd Parliament (2015–2019):** the parser handles its sittings (checked on 11, from
  the first to the last, including recorded votes and bills); load with
  `load_hansard --parliament 42 --session 1`.
- **Statements, questions and answers:** the House types most members' statements and
  many Question Period exchanges "Debate" (in the 42nd Parliament, all of them). They
  are now recognised from the part of the sitting day: statements during Statements by
  Members; in Question Period, answers from speakers who answer as ministers or
  parliamentary secretaries and questions from everyone else. Member pages count them
  correctly; the House's own type is kept in `house_type`. Migration 0012 applies this
  to everything already loaded.
- **All 25 standing committees** are loaded by default (`HANSARD_COMMITTEES` chooses
  fewer). The House site answers "not found" for meetings held in camera as for numbers
  not yet used, so the committee loader searches 30 numbers ahead instead of 15.
- **Who is heard:** one row per committee with short column headings; a dash for none.
  Witness kinds cover hospital and health networks (civil society), airport
  authorities (business), associations of municipalities and a few more names seen in
  the other committees.
- **French** abbreviation for the CCF (FCC).

## 1.10.0 – 2026-10-19

- **Who is heard:** every committee witness appearance is given a kind (federal
  departments and agencies, officers of Parliament and oversight offices, other
  governments, Indigenous governments and organisations, businesses and industry
  associations, unions, universities and think tanks, civil society, international
  bodies, individuals) from the title and organisation printed with the name. Rules
  were written against all 2,214 distinct labels and checked on a fresh random sample.
  The committees page compares committees; each committee page shows its own mix, by
  session; the witness list filters by kind; each witness page shows it.
- **Topics in committee:** committee speeches by members, ministers and witnesses are
  scored with the House topic model each time it is fitted. Committee pages show their
  main topics next to each topic's share in the House, topic pages show their share in
  each committee, and meeting pages their main topics.
- **Members:** each committee page lists the members who spoke most; member pages
  compare words spoken in committee and in the House, and meetings chaired.
- **API:** `/api/v1/committees/{acronym}/` (who is heard, topics, members; `session`
  filter); witnesses carry their `kind` and can be filtered by it.
- **French** text for every new label; accessibility audit extended to 31 pages with no
  failures.
- **Docs:** methods note section 11 (who is heard, topics in committee, members in
  committee) and limits; README, architecture and case study.

## 1.9.0 – 2026-10-18

- **Committees:** the public meetings of the Standing Committees on Finance (FINA),
  Government Operations and Estimates (OGGO) and Access to Information, Privacy and
  Ethics (ETHI), in English and French, for every loaded session. Pages for each
  committee (meetings with the witnesses heard and the organisations heard most
  often), each meeting (witness list and side-by-side transcript with the language
  spoken), witnesses (searchable by name, title or organisation) and each witness, and
  a search of committee transcripts filtered by committee and by who spoke.
- **Members:** each member's page lists the committee meetings where they spoke.
- **Loading:** `load_committees` finds each meeting's evidence XML from its page on
  ourcommons.ca, skips meetings held in camera, and continues from the last meeting
  loaded; `refresh_data` loads new meetings of the current session.
  `HANSARD_COMMITTEES` chooses the committees.
- **API:** `/api/v1/committees/`, a committee's meetings, one meeting with its
  transcript, `/api/v1/witnesses/` and one witness.
- **French** interface text for every new page; accessibility checks (axe-core and the
  structural tests) extended to the committee pages, with no failures.
- **Docs:** methods note section 11 (committees), README, architecture and case study.

## 1.8.0 – 2026-10-18

- **Accessibility audit** against WCAG 2.1 AA: axe-core on every page type in English
  and French at desktop and phone widths, keyboard testing, reflow at 320 px and
  computed contrast. Report in `docs/ACCESSIBILITY.md`; `tools/a11y_audit.js` reruns it.
- **Fixes:** visible keyboard focus on the red header and on date fields; form field
  borders, chart lines and bars at 3:1 or more; placeholder contrast; a level-one
  heading and correct heading order on the search page; no autofocus on the home page;
  the Languages page applies its filter with a button; current sort marked for screen
  readers; the API documentation page has a language, main landmark and heading.
- **Charts:** keys explained in each chart's accessible name, values read out as the
  keyboard moves between months, Home and End keys, and Escape closes the tooltip.
- **Accessibility statement** at `/accessibility/` in English and French, linked from
  every page.
- **Tests:** structural accessibility checks (language, title, headings, landmarks,
  skip link, labels) on 17 pages in both languages.

## 1.7.1 – 2026-10-18

- **Topics:** courtesy around questions ("I thank my colleague for his speech; I
  wonder…") is left out of the topic model, so it no longer forms a topic of its own.
- **Docs:** figures for all three Parliaments (709 sittings, 840,469 paragraphs, 1,317
  recorded votes, 699 bills).

## 1.7.0 – 2026-10-18

- **43rd Parliament:** checked on 19 sittings across both sessions (December 2019 to
  June 2021): same XML structure, no alignment issues, every speaker matched. Load it
  with `load_hansard --parliament 43 --session 1` and `--session 2`.
- **Votes in 2020 sittings:** reduced-attendance sittings print "(The House divided on
  the motion:)" with the outcome announced afterwards; the result is now read from the
  Speaker's announcement, so a 23–23 tie decided by the casting vote is recorded
  correctly.
- **Bills moved under a generic heading** ("Main Estimates, 2021-22" for an
  appropriation bill) take their long title as title and are linked only to the debate
  where they are moved.
- **`load_hansard --no-cache`** loads without keeping the XML in `data/raw`.

## 1.6.1 – 2026-10-18

- **French dates:** short dates use the usual French abbreviations (juin, juill., déc.);
  June and July were both shortened to "jui".
- **Docs:** case study (`docs/CASE_STUDY.md`) and new screenshots of members, votes and
  bills in the README.

## 1.6.0 – 2026-10-18

- **Bills:** `build_bills` finds each bill debated in the House from the motions that
  move or introduce it ("moved that Bill C-37, An Act …, be read the second time"),
  with its number, long title (English and French) and short title (the debate
  heading). Debates under that heading are linked to the bill; shared headings such as
  "Criminal Code" go to the bill the debate names most. `refresh_data` reruns it after
  new sittings.
- **Bill pages:** `/bills/` (search by number or title, filter by session) and
  `/bills/45-1/C-4/`: titles, stages moved and completed in the House, recorded votes
  with their stage, debate days, who spoke most and speeches by party, with links to
  LEGISinfo for status and text.
- **Links:** speeches in a bill debate and votes on a bill link to the bill page.
- **API:** `GET /api/v1/bills/` and `GET /api/v1/bills/{parliament}-{session}/{code}/`.
- Methods note section 10; French translation of the new pages.

## 1.5.0 – 2026-10-18

- **Recorded votes:** divisions are read from Hansard as sittings load: number, the
  question (debate heading, qualifier such as *Opposition Motion—…*, and *Motion No. 3*
  or *the amendment*), result, and every member's yea, nay or paired vote.
- **Vote pages:** `/votes/` lists every division (filter by subject, session, result or
  member); `/votes/44-1/481/` shows the counts, a breakdown by party at the time of the
  vote, the members who voted differently from most of their party, every member's
  vote, and links to the debate and to the House of Commons page with the motion text.
- **Members and sittings:** member pages summarise their recorded votes with the latest
  ones; sitting pages list their votes.
- **Name matching:** printed names are matched to members by House id, then by surname
  and riding (ministers speak under a role id); unmatched names keep their label and
  are matched again after each load.
- **Existing databases:** `python manage.py load_divisions` adds votes to sittings loaded
  earlier, without changing speeches (`--no-cache` avoids storing the XML).
- **API:** `GET /api/v1/votes/` and `GET /api/v1/votes/{parliament}-{session}/{number}/`.
- Methods note section 9; French translation of the new pages.

## 1.4.0 – 2026-10-18

- **Member pages:** `/members/` lists everyone who has spoken, with party, riding,
  speech count and last appearance; filter by name or riding (accents optional), party
  and Parliament, and sort by name, speeches or most recent. Each member's page shows
  speeches by kind and by month, party and riding over time (floor crossings
  included), roles printed in Hansard, the share spoken in French, main topics next to
  the House average, and every speech, with a search limited to that member.
- **Links:** speaker names on speech pages, search results, topic examples and the
  Languages table lead to the member's page. Addresses are name-based
  (`/members/bernard-genereux/`) and survive reloads (migration 0007 adds the slug).
- **API:** `GET /api/v1/people/{slug}/` returns the member profile; the people list
  now includes `slug` and `url`.
- **Charts:** counts use whole-number gridlines.
- Interface fully translated into French; methods note section 8 explains the figures.

## 1.3.1 – 2026-10-18

- **Backups:** only one backup runs at a time (a lock in the backup folder; a lock left
  by a killed run is cleared after two hours), and each run writes its own temporary
  file. Previously a manual `--now` started alongside the service's catch-up run failed.
- **Dependabot:** major upgrades of Django (beyond the 5.2 LTS line), PostgreSQL and the
  Python base image, and other major versions, are no longer proposed; they are planned
  upgrades.
- **Docs:** the server health check sends `Host: localhost`, which the site accepts.

## 1.3.0 – 2026-10-18

- **Reproducible builds:** `requirements.in` / `requirements-dev.in` hold the accepted
  ranges; `requirements.txt` / `requirements-dev.txt` are generated by pip-compile with
  exact versions and checksums (tested on Python 3.12: all tests pass). Dependabot
  proposes weekly updates for Python packages, Docker images and GitHub Actions.
- **Nightly backups:** a `backup` service (same PostgreSQL 16 image as the database)
  dumps the database at 02:30, verifies each dump is readable, keeps the newest three,
  and catches up after downtime. Restore procedure documented and tested.
- **Alerts:** optional Healthchecks.io pings for the daily refresh (start, success,
  failure with the error) and the nightly backup; `/health/` reports the newest backup.

## 1.2.0 – 2026-10-18

- **New look:** Canadian red frame (header, links, buttons, the spoken-text marker) with
  an original maple leaf in the header and as the browser icon. Data marks stay neutral
  grey, since red is also a party colour. Text contrast meets WCAG AA (6.4:1 or more).
- **Phone navigation:** the header menu wraps instead of running off narrow screens.
- **Live site** linked from the README.

## 1.1.0 – 2026-10-18

- **Automatic refresh:** a `scheduler` service in both Docker stacks runs
  `refresh_data` Tuesday to Saturday at 06:30, catches up after the computer was asleep
  or off, retries hourly after a failure, and reports its last run on `/health/`.
- **Sub-path hosting:** `DJANGO_SCRIPT_NAME` serves the app under a prefix such as
  `/hansardlens/` behind a reverse proxy, with prefixed links, static files
  and cookie paths, and cookie names that cannot clash with another Django app.
- **Side-by-side deployment:** the production stack has its own project name and listens
  only on the server's loopback; `deploy/DEPLOY.md` and `deploy/nginx-hansardlens.conf`
  describe adding it next to an existing app.

## 1.0.0 – 2026-10-14

First release.

- **Ingestion:** House of Commons Hansard XML in English and French for the 44th
  Parliament, 1st session and the 45th Parliament, 1st session (540 sittings, about
  184,000 interventions and 640,000 paragraphs); English and French paired paragraph
  by paragraph; floor language, speakers, parties, ridings, agenda and time recorded;
  data-quality report.
- **Search:** paragraph-level full-text search in either language, accent-insensitive
  with stemming, web-style queries, filters and highlighted snippets; side-by-side
  English and French reading view.
- **Analysis:** term trends per 1,000 paragraphs; share of speech given in French by
  month, party and member; 30 NMF topics; rising and fading terms (log-odds with an
  informative prior).
- **Interface:** complete English and French interface, accessible SVG charts with
  table views.
- **API:** read-only REST API under `/api/v1/` with OpenAPI documentation.
- **Operations:** daily refresh command that follows new sessions and Parliaments;
  production Docker setup (gunicorn, WhiteNoise, security headers, non-root container,
  health check); 139 automated tests and CI.
