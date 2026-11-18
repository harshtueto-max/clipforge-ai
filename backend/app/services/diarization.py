"""Lightweight local speaker diarization.

Approach: MFCC + delta statistics over 1.5 s sliding windows inside speech regions, standardised, then
agglomerative clustering with the number of speakers chosen by silhouette score. This is an *approximate*
method (no neural speaker embeddings) and is labelled as such in the UI. Speakers are anonymous
("Speaker 1", "Speaker 2", ...) - identities are never inferred.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

log = logging.getLogger("clipforge.diarization")

WIN = 1.5
STEP = 0.75


def _ward_cluster(X: np.ndarray, k: int) -> np.ndarray:
    """Pure-NumPy Ward hierarchical clustering (avoids Cython extensions blocked by Windows Smart App Control)."""
    n = len(X)
    if k <= 1 or n <= k:
        return np.zeros(n, dtype=int)
    # Cap merge matrix at <= 600 prototypes via deterministic stride, then assign all points to final centroids
    if n > 600:
        sub_idx = np.linspace(0, n - 1, 600).astype(int)
        sub_labels = _ward_cluster(X[sub_idx], k)
        cents = np.stack([X[sub_idx][sub_labels == c].mean(axis=0) for c in range(k)])
        return np.argmin(((X[:, None, :] - cents[None, :, :]) ** 2).sum(axis=-1), axis=1)
    means = X.astype(np.float64).copy()
    sizes = np.ones(n, dtype=np.float64)
    active = np.ones(n, dtype=bool)
    members: list[list[int]] = [[i] for i in range(n)]
    # Pairwise Ward merge cost: (n_i * n_j / (n_i + n_j)) * ||mu_i - mu_j||^2
    diff = means[:, None, :] - means[None, :, :]
    sq = (diff * diff).sum(axis=-1)
    cost = (sizes[:, None] * sizes[None, :] / (sizes[:, None] + sizes[None, :])) * sq
    np.fill_diagonal(cost, np.inf)
    for _ in range(n - k):
        flat = int(np.argmin(cost))
        a, b = divmod(flat, n)
        if a > b:
            a, b = b, a
        tot = sizes[a] + sizes[b]
        means[a] = (sizes[a] * means[a] + sizes[b] * means[b]) / tot
        sizes[a] = tot
        members[a].extend(members[b])
        active[b] = False
        cost[b, :] = np.inf
        cost[:, b] = np.inf
        act = np.where(active)[0]
        act = act[act != a]
        if len(act):
            d = ((means[act] - means[a]) ** 2).sum(axis=-1)
            w = (sizes[act] * sizes[a] / (sizes[act] + sizes[a])) * d
            cost[a, act] = w
            cost[act, a] = w
    labels = np.zeros(n, dtype=int)
    for cid, idx in enumerate(np.where(active)[0]):
        for m in members[idx]:
            labels[m] = cid
    return labels


def _silhouette(X: np.ndarray, labels: np.ndarray) -> float:
    uniq = np.unique(labels)
    if len(uniq) < 2:
        return -1.0
    if len(X) > 600:
        idx = np.linspace(0, len(X) - 1, 600).astype(int)
        X, labels = X[idx], labels[idx]
    D = np.sqrt(np.maximum(0.0, ((X[:, None, :] - X[None, :, :]) ** 2).sum(axis=-1)))
    sils = np.zeros(len(X), dtype=np.float64)
    for i in range(len(X)):
        own = labels == labels[i]
        n_own = int(own.sum())
        a = float(D[i, own].sum() / max(1, n_own - 1)) if n_own > 1 else 0.0
        b = min(float(D[i, labels == c].mean()) for c in uniq if c != labels[i] and (labels == c).any())
        denom = max(a, b)
        sils[i] = (b - a) / denom if denom > 1e-9 else 0.0
    return float(sils.mean())


def diarize(audio: np.ndarray, sr: int, vad: list[dict[str, float]], words: list[dict[str, Any]],
            sentences: list[dict[str, Any]], max_speakers: int = 4) -> dict[str, Any]:
    import librosa

    windows: list[tuple[float, float]] = []
    for seg in vad:
        t = seg["s"]
        while t + WIN * 0.6 <= seg["e"]:
            windows.append((t, min(seg["e"], t + WIN)))
            t += STEP
    if len(windows) < 8:
        return _single(words, sentences, "too little speech for diarization")
    # cap windows for very long inputs (uniform subsample for clustering, then assign all)
    feats = []
    for s, e in windows:
        seg = audio[int(s * sr): int(e * sr)]
        if len(seg) < sr * 0.4:
            feats.append(None)
            continue
        mf = librosa.feature.mfcc(y=seg, sr=sr, n_mfcc=20, n_fft=512, hop_length=160)
        d = librosa.feature.delta(mf)
        vec = np.concatenate([mf[1:].mean(axis=1), mf[1:].std(axis=1), d[1:].std(axis=1)])
        feats.append(vec)
    idx = [i for i, f in enumerate(feats) if f is not None]
    if len(idx) < 8:
        return _single(words, sentences, "too little speech for diarization")
    X = np.stack([feats[i] for i in idx]).astype(np.float64)
    X = (X - X.mean(axis=0)) / np.maximum(1e-6, X.std(axis=0))
    rng = np.random.default_rng(0)
    fit_idx = np.arange(len(X))
    if len(X) > 2500:
        fit_idx = np.sort(rng.choice(len(X), 2500, replace=False))
    Xf = X[fit_idx]
    best_k, best_sil, best_labels = 1, -1.0, None
    for k in range(2, max(2, max_speakers) + 1):
        if len(Xf) <= k * 3:
            break
        lab = _ward_cluster(Xf, k)
        counts = np.bincount(lab, minlength=k)
        if counts.min() < max(3, 0.03 * len(Xf)):
            continue
        sil = _silhouette(Xf, lab)
        if sil > best_sil:
            best_k, best_sil, best_labels = k, sil, lab
    if best_labels is None or best_sil < 0.06:
        return _single(words, sentences, f"single speaker (silhouette {best_sil:.2f})")
    # centroids & assign all windows
    cents = np.stack([Xf[best_labels == c].mean(axis=0) for c in range(best_k)])
    all_lab = np.argmin(((X[:, None, :] - cents[None]) ** 2).sum(-1), axis=1)
    # temporal smoothing (majority over 5 windows)
    sm = all_lab.copy()
    for i in range(len(all_lab)):
        a, b = max(0, i - 2), min(len(all_lab), i + 3)
        sm[i] = np.bincount(all_lab[a:b], minlength=best_k).argmax()
    win_times = np.array([windows[i] for i in idx])
    centers = win_times.mean(axis=1)
    # order speakers by first appearance
    order = []
    for l in sm:
        if l not in order:
            order.append(int(l))
    remap = {old: new for new, old in enumerate(order)}
    sm = np.array([remap[int(l)] for l in sm])

    def label_at(t: float) -> int:
        j = int(np.argmin(np.abs(centers - t)))
        return int(sm[j])

    for w in words:
        w["spk"] = label_at((w["s"] + w["e"]) / 2)
    for s in sentences:
        labs = [words[i]["spk"] for i in range(s["w0"], s["w1"])]
        s["speaker"] = int(np.bincount(labs).argmax()) if labs else 0
    turns = _turns(sentences)
    stats = []
    for k in range(best_k):
        t = sum(x["e"] - x["s"] for x in turns if x["speaker"] == k)
        stats.append({"label": f"Speaker {k + 1}", "index": k, "speaking_time": round(t, 1),
                      "turns": sum(1 for x in turns if x["speaker"] == k)})
    return {"method": "mfcc-agglomerative (approximate)", "num_speakers": best_k, "silhouette": round(float(best_sil), 3),
            "speakers": stats, "turns": turns, "note": "Approximate clustering; speakers are anonymous."}


def _turns(sentences):
    turns = []
    for s in sentences:
        sp = s.get("speaker", 0)
        if turns and turns[-1]["speaker"] == sp:
            turns[-1]["e"] = s["e"]
        else:
            turns.append({"speaker": sp, "s": s["s"], "e": s["e"]})
    return turns


def _single(words, sentences, note):
    for w in words:
        w["spk"] = 0
    for s in sentences:
        s["speaker"] = 0
    total = sum(s["e"] - s["s"] for s in sentences)
    return {"method": "none", "num_speakers": 1, "silhouette": None,
            "speakers": [{"label": "Speaker 1", "index": 0, "speaking_time": round(total, 1), "turns": 1}],
            "turns": _turns(sentences), "note": note}
