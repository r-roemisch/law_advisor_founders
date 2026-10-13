"""Reciprocal rank fusion: merges ranked lists without comparing their raw scores."""

from .types import Hit

RRF_K = 60


def reciprocal_rank_fusion(rankings: list[list[Hit]], limit: int) -> list[Hit]:
    scores: dict[str, float] = {}
    passages = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking):
            pid = hit.passage.id
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (RRF_K + rank + 1)
            passages.setdefault(pid, hit.passage)
    ordered = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
    return [Hit(passage=passages[pid], score=scores[pid]) for pid in ordered]
