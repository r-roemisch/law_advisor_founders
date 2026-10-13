"""Keeping the Corpus current: the public "What changed" feed, admin-only update runs with live
progress, the review queue, and the daily schedule."""

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from typing import Literal

import yaml
from fastapi import APIRouter, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from .disclaimer import DISCLAIMER
from .evaluation.run import RESULTS_DIR
from .ingestion.cli import select_entries
from .ingestion.http import Fetcher
from .ingestion.registry import load_registry
from .ingestion.update import approve, reject, run_update
from .observability import coverage_status, usage_summary
from .settings import REPO_ROOT

log = logging.getLogger(__name__)
router = APIRouter()


def _require_admin(request: Request, authorization: str | None) -> None:
    token = request.app.state.flg.settings.admin_token
    if not token:
        raise HTTPException(503, "Admin features are disabled: set ADMIN_TOKEN on the server")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "Invalid admin token")


@router.get("/api/changes")
def changes(
    request: Request,
    limit: int = 50,
    status: Literal["applied", "review_needed", "approved", "rejected"] | None = None,
) -> dict:
    flg = request.app.state.flg
    sources = flg.tool_context.sources
    rows = []
    for change in flg.corpus_state.changes(min(max(limit, 1), 200), status):
        entry = sources.get(change.source_id)
        rows.append(
            change.public()
            | {
                "source": entry.citation_name(change.language) if entry else change.source_id,
                "jurisdiction": entry.jurisdiction if entry else None,
                "tier": entry.tier if entry else None,
                "url": entry.ref.get("url") if entry else None,
            }
        )
    return {"changes": rows, "disclaimer": DISCLAIMER}


@router.get("/api/admin/check")
def check_admin(request: Request, authorization: str | None = Header(default=None)) -> dict:
    _require_admin(request, authorization)
    return {"ok": True}


@router.post("/api/admin/update")
async def start_update(
    request: Request, authorization: str | None = Header(default=None), body: dict | None = None
) -> EventSourceResponse:
    _require_admin(request, authorization)
    flg = request.app.state.flg
    if flg.settings.demo_mode:
        raise HTTPException(409, "Updates fetch official sources; not available in demo mode")
    if flg.update_lock.locked():
        raise HTTPException(409, "An update is already running")
    sources = (body or {}).get("sources")
    return EventSourceResponse(_stream_update(flg, sources))


@router.post("/api/admin/changes/{change_id}/{decision}")
async def decide(
    change_id: int,
    decision: Literal["approve", "reject"],
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_admin(request, authorization)
    flg = request.app.state.flg
    try:
        if decision == "approve":
            change = await asyncio.to_thread(
                approve, change_id, flg.enabled_strategies(), flg.corpus_state
            )
        else:
            change = reject(change_id, flg.corpus_state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return change.public() | {"disclaimer": DISCLAIMER}


async def _stream_update(flg, sources: list[str] | None) -> AsyncIterator[dict]:
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_event(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async with flg.update_lock:
        task = asyncio.create_task(asyncio.to_thread(_run, flg, sources, on_event))
        while not (task.done() and queue.empty()):
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            yield {"event": event["type"], "data": json.dumps(event, default=str)}
        if task.exception():
            log.error("update run failed", exc_info=task.exception())
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": "The update run failed."}),
            }
    yield {"event": "done", "data": json.dumps({"type": "done", "disclaimer": DISCLAIMER})}


def _run(flg, sources: list[str] | None, on_event) -> dict:
    entries, _ = select_entries(load_registry(flg.settings.config_dir / "sources.yaml"), sources)
    fetcher = Fetcher(refresh=True)
    try:
        report = run_update(entries, fetcher, flg.enabled_strategies(), flg.corpus_state, on_event)
    finally:
        fetcher.close()
    return report.summary()


async def scheduled_update(flg) -> None:
    """The daily run (UPDATE_CRON). Skipped when a manual run is in progress."""
    if flg.update_lock.locked():
        log.info("scheduled update skipped: a run is in progress")
        return
    async with flg.update_lock:
        summary = await asyncio.to_thread(_run, flg, None, lambda e: None)
    log.info("scheduled update finished: %s", summary)


@router.get("/api/admin/dashboard")
def dashboard(request: Request, authorization: str | None = Header(default=None)) -> dict:
    """Coverage of the Coverage Map, usage and costs, Gap Signals, latest evaluation runs."""
    _require_admin(request, authorization)
    flg = request.app.state.flg
    config_dir = flg.settings.config_dir if not flg.settings.demo_mode else REPO_ROOT / "config"
    cells = yaml.safe_load((config_dir / "coverage.yaml").read_text(encoding="utf-8"))["cells"]
    records = flg.request_log.recent(500)
    return {
        "coverage": coverage_status(cells, flg.corpus_state.indexed_sources()),
        "usage": usage_summary(records),
        "gap_signals": [
            {
                "at": r.at.isoformat(),
                "question": r.question,
                "signal": r.gap_signal,
                "strategy": r.strategy,
            }
            for r in records
            if r.gap_signal
        ][:50],
        "evaluations": _latest_evaluations(),
        "pending_reviews": len(flg.corpus_state.changes(200, "review_needed")),
        "disclaimer": DISCLAIMER,
    }


def _latest_evaluations(limit: int = 6) -> list[dict]:
    """Summaries of the newest result files in data/eval (items omitted)."""
    summaries = []
    for path in sorted(RESULTS_DIR.glob("*.json"), reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs = [{k: v for k, v in run.items() if k != "items"} for run in data.get("runs", [])]
        summaries.append(
            {"file": path.name, "reviewed_only": data.get("reviewed_only"), "runs": runs}
        )
    return summaries
