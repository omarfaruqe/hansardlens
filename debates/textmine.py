"""Explainable text mining: NMF topics and log-odds term shifts.

Documents are member speeches (questions, answers, statements and debate; not chair
occupants, procedural text or short interjections). Both methods run on a normal CPU.

Stop words: the usual function words plus parliamentary boilerplate ("Mr. Speaker",
"hon. member") and party names. Party names are removed so topics group speeches by
subject rather than by who is being criticized.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
from django.db import transaction
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer, TfidfVectorizer

from .models import Intervention, InterventionTopic, TermShift, Topic, TopicModel

SPEECH_KINDS = [
    Intervention.Kind.DEBATE,
    Intervention.Kind.QUESTION,
    Intervention.Kind.QUESTION_SUPPLEMENTAL,
    Intervention.Kind.QUESTION_COMMENT,
    Intervention.Kind.ANSWER,
    Intervention.Kind.ANSWER_SUPPLEMENTAL,
    Intervention.Kind.STATEMENT,
]

PARLIAMENTARY_EN = """
speaker madam mr mrs ms hon honourable member members colleague colleagues house chamber
minister ministers government parliament parliamentary bill bills motion motions question
questions answer today time year years day week month know think want going said say says
saying like just really make made way thing things lot need needs let look talk talking
point canadians canada canadian country people right sure actually good important new
agree indeed course certainly order unanimous consent standing committee report
liberal liberals conservative conservatives ndp bloc québécois quebecois green party
parties leader opposition prime riding constituents thank thanks deputy chair presiding
did does doing got get gets getting come comes came coming went goes put puts paid pay
tell told ask asked asking heard hear able clear fact far little long ago yes
january february march april may june july august september october november december
""".split()

FRENCH_STOP = """
au aux avec ce ces dans de des du elle en et eux il ils je la le les leur lui ma mais me
même mes moi mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te
tes toi ton tu un une vos votre vous c d j l à m n s t y été être avoir ai as avons avez
ont avait était sont est cette cet ceux celle celles celui ça cela ici là plus moins très
aussi bien alors donc car comme si tout tous toute toutes autre autres fait faire peut
doit dit dire faut entre sans sous chez depuis encore déjà jamais toujours quand où
dont lorsque puis ainsi après avant leurs nos quel quelle quels quelles chaque
""".split()

PARLIAMENTARY_FR = """
président présidente monsieur madame député députés députée députées honorable collègue
collègues chambre ministre ministres gouvernement parlement projet loi motion question
questions réponse aujourd hui année années jour semaine mois sais pense veux veut
canadiens canadiennes canada canadien canadienne pays gens accord ordre consentement
comité rapport libéral libéraux libéraux conservateur conservateurs npd bloc québécois
vert parti partis chef opposition premier circonscription merci vice
janvier février mars avril mai juin juillet août septembre octobre novembre décembre
fois chose choses façon oui non
""".split()

STOP_WORDS = {
    "en": sorted(set(ENGLISH_STOP_WORDS) | set(PARLIAMENTARY_EN)),
    "fr": sorted(set(FRENCH_STOP) | set(PARLIAMENTARY_FR)),
}
TOKEN_PATTERN = r"(?u)\b[^\W\d_][\w'’-]*[^\W\d_]\b"  # words of 2+ letters, no numbers


def documents(
    lang: str = "en",
    min_words: int = 60,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> Iterator[tuple[int, str, dt.date, int]]:
    """Yield (intervention id, text, sitting date, word count) for member speeches."""
    qs = Intervention.objects.filter(kind__in=SPEECH_KINDS, is_chair=False).filter(
        **{f"word_count_{lang}__gte": min_words}
    )
    if date_from:
        qs = qs.filter(sitting__date__gte=date_from)
    if date_to:
        qs = qs.filter(sitting__date__lte=date_to)
    rows = qs.order_by("id").values_list(
        "id", f"text_{lang}", "sitting__date", f"word_count_{lang}"
    )
    yield from rows.iterator(chunk_size=2000)


# ------------------------------------------------------------------------------------
# Topics
# ------------------------------------------------------------------------------------


@dataclass
class TopicParams:
    lang: str = "en"
    n_topics: int = 30
    min_df: int = 20
    max_df: float = 0.4
    max_features: int = 20_000
    min_words: int = 60
    top_terms: int = 15
    random_state: int = 0


def fit_topics(p: TopicParams, log=print) -> TopicModel:
    from sklearn.decomposition import NMF

    ids, texts, dates = [], [], []
    for pk, text, date, _ in documents(p.lang, p.min_words):
        ids.append(pk)
        texts.append(text)
        dates.append(date)
    if len(ids) < p.n_topics * 2:
        raise ValueError(f"Only {len(ids)} speeches: too few for {p.n_topics} topics")
    log(f"{len(ids):,} speeches; building TF-IDF")

    vectorizer = TfidfVectorizer(
        stop_words=STOP_WORDS[p.lang],
        token_pattern=TOKEN_PATTERN,
        lowercase=True,
        strip_accents=None,
        min_df=p.min_df,
        max_df=p.max_df,
        max_features=p.max_features,
        ngram_range=(1, 2),
        sublinear_tf=True,
        dtype=np.float32,
    )
    X = vectorizer.fit_transform(texts)
    del texts
    vocab = vectorizer.get_feature_names_out()
    log(f"TF-IDF matrix {X.shape[0]:,} x {X.shape[1]:,}; fitting NMF with {p.n_topics} topics")

    nmf = NMF(
        n_components=p.n_topics,
        init="nndsvda",
        random_state=p.random_state,
        max_iter=400,
        tol=1e-4,
    )
    W = nmf.fit_transform(X)
    H = nmf.components_
    log(f"NMF converged in {nmf.n_iter_} iterations; storing results")

    totals = W.sum(axis=1)
    main = W.argmax(axis=1)
    counts = np.bincount(main[totals > 0], minlength=p.n_topics)
    assigned = int((totals > 0).sum())

    with transaction.atomic():
        model = TopicModel.objects.create(
            lang=p.lang,
            n_topics=p.n_topics,
            n_documents=assigned,
            vocabulary_size=len(vocab),
            first_date=min(dates),
            last_date=max(dates),
            params={**p.__dict__, "nmf_iterations": int(nmf.n_iter_)},
        )
        topics = []
        for k in range(p.n_topics):
            order = np.argsort(H[k])[::-1][: p.top_terms]
            peak = float(H[k][order[0]]) or 1.0
            topics.append(
                Topic(
                    model=model,
                    number=k + 1,
                    terms=[[str(vocab[j]), round(float(H[k][j]) / peak, 3)] for j in order],
                    share=round(counts[k] / assigned, 4) if assigned else 0,
                )
            )
        Topic.objects.bulk_create(topics)
        topics = list(model.topics.order_by("number"))
        rows = [
            InterventionTopic(
                topic=topics[int(main[i])],
                intervention_id=ids[i],
                weight=round(float(W[i, main[i]] / totals[i]), 4),
            )
            for i in range(len(ids))
            if totals[i] > 0
        ]
        InterventionTopic.objects.bulk_create(rows, batch_size=5000)
        old = TopicModel.objects.filter(lang=p.lang).exclude(pk=model.pk)
        old.delete()  # cascades to their topics and assignments
        model.is_active = True
        model.save(update_fields=["is_active"])
    return model


def active_model(lang: str = "en") -> TopicModel | None:
    return TopicModel.objects.filter(lang=lang, is_active=True).first()


# ------------------------------------------------------------------------------------
# Term shifts: log-odds ratio with an informative Dirichlet prior
# (Monroe, Colaresi & Quinn 2008, "Fightin' Words")
# ------------------------------------------------------------------------------------


def log_odds_z(y_a: np.ndarray, y_b: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """z-scores of the log-odds ratio of each term between corpora a and b.

    y_a, y_b: term counts in each corpus; prior: pseudo-counts per term (same shape).
    Positive z = relatively more frequent in a.
    """
    n_a, n_b, a0 = y_a.sum(), y_b.sum(), prior.sum()
    delta = np.log((y_a + prior) / (n_a + a0 - y_a - prior)) - np.log(
        (y_b + prior) / (n_b + a0 - y_b - prior)
    )
    variance = 1.0 / (y_a + prior) + 1.0 / (y_b + prior)
    return delta / np.sqrt(variance)


def _dedupe(indices: list[int], vocab, counts: np.ndarray, overlap: float = 0.8) -> list[int]:
    """Drop a single word when a listed phrase containing it accounts for most of its
    uses ("drinking" next to "drinking water"). Order is kept."""
    phrases = [j for j in indices if " " in vocab[j]]
    keep = []
    for j in indices:
        term = vocab[j]
        if " " not in term and any(
            term in vocab[k].split() and counts[k] >= overlap * counts[j] for k in phrases
        ):
            continue
        keep.append(j)
    return keep


@dataclass
class ShiftParams:
    lang: str = "en"
    recent_days: int = 60
    base_days: int = 365
    min_count: int = 25
    top: int = 30
    min_words: int = 20
    prior_strength: float = 0.1  # prior pseudo-counts = this share of all tokens


def compute_shifts(p: ShiftParams, end: dt.date, log=print) -> TermShift:
    recent_start = end - dt.timedelta(days=p.recent_days - 1)
    base_end = recent_start - dt.timedelta(days=1)
    base_start = base_end - dt.timedelta(days=p.base_days - 1)

    texts, labels, words = [], [], [0, 0]
    for _, text, date, n in documents(p.lang, p.min_words, base_start, end):
        is_recent = date >= recent_start
        texts.append(text)
        labels.append(is_recent)
        words[0 if is_recent else 1] += n
    labels = np.array(labels, dtype=bool)
    if labels.sum() == 0 or (~labels).sum() == 0:
        raise ValueError("Need speeches in both the recent and the baseline window")
    log(f"{labels.sum():,} recent and {(~labels).sum():,} baseline speeches")

    vectorizer = CountVectorizer(
        stop_words=STOP_WORDS[p.lang],
        token_pattern=TOKEN_PATTERN,
        ngram_range=(1, 2),
        min_df=3,
        max_features=100_000,
        dtype=np.int32,
    )
    X = vectorizer.fit_transform(texts)
    vocab = vectorizer.get_feature_names_out()
    y_recent = np.asarray(X[labels].sum(axis=0)).ravel().astype(float)
    y_base = np.asarray(X[~labels].sum(axis=0)).ravel().astype(float)
    combined = y_recent + y_base
    prior = combined / combined.sum() * (combined.sum() * p.prior_strength)
    z = log_odds_z(y_recent, y_base, prior)

    def rows(indices):
        out = []
        for j in indices:
            out.append(
                {
                    "term": str(vocab[j]),
                    "z": round(float(z[j]), 2),
                    "recent": int(y_recent[j]),
                    "base": int(y_base[j]),
                    "rate_recent": round(10_000 * y_recent[j] / words[0], 2),
                    "rate_base": round(10_000 * y_base[j] / words[1], 2),
                }
            )
        return out

    order = np.argsort(z)
    rising = _dedupe(
        [j for j in order[::-1] if y_recent[j] >= p.min_count and z[j] > 0], vocab, y_recent
    )[: p.top]
    fading = _dedupe([j for j in order if y_base[j] >= p.min_count and z[j] < 0], vocab, y_base)[
        : p.top
    ]
    shift = TermShift.objects.create(
        lang=p.lang,
        recent_start=recent_start,
        recent_end=end,
        base_start=base_start,
        base_end=base_end,
        words_recent=words[0],
        words_base=words[1],
        rising=rows(rising),
        fading=rows(fading),
        params={**p.__dict__, "vocabulary": len(vocab)},
    )
    TermShift.objects.filter(lang=p.lang).exclude(pk=shift.pk).delete()
    return shift


def z_label(z: float) -> str:
    """Plain-language strength for a z-score."""
    a = abs(z)
    return "very strong" if a >= 10 else "strong" if a >= 5 else "clear" if a >= 3 else "weak"
