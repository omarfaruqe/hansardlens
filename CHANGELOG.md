# Changelog

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
