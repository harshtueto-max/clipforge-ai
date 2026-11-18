"""Local semantic transcript analysis: sentence-level linguistic features, sentiment, topic segmentation,
keywords. No network access, no large models required."""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from . import hinglish

STOPWORDS = set("""a about above after again against all am an and any are aren't as at be because been before being below
between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few for from
further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself him himself his how how's
i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off on once
only or other ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't so some such than
that that's the their theirs them themselves then there there's these they they'd they'll they're they've this those through
to too under until up very was wasn't we we'd we'll we're we've were weren't what what's when when's where where's which
while who who's whom why why's with won't would wouldn't you you'd you'll you're you've your yours yourself yourselves
yeah yes okay ok um uh like just really know mean gonna wanna got get think actually right well thing things lot kind sort
also even still going much many way go say said one two oh hey""".split()) | hinglish.HINGLISH_STOPWORDS

FILLERS = {"um", "uh", "erm", "hmm", "mm", "uhh", "umm", "ah"}
FILLER_PHRASES = ["you know", "i mean", "sort of", "kind of"]

PATTERNS: dict[str, list[tuple[str, float]]] = {
    "hook": [
        (r"\b(here'?s (the thing|why|what|how)|the (truth|secret|problem|reason|mistake|key) (is|was))\b", 1.0),
        (r"\b(most people|nobody|no one|everyone) (don'?t|doesn'?t|thinks?|believes?|knows?|gets? this|realizes?)\b", 1.0),
        (r"\b(never|always|biggest|worst|best|craziest|most important|number one|crazy|insane|wild|shocking)\b", 0.5),
        (r"\b(what if|imagine|did you know|have you ever|guess what)\b", 0.9),
        (r"\b(i (was|got) wrong|i changed my mind|unpopular opinion|hot take|controversial)\b", 1.0),
        (r"\b(stop|don'?t) (doing|do|ever)\b", 0.7),
        (r"\b(the (one|only) thing|if you (want|only)|you need to|you have to)\b", 0.6),
        (r"\b(\d+ (ways|reasons|things|mistakes|tips|steps|signs|years|percent|%))\b", 0.8),
        (r"\b(why|how) (do|does|did|is|are|can|should|would)\b", 0.5),
    ],
    "weak_open": [
        (r"^(so+|and|but|or|because|cause|'cause|cuz|um+|uh+|yeah|yes|no|okay|ok|well|right|like|anyway|also|plus|yet|nor)\b", 1.0),
        (r"^(is|are|was|were|be|been|which|whereas|unless|until|though|although|then|than)\b", 0.95),
        (r"^if\b[^?]{0,70}\.$", 0.65),
        (r"^(it|that|this|those|these|they|he|she|him|her|them)\b(?! (is|was) (the|a|why|what|how))", 0.7),
        (r"\b(as i (said|mentioned)|like (i|we) (said|talked about)|going back to|earlier|the other thing|another thing)\b", 0.8),
    ],
    "conclusion": [
        (r"\b(that'?s (why|how|what|the point|the key|it)|the (lesson|point|bottom line|takeaway) (is|was)|so the answer)\b", 1.0),
        (r"\b(in the end|at the end of the day|ultimately|in short|long story short|that changed|and that'?s)\b", 0.8),
        (r"\b(which means|so basically|so yeah|that'?s all|period|end of story)\b", 0.5),
    ],
    "story": [
        (r"\b(i remember|when i was|one time|years ago|back (then|in)|the first time|story|happened|i told|she said|he said|we were)\b", 0.8),
        (r"\b(then|suddenly|turns out|it turned out|realized|finally|ended up)\b", 0.4),
    ],
    "advice": [
        (r"\b(you should|you need to|you have to|try to|make sure|the key is|my advice|tip|the trick|focus on|start (with|by)|don'?t (be|do|try))\b", 0.8),
        (r"\b(step (one|two|1|2)|first(ly)?,|second(ly)?,|the best way|how to)\b", 0.6),
    ],
    "education": [
        (r"\b(because|the reason|which means|for example|for instance|in other words|basically|research|study|studies|data|evidence|science|scientific)\b", 0.5),
        (r"\b(defined as|is called|means that|works by|the difference between|compared to|percent|per cent|%)\b", 0.7),
    ],
    "opinion": [
        (r"\b(i (think|believe|feel)|in my opinion|honestly|frankly|to be honest|personally|i disagree|i agree|overrated|underrated)\b", 0.6),
        (r"\b(wrong|stupid|ridiculous|absurd|nonsense|myth|lie|scam|bullshit|terrible|hate)\b", 0.7),
    ],
    "humor": [
        (r"\b(haha+|lol|laugh(ing|s|ed)?|funny|hilarious|joke|kidding|ridiculous|dude|oh my god|omg)\b", 0.8),
        (r"\[(laughter|laughs|laughing)\]|\((laughter|laughs|laughing)\)", 1.5),
    ],
    "emotion": [
        (r"\b(love|hate|afraid|scared|cried|crying|tears|heartbroken|proud|grateful|angry|furious|devastated|terrified|amazing|incredible|painful|lonely|depressed|anxiety|died|death|lost)\b", 0.8),
    ],
    "reference_back": [
        (r"\b(as i said|like i said|as we (discussed|talked)|we talked about|you mentioned|that thing|the same thing)\b", 1.0),
    ],
}

_COMPILED = {
    k: [(re.compile(p, re.I), w) for p, w in (v + hinglish.HINGLISH_PATTERNS.get(k, []))]
    for k, v in PATTERNS.items()
}

_vader = None


def vader():
    global _vader
    if _vader is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        _vader = SentimentIntensityAnalyzer()
    return _vader


def pattern_score(text: str, kind: str) -> tuple[float, list[str]]:
    total, hits = 0.0, []
    for rx, w in _COMPILED[kind]:
        for m in rx.finditer(text):
            total += w
            hits.append(m.group(0))
    return total, hits


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z'\-]+|[\u0900-\u097F]{2,}|\d+(?:\.\d+)?%?", text.lower())


def sentence_features(sentences: list[dict[str, Any]], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    an = vader()
    feats = []
    for s in sentences:
        text = s["text"]
        tk = tokens(text)
        n = max(1, len(tk))
        dur = max(0.2, s["e"] - s["s"])
        content = [t for t in tk if t not in STOPWORDS and len(t) > 2]
        fill = sum(1 for t in tk if t in FILLERS) + sum(text.lower().count(p) for p in FILLER_PHRASES)
        vs = an.polarity_scores(text)
        f: dict[str, Any] = {
            "n_words": len(tk),
            "dur": dur,
            "rate": len(tk) / dur,
            "question": text.rstrip().endswith("?"),
            "exclaim": "!" in text,
            "numbers": len(re.findall(r"\b\d+(?:[.,]\d+)?%?|\b(hundred|thousand|million|billion|percent)\b", text, re.I)),
            "you": len(re.findall(r"\byou(r|'re|'ll|'ve)?\b", text, re.I)),
            "filler_ratio": fill / n,
            "lexical_density": len(content) / n,
            "sentiment": vs["compound"],
            "sent_mag": abs(vs["compound"]),
            "asr_conf": float(np.mean([words[i]["p"] for i in range(s["w0"], s["w1"])])) if s["w1"] > s["w0"] else 0.5,
        }
        for kind in PATTERNS:
            sc, hits = pattern_score(text, kind)
            f[kind] = sc
            if hits:
                f[kind + "_hits"] = hits[:3]
        feats.append(f)
    return feats


def tfidf_matrix(sentences: list[dict[str, Any]]):
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [s["text"] for s in sentences]
    if not texts:
        return None, None
    vec = TfidfVectorizer(
        stop_words=list(STOPWORDS),
        token_pattern=r"(?u)(?:\b[a-zA-Z][a-zA-Z'\-]{2,}\b|[\u0900-\u097F]{2,})",
        sublinear_tf=True,
        min_df=1,
    )
    try:
        X = vec.fit_transform(texts)
    except ValueError:
        return None, None
    return X, vec


def topic_segments(sentences: list[dict[str, Any]], X, block: int = 4) -> tuple[list[int], list[int], np.ndarray]:
    """TextTiling-style topic segmentation. Returns (boundary sentence indices, topic id per sentence, gap similarity)."""
    n = len(sentences)
    if X is None or n < block * 2 + 1:
        return [0], [0] * n, np.ones(max(0, n - 1))
    from sklearn.preprocessing import normalize

    Xn = normalize(X)
    sims = np.ones(n - 1)
    for g in range(1, n):
        a0, b1 = max(0, g - block), min(n, g + block)
        left = np.asarray(Xn[a0:g].sum(axis=0)).ravel()
        right = np.asarray(Xn[g:b1].sum(axis=0)).ravel()
        na, nb = np.linalg.norm(left), np.linalg.norm(right)
        sims[g - 1] = float(left @ right / (na * nb)) if na > 0 and nb > 0 else 0.0
    # long pauses also signal topic shifts
    sm = np.convolve(sims, np.ones(3) / 3, mode="same")
    depth = np.zeros_like(sm)
    for i in range(len(sm)):
        lpk = sm[max(0, i - 6): i + 1].max()
        rpk = sm[i: i + 7].max()
        depth[i] = (lpk - sm[i]) + (rpk - sm[i])
    thr = depth.mean() + 0.5 * depth.std()
    bounds = [0]
    min_gap = 5
    for i in np.argsort(-depth):
        if depth[i] < thr:
            break
        g = int(i) + 1
        if all(abs(g - b) >= min_gap for b in bounds):
            bounds.append(g)
    bounds.sort()
    topic = []
    k = -1
    bset = set(bounds)
    for i in range(n):
        if i in bset:
            k += 1
        topic.append(k)
    return bounds, topic, sims


def adjacent_similarity(X) -> np.ndarray:
    if X is None or X.shape[0] < 2:
        return np.zeros(0)
    from sklearn.preprocessing import normalize

    Xn = normalize(X)
    return np.asarray(Xn[:-1].multiply(Xn[1:]).sum(axis=1)).ravel()


def global_keywords(X, vec, top: int = 40) -> list[str]:
    if X is None:
        return []
    scores = np.asarray(X.sum(axis=0)).ravel()
    terms = np.array(vec.get_feature_names_out())
    order = np.argsort(-scores)
    out = [t for t in terms[order] if t not in STOPWORDS and (len(t) > 3 or hinglish.has_devanagari(t))][:top]
    return out


def clip_text_similarity(a: str, b: str) -> float:
    ta, tb = set(tokens(a)) - STOPWORDS, set(tokens(b)) - STOPWORDS
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def title_case(s: str) -> str:
    small = {"a", "an", "the", "and", "but", "or", "for", "nor", "on", "at", "to", "by", "of", "in", "is"}
    words = s.split()
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.lower() in small:
            out.append(w.lower())
        elif w.isupper() and len(w) > 1:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))
