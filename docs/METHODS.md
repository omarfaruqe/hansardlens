# HansardLens methods note

This note explains how HansardLens turns the House of Commons record into searchable
text and descriptive figures, what each number means, and where the method has limits.
Every figure on the site is a share with a stated denominator; none is a judgment about
a party or a member.

## 1. Source

- **Data:** the official Hansard (Debates) of the House of Commons of Canada, published as
  XML on ourcommons.ca, one file per sitting and language:
  `https://www.ourcommons.ca/Content/House/{parliament}{session}/Debates/{nnn}/HAN{nnn}-{E|F}.XML`.
- **Coverage in v1.0.0:** the 44th Parliament, 1st session (November 2021 to
  December 2024, 391 sittings) and the 45th Parliament, 1st session (from May 2025),
  updated daily.
- **Terms:** reproduced under the Speaker's permission, which allows reproduction
  provided it is accurate, is not presented as official, and is not for commercial use.
  Text is stored as published, with whitespace normalized and recorded-vote name lists
  left out of speech text.

## 2. From XML to records

The structure was established from real files before any parser was written
(`inspect_sitting`), and is checked again by tests on downloaded sittings.

| Element | Becomes |
| ------- | ------- |
| `ExtractedInformation` (date, numbers, Speaker) | `Sitting` |
| `OrderOfBusiness[@Rubric]`, `SubjectOfBusiness` | agenda section and subject of each intervention |
| `Intervention[@Type,@id]` with `PersonSpeaking/Affiliation` | `Intervention` |
| `ParaText`, `ProceduralText` | `Paragraph` (speech or procedural) |
| `FloorLanguage`, `Timestamp` | floor language and time, carried forward in document order |
| `Division` | skipped (vote lists) |

**Aligning English and French.** The two files of a sitting use the same House ids in
the same order for interventions and paragraphs. HansardLens pairs them by position
when every id matches (the normal case) and by id otherwise; any mismatch is recorded on
the sitting. Across 540 sittings, one sitting (44-1 No. 285) has a mismatch: one
speech whose French version splits four paragraphs that English keeps whole. Every
English paragraph there still has its French text. The intervention type is taken from
the English file, because the French file sometimes types the same intervention
differently.

**Floor language.** `[English]`, `[Translation]` (French spoken) and `[Text]` (written
answers) markers act as switches: each applies to every following paragraph, across
interventions, until the next marker. Each paragraph therefore records the language in
which it was actually said.

**Speakers.** Labels are full on a member's first intervention of the day
(`Mr. Marc Dalton (Pitt Meadows—Maple Ridge, CPC)`) and short afterwards
(`Mr. Marc Dalton`). Within a sitting, the House speaker id links the two, so party
and riding are carried forward. House ids belong to a *role* (one person can have one id
as a member and another as parliamentary secretary), so people are matched across
sittings by name without honorific. Chair occupants are recorded with their role
(`The Assistant Deputy Speaker`) and, where given, their name. Where a member appears
only in short form in a sitting, the party from the nearest sitting with a full label is
used (0.1% of member interventions remain without a party).

## 3. Search

- Paragraph-level full-text search in PostgreSQL, separately on the English and the
  French text.
- Two text-search configurations, `en_unaccent` and `fr_unaccent`, apply `unaccent`
  before the language's Snowball stemmer: `economie` finds *économie*, `bridges` finds
  *bridge*.
- Search vectors are generated columns with GIN indexes, so they are always current.
- Queries use web-search syntax (`"phrase"`, `OR`, `-exclude`); results are ranked with
  `ts_rank` or sorted by date. Only speech paragraphs are searched.

## 4. Term trends

For each calendar month *m* and term *t*:

```
rate(t, m) = 1,000 × (speech paragraphs in m matching t) / (all speech paragraphs in m)
```

- The unit is the paragraph, so a phrase or an `OR` query counts the same way as a
  single word, and a paragraph counts once however often it repeats the term.
- A party filter restricts numerator and denominator to that party's speeches.
- Chair occupants and procedural text are excluded.
- Months without sittings are gaps, not zeros. Months with fewer than 100 speech
  paragraphs are also gaps, because one short sitting (an adjournment after a death, for
  example) would produce extreme rates.

## 5. Language on the floor

```
French share = Σ words_en(paragraphs spoken in French) / Σ words_en(paragraphs spoken in English or French)
```

`words_en` is the length of each paragraph's **English** text, whichever language was
spoken. French typically needs more words than English for the same content, so
comparing French word counts with English word counts would overstate French. Using
one yardstick for both languages removes that bias. Written answers, chair occupants and
procedural text are excluded; months under 5,000 words are gaps; parties need at least
20,000 words and members 10,000 to be listed.

## 6. Topics

- **Documents:** member speeches (debate, questions, answers, statements; not chair
  occupants, procedural text or interjections) of at least 60 words.
- **Features:** TF-IDF over unigrams and bigrams with sublinear term frequency;
  terms in fewer than 20 speeches or more than 40% of speeches are dropped; at most
  20,000 terms.
- **Stop words:** standard English (or French) function words, parliamentary
  boilerplate (*Mr. Speaker*, *hon. member*, *motion*), common verbs, month names and
  **party names**. Party names are removed so that topics group speeches by subject
  rather than by who is being addressed or criticized.
- **Model:** non-negative matrix factorization (scikit-learn `NMF`, `nndsvda`
  initialization, fixed random seed), 30 topics by default.
- **Assignment:** each speech is counted under its strongest topic; its weight is that
  topic's share of the speech's topic weights.
- **Shown:** each topic's words with weights relative to the strongest; its share of
  each month's speeches; the share of *each party's own* speeches on it (so large and
  small parties compare fairly; parties under 200 speeches are hidden); the speeches
  most clearly about it.
- **Names** are the strongest words unless an editor sets a title in the admin. Topics are
  found by the method, not chosen in advance, and refitting can change their numbering.

## 7. What's new (term shifts)

Recent window: the last 60 days of sittings. Baseline: the 365 days before it. Terms
(unigrams and bigrams, same stop words) are scored with the log-odds ratio with an
informative Dirichlet prior (Monroe, Colaresi and Quinn, 2008, *Political Analysis* 16:4):

```
δ_w = log[(y_w^r + α_w) / (n^r + α_0 − y_w^r − α_w)] − log[(y_w^b + α_w) / (n^b + α_0 − y_w^b − α_w)]
σ²(δ_w) ≈ 1/(y_w^r + α_w) + 1/(y_w^b + α_w)
z_w = δ_w / σ(δ_w)
```

where *y* are term counts and *n* total counts in the recent (*r*) and baseline (*b*)
windows, and the prior α is the combined frequency of each term scaled to 10% of all
tokens. The prior shrinks rare terms, so they do not reach the top by chance. Listed
terms need at least 25 occurrences in the window where they are more common. A single
word is dropped when a listed phrase containing it accounts for at least 80% of its
uses. Each term is shown with its rate per 10,000 words in both windows.

## 8. Members

- **Who is listed:** every person who has spoken, matched across sittings by name
  without honorific (section 2). People who have presided over the House are marked.
- **Speeches:** a member's own interventions of type debate, question, answer or
  members' statement. Interjections, procedural text and anything said while presiding
  are not counted.
- **Party, riding and roles over time:** each value printed with the member's label,
  with the first and last sitting it appears on. Roles (minister, parliamentary
  secretary, presiding officer) are the titles printed in the English labels.
- **Speeches by month:** counts, from the member's first speech to the latest sitting.
  Months without sittings are gaps; months with sittings but no speech are zero.
- **Spoken in French:** the measure of section 5 restricted to the member's paragraphs,
  shown from 1,000 words.
- **Main topics:** the share of the member's analysed speeches (section 6) whose main
  topic is each topic, next to that topic's share of all speeches. Shown from 10
  analysed speeches.
- **Reading the counts:** time on the floor depends on role (ministers answer
  questions, the government House leader moves business), party size and the business
  of the day. The pages describe what was said, not how much work a member does.
- **Addresses:** `/members/<slug>/`, where the slug is made once from the name
  (`Bernard Généreux` → `bernard-genereux`) and kept on reloads.

## 9. Limits

- **Coverage:** two sessions; earlier Parliaments use the same XML structure, but have not
  been loaded or checked.
- **Translation:** English and French are translations of each other, not independent
  corpora. A term trend in French text partly reflects translators' choices.
- **Counting is not meaning:** a rising term means a subject took more of the
  conversation, not that anyone's position changed. Mentions include criticism,
  support and passing references alike.
- **Parties:** a member's party is the one printed with their label at the time; floor
  crossings are reflected from the next full label. Party shares reflect seat counts and
  where members were elected.
- **Topics are a model:** a different seed, number of topics or stop-word list gives
  somewhat different topics. They are an aid to exploring, not a classification of record.
- **Interjections** ("Some hon. members: Agreed") are kept as interventions but excluded
  from topics and term shifts.
