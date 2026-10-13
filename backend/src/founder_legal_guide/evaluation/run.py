"""Evaluation runs over the Golden Set.

- Retrieval evaluation (cheap): every Retrieval Strategy searches every question; we measure
  whether the expected passages come back (hit@k, recall@k, MRR).
- Answer evaluation (costs model calls): the real chat pipeline answers each question for a
  given Retrieval Strategy × Answering Mode × Answer Model; we check citations, escalations,
  tax referrals, latency and tokens, and optionally RAGAs scores (judge model fixed).

Results are written to data/eval/<run>.json so runs can be compared later.
"""

import asyncio
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..settings import REPO_ROOT
from . import metrics
from .golden import ExpectedPassage, GoldenItem

RESULTS_DIR = REPO_ROOT / "data" / "eval"


def matches(source_id: str, label: str, anchor: str | None, expected: ExpectedPassage) -> bool:
    if source_id != expected.source_id:
        return False
    if expected.anchor and anchor:
        return anchor == expected.anchor
    return label.endswith(expected.label)


@dataclass
class RetrievalScore:
    item_id: str
    hit: bool
    recall: float
    reciprocal_rank: float
    retrieved: list[str]


def score_retrieval(item: GoldenItem, hits: list[tuple[str, str, str | None]]) -> RetrievalScore:
    """`hits`: (source_id, citation label, anchor) in rank order."""
    found = [any(matches(*h, e) for h in hits) for e in item.expected]
    first = next(
        (
            rank
            for rank, h in enumerate(hits, start=1)
            if any(matches(*h, e) for e in item.expected)
        ),
        None,
    )
    return RetrievalScore(
        item_id=item.id,
        hit=any(found),
        recall=sum(found) / len(found) if found else 0.0,
        reciprocal_rank=1 / first if first else 0.0,
        retrieved=[f"{s} | {label}" for s, label, _ in hits],
    )


def evaluate_retrieval(strategy, items: list[GoldenItem], k: int | None = None) -> dict:
    scores = []
    for item in items:
        if not item.expected:
            continue
        result = strategy.retrieve(item.question, k=k)
        hits = [
            (h.passage.source.id, h.passage.citation_label, h.passage.anchor) for h in result.hits
        ]
        scores.append(score_retrieval(item, hits))
    return {
        "strategy": strategy.name,
        "k": k or strategy.spec.top_k,
        "questions": len(scores),
        "hit_rate": _mean(s.hit for s in scores),
        "recall": _mean(s.recall for s in scores),
        "mrr": _mean(s.reciprocal_rank for s in scores),
        "items": [asdict(s) for s in scores],
    }


@dataclass
class AnswerScore:
    item_id: str
    kind: str
    seconds: float
    tokens: int
    citations_ok: bool | None = None
    cited_expected: bool | None = None
    retrieval: dict | None = None
    escalation_ok: bool | None = None
    tax_ok: bool | None = None
    tools: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)  # RAGAs-style scores, when a judge is given
    answer: str = ""
    contexts: list[str] = field(default_factory=list)
    error: str | None = None


async def answer_item(
    app_state, item: GoldenItem, strategy: str, mode: str, model: str
) -> AnswerScore:
    from ..answering import stream_turn
    from ..api import ChatRequest, _prepare_turn

    body = ChatRequest(
        question=item.question, strategy=strategy, answer_model=model, answering_mode=mode
    )
    turn, answering_mode = _prepare_turn(app_state, body)
    utility = app_state.models.chat(app_state.models_config.utility.id, temperature=0.0)
    started = time.monotonic()
    events = []
    try:
        async for event in stream_turn(turn, answering_mode, mode, utility, None):
            events.append(event)
    except Exception as exc:  # noqa: BLE001  (record the failure, keep evaluating)
        return AnswerScore(
            item.id, item.kind, time.monotonic() - started, 0, error=f"{type(exc).__name__}: {exc}"
        )
    seconds = time.monotonic() - started

    answer = next((e for e in events if e["type"] == "answer"), {})
    guard = next((e for e in events if e["type"] == "guard"), {})
    hits = [h for e in events if e["type"] == "retrieval" for h in e["hits"]]
    score = AnswerScore(
        item_id=item.id,
        kind=item.kind,
        seconds=round(seconds, 1),
        tokens=answer.get("usage", {}).get("total_tokens", 0),
        answer=answer.get("text", ""),
        contexts=[f"{p.citation_label}\n{p.text}" for p in turn.retrieved.passages],
        tools=[e["name"] for e in events if e["type"] == "tool"],
    )
    if answer:
        score.citations_ok = answer["citations"]["ok"]
    if item.expected:
        ranked = [(h["source_id"], h["label"], h.get("anchor")) for h in hits]
        score.retrieval = asdict(score_retrieval(item, ranked)) | {"retrieved": None}
        by_number = {h["n"]: (h["source_id"], h["label"], h.get("anchor")) for h in hits}
        cited = [
            by_number[n] for n in answer.get("citations", {}).get("cited", []) if n in by_number
        ]
        score.cited_expected = any(matches(*c, e) for c in cited for e in item.expected)
    if item.expected_triggers:
        found = {t["id"] for t in guard.get("triggers", [])}
        score.escalation_ok = set(item.expected_triggers) <= found
    if item.expect_tax_referral:
        score.tax_ok = bool(guard.get("tax_question"))
    return score


async def evaluate_answers(
    app_state, items, strategy: str, mode: str, model: str, judge=None, concurrency: int = 4
) -> dict:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(item):
        async with semaphore:
            score = await answer_item(app_state, item, strategy, mode, model)
            if judge is not None and score.error is None and item.kind == "answerable":
                score.metrics = await asyncio.to_thread(
                    _judge_metrics, judge, app_state, item, score
                )
            return score

    scores = await asyncio.gather(*(one(i) for i in items))
    answerable = [s for s in scores if s.retrieval is not None]
    judged = [s.metrics for s in scores if s.metrics]
    return {
        "strategy": strategy,
        "mode": mode,
        "model": model,
        "questions": len(scores),
        "errors": sum(s.error is not None for s in scores),
        "citations_valid": _mean(s.citations_ok for s in scores if s.citations_ok is not None),
        "cited_expected": _mean(s.cited_expected for s in answerable),
        "hit_rate": _mean(s.retrieval["hit"] for s in answerable),
        "recall": _mean(s.retrieval["recall"] for s in answerable),
        "escalation_accuracy": _mean(
            s.escalation_ok for s in scores if s.escalation_ok is not None
        ),
        "tax_accuracy": _mean(s.tax_ok for s in scores if s.tax_ok is not None),
        "faithfulness": _mean(m.get("faithfulness") for m in judged),
        "answer_relevancy": _mean(m.get("answer_relevancy") for m in judged),
        "context_precision": _mean(m.get("context_precision") for m in judged),
        "context_recall": _mean(m.get("context_recall") for m in judged),
        "median_seconds": statistics.median(s.seconds for s in scores) if scores else None,
        "mean_tokens": _mean(s.tokens for s in scores),
        "items": [asdict(s) for s in scores],
    }


def _judge_metrics(judge, app_state, item: GoldenItem, score: AnswerScore) -> dict:
    embeddings = app_state.models.embeddings(app_state.strategies_config.strategies["S1"].embedding)
    return {
        "faithfulness": metrics.faithfulness(judge, score.answer, score.contexts),
        "answer_relevancy": metrics.answer_relevancy(
            judge, embeddings, item.question, score.answer
        ),
        "context_precision": metrics.context_precision(
            judge, item.question, item.reference_answer, score.contexts[:8]
        ),
        "context_recall": metrics.context_recall(judge, item.reference_answer, score.contexts),
    }


def save_results(name: str, results: dict) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"{stamp}-{name}.json"
    path.write_text(
        json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    return path


def _mean(values) -> float | None:
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 3) if values else None
