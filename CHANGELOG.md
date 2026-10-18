# Changelog

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
