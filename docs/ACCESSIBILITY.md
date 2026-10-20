# HansardLens accessibility report

- **Standard:** WCAG 2.1, levels A and AA (the level required of Government of Canada
  websites by the Standard on Web Accessibility).
- **Reviewed:** 18 October 2026, version 1.8.0; committee pages added and checked in
  version 1.9.0; rebuilt on Tailwind CSS and daisyUI with a dark theme, and every page
  checked again in both themes, in version 1.13.0 (20 October 2026).
- **Scope:** every type of page, in English and French, at desktop (1280 px) and phone
  (375 px) widths: home, search and results, sittings, a sitting, a speech, members, a
  member, recorded votes, a vote, bills, a bill, committees, a committee, a meeting,
  witnesses, a witness, committee search, trends, languages, topics, a topic, what's new, the accessibility statement, the API documentation and the error page.
- **Statement for users:** `/accessibility/` on the site (English and French).

## Method

| Check | How |
| ----- | --- |
| Automated rules | axe-core 4.10.2 in Chromium, WCAG 2.0/2.1 A and AA rules and best practices, 31 pages × 2 widths × light and dark themes (`tools/a11y_audit.js`) |
| Structure on every release | `debates/tests/test_accessibility.py`: page language, title, one level-one heading, main landmark, skip link first, labelled form fields, text alternatives, language of parts; 23 pages × 2 languages |
| Keyboard | Tabbing through every page type: order, visible focus, no traps; chart keys |
| Reflow | Every page at 320 CSS px: no horizontal scrolling outside data tables |
| Contrast | Computed for every text and component colour pair in the style sheet, in both themes (dark: body text 15.2:1, secondary text 7.7:1, links 8.1:1, field borders 4.7:1, chart lines 6.4:1 to 8.3:1) |
| Screen readers | Not yet tested by a person with a screen reader (see Limitations) |

## Findings and fixes

| # | Finding | WCAG | Fix |
| - | ------- | ---- | --- |
| 1 | Search page had no level-one heading | 1.3.1, 2.4.6 | Visually hidden `h1` ("Search the debates") |
| 2 | Search filters were a complementary landmark (`aside`) inside the main landmark | 1.3.1 | Now a labelled section |
| 3 | Search results sidebar jumped from `h1` to `h3` | 1.3.1 | Now an `h2` with the same look |
| 4 | API documentation page had no language, main landmark or heading | 3.1.1, 1.3.1, 2.4.1 | Own template for the Swagger UI page: `lang="en"`, main landmark, heading, links back |
| 5 | Keyboard focus on header links was red on the red header (invisible) | 2.4.7 | White focus outline in the header |
| 6 | Focus was not visible on date fields in Chrome | 2.4.7 | Focus outline on every form field, not only `:focus-visible` |
| 7 | Form field borders had a 1.4:1 contrast | 1.4.11 | Borders at 3.3:1 |
| 8 | Two chart line colours (green 2.8:1, gold 2.2:1) and the "used less" bars (2.3:1) were below 3:1 | 1.4.11 | Darker green, gold and orange (4.1:1 to 4.6:1), bars 3.9:1 |
| 9 | Placeholder text used the browser's light grey | 1.4.3 | Placeholder in the muted text colour (6.1:1) |
| 10 | The home page put the cursor in the search box on load, skipping the skip link and navigation for keyboard and screen-reader users | 2.4.3 | No autofocus |
| 11 | Chart values were shown only in a visual tooltip; arrow keys worked but nothing was announced; the tooltip could not be dismissed with the keyboard | 1.3.1, 4.1.3, 1.4.13 | Keys explained in the chart's accessible name; values read out through a live region; Home and End keys; Escape closes the tooltip from the keyboard or after hovering |
| 12 | The current sort order was shown only in bold | 1.3.1 | `aria-current` on the current sort |
| 13 | Changing the Parliament list on the Languages page reloaded the page at once | 3.2.2 | A "Show" button applies the choice, as on the other pages |

After the fixes, axe-core reports no failures on any page at either width, in either
theme. The theme switch is a button with a constant name ("Dark theme") whose pressed
state says which theme is on; without JavaScript it is hidden and the site follows the
system setting. On phones the navigation folds into a "Menu" disclosure that opens and
closes with the keyboard. The
committee pages added in version 1.9.0 use the same components and also report none. It flags
the small axis numbers in charts for review because it cannot read the SVG background;
they are dark grey on white, 6.1:1.

## WCAG 2.1 A and AA criteria

| Criterion | Result | Notes |
| --------- | ------ | ----- |
| 1.1.1 Non-text content | Meets | Logo leaf decorative (`aria-hidden`); charts have names and tables with the same figures |
| 1.2.x Time-based media | Not applicable | No audio or video |
| 1.3.1 Info and relationships | Meets | Headings, landmarks, lists, table headers, labelled fields and groups |
| 1.3.2 Meaningful sequence | Meets | Reading order follows the layout; search results come before filters on phones in both reading and visual order |
| 1.3.3 Sensory characteristics | Meets | No instructions rely on shape, place or colour |
| 1.3.4 Orientation | Meets | Works in portrait and landscape |
| 1.3.5 Identify input purpose | Not applicable | No fields collect personal information |
| 1.4.1 Use of colour | Meets | Results, votes, parties and the spoken language are written out; links are underlined |
| 1.4.2 Audio control | Not applicable | |
| 1.4.3 Contrast (minimum) | Meets | Text at least 5.7:1 |
| 1.4.4 Resize text | Meets | Text in relative units; usable at 200% |
| 1.4.5 Images of text | Meets | None |
| 1.4.10 Reflow | Meets | 320 px without horizontal scrolling, except data tables, which scroll within themselves (allowed for two-dimensional content) |
| 1.4.11 Non-text contrast | Meets | Field borders, focus outlines, chart lines and bars at least 3:1 |
| 1.4.12 Text spacing | Meets | No fixed heights on text containers |
| 1.4.13 Content on hover or focus | Meets | Chart tooltip stays while hovered, closes with Escape |
| 2.1.1 Keyboard | Meets | Every control and chart usable from the keyboard |
| 2.1.2 No keyboard trap | Meets | |
| 2.1.4 Character key shortcuts | Not applicable | Chart keys only act while the chart has focus |
| 2.2.x Timing | Not applicable | No time limits or moving content |
| 2.3.1 Three flashes | Meets | Nothing flashes |
| 2.4.1 Bypass blocks | Meets | "Skip to content" link first on every page |
| 2.4.2 Page titled | Meets | Each page has its own title |
| 2.4.3 Focus order | Meets | Follows the reading order |
| 2.4.4 Link purpose | Meets | Link text, or link text with its row or heading |
| 2.4.5 Multiple ways | Meets | Navigation, search and lists of sittings, members, votes and bills |
| 2.4.6 Headings and labels | Meets | |
| 2.4.7 Focus visible | Meets | 3 px outline, red on the page and white on the header |
| 2.5.1–2.5.4 Pointer, labels, motion | Meets | No path gestures or motion; visible labels are part of accessible names |
| 3.1.1 Language of page | Meets | `lang` follows the interface language |
| 3.1.2 Language of parts | Meets | Every passage of debate, title and the language switcher carry their own `lang` |
| 3.2.1–3.2.4 Predictable | Meets | Nothing changes on focus or input; filters apply with a button; navigation is the same on every page |
| 3.3.1–3.3.4 Input assistance | Meets | Search errors are described in text; no forms with legal or financial effect |
| 4.1.1 Parsing | Meets | (Obsolete in WCAG 2.2) |
| 4.1.2 Name, role, value | Meets | Native controls; charts named |
| 4.1.3 Status messages | Meets | Result counts and chart values are announced politely |

## Limitations

- **Screen readers:** the site follows the markup that screen readers rely on, but it
  has not yet been tested by a person using NVDA, JAWS or VoiceOver. That is the next
  step, and the most important one.
- **API documentation:** the interactive page is Swagger UI, a third-party interface
  in English only with known accessibility issues; the same endpoints are documented
  in the README.
- **Source text:** debate text is reproduced from Hansard as published, including
  abbreviations and the House's headings. Party abbreviations are not expanded.

## Re-running the audit

```bash
docker compose up -d
npm install --no-save playwright@1.48 axe-core@4.10.2 && npx playwright install chromium
node tools/a11y_audit.js http://localhost:8000
```

The structural tests run with the rest of the test suite on every push.
