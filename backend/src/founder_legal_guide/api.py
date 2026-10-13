"""HTTP API. Every response carries the "not legal advice" header (ADR 0002)."""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from . import demo
from .answering import ANSWERING_MODES, RetrievedSet, Turn, stream_turn
from .config import ModelsConfig, StrategiesConfig, load_models, load_strategies
from .disclaimer import DISCLAIMER, DISCLAIMER_HEADER
from .examples import EXAMPLE_QUESTIONS
from .ingestion.http import Fetcher
from .ingestion.state import CorpusState, MemoryVersionStore, PostgresVersionStore
from .ingestion.update import run_update
from .models import ModelFactory
from .observability import (
    MemoryRequestLog,
    PostgresRequestLog,
    RequestLog,
    RequestRecord,
    estimate_cost,
)
from .profile import FounderProfile
from .ratelimit import RateLimiter
from .retrieval.context import ComponentContext
from .retrieval.strategy import RetrievalStrategy
from .retrieval.types import SearchFilters
from .settings import REPO_ROOT, Settings, get_settings
from .tools import ToolContext, build_domain_tools
from .updates_api import router as updates_router
from .updates_api import scheduled_update

log = logging.getLogger(__name__)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class AppState:
    """Loaded config plus lazily built Retrieval Strategies."""

    def __init__(self, settings: Settings, models: ModelFactory | None = None):
        self.settings = settings
        self._strategies: dict[str, RetrievalStrategy] = {}
        if settings.demo_mode:
            self.strategies_config: StrategiesConfig = demo.DEMO_STRATEGIES
            self.models_config: ModelsConfig = demo.DEMO_MODELS
            self.models = demo.DemoModelFactory()
        else:
            self.strategies_config = load_strategies(settings.config_dir / "strategies.yaml")
            self.models_config = load_models(settings.config_dir / "models.yaml")
            self.models = models or ModelFactory(settings)
        self.ctx = ComponentContext(settings, self.models, self.models_config.utility.id)
        self.corpus_state: CorpusState = (
            MemoryVersionStore()
            if settings.demo_mode
            else PostgresVersionStore(settings.database_url)
        )
        self.tool_context = ToolContext.load(
            settings.config_dir if not settings.demo_mode else REPO_ROOT / "config",
            version_store=self.corpus_state,
            fetcher_factory=Fetcher,
        )
        self.update_lock = asyncio.Lock()
        self.rate_limiter = RateLimiter(
            settings.rate_limit_requests, settings.rate_limit_window_seconds
        )
        self.request_log: RequestLog = (
            MemoryRequestLog() if settings.demo_mode else PostgresRequestLog(settings.database_url)
        )
        if settings.demo_mode:
            # The sample Corpus is loaded through the normal update path, so its Change Records
            # in the "What changed" feed are real ("added" at startup).
            entries = [demo.sample_entry(doc) for doc in demo.SAMPLE_DOCUMENTS]
            run_update(entries, None, self.enabled_strategies(), self.corpus_state)

    def enabled_strategies(self) -> list[RetrievalStrategy]:
        return [self.strategy(name) for name in self.strategies_config.enabled()]

    def strategy(self, name: str) -> RetrievalStrategy:
        if name not in self._strategies:
            self._strategies[name] = RetrievalStrategy(
                self.strategies_config.strategies[name], self.ctx
            )
        return self._strategies[name]


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    strategy: str | None = None
    answer_model: str | None = None
    answering_mode: str = "single_pass"
    jurisdictions: list[Literal["EU", "DE", "US"]] | None = None
    profile: FounderProfile | None = None
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)

    @field_validator("question")
    @classmethod
    def _clean(cls, value: str) -> str:
        value = _CONTROL_CHARS.sub("", value).strip()
        if not value:
            raise ValueError("Question is empty")
        return value


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        flg = app.state.flg = state or AppState(get_settings())
        scheduler = _start_scheduler(flg)
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="Founder Legal Guide", description=DISCLAIMER, lifespan=lifespan)
    settings = state.settings if state else get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=[DISCLAIMER_HEADER],
    )

    @app.middleware("http")
    async def add_disclaimer(request: Request, call_next):
        response = await call_next(request)
        response.headers[DISCLAIMER_HEADER] = DISCLAIMER
        return response

    app.include_router(updates_router)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "disclaimer": DISCLAIMER}

    @app.get("/api/options")
    def options(request: Request) -> dict:
        flg: AppState = request.app.state.flg
        return {
            "disclaimer": DISCLAIMER,
            "demo_notice": demo.DEMO_NOTICE if flg.settings.demo_mode else None,
            "examples": demo.DEMO_EXAMPLES if flg.settings.demo_mode else EXAMPLE_QUESTIONS,
            "default_strategy": flg.strategies_config.default,
            "strategies": [
                {"name": s.name, "description": s.description}
                for s in flg.strategies_config.enabled().values()
            ],
            "answer_models": [m.model_dump() for m in flg.models_config.answer],
            "answering_modes": [
                {
                    "name": name,
                    "label": ANSWERING_MODES.get(name).label,
                    "description": ANSWERING_MODES.get(name).description,
                }
                for name in ANSWERING_MODES.names()
            ],
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request) -> EventSourceResponse:
        flg: AppState = request.app.state.flg
        client = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or (
            request.client.host if request.client else "unknown"
        )
        if (retry := flg.rate_limiter.check(client)) is not None:
            raise HTTPException(
                429,
                f"Too many questions in a short time. Please try again in {int(retry) + 1} seconds.",
                headers={"Retry-After": str(int(retry) + 1)},
            )
        turn, mode = _prepare_turn(flg, body)
        utility = flg.models.chat(flg.models_config.utility.id, temperature=0.0)
        model_id = body.answer_model or flg.models_config.default_answer
        return EventSourceResponse(
            _events(flg, turn, mode, body.answering_mode, model_id, utility, body.profile)
        )

    return app


def _start_scheduler(flg: AppState):
    """Daily update run, when configured (UPDATE_CRON) and possible (key set, not demo)."""
    settings = flg.settings
    if not settings.update_cron or settings.demo_mode or not settings.openrouter_api_key:
        return None
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_update, CronTrigger.from_crontab(settings.update_cron), args=[flg])
    scheduler.start()
    log.info("daily update scheduled: %s", settings.update_cron)
    return scheduler


def _prepare_turn(flg: AppState, body: ChatRequest):
    if not flg.settings.openrouter_api_key and not flg.settings.demo_mode:
        raise HTTPException(503, "OPENROUTER_API_KEY is not configured on the server")
    if len(body.question) > flg.settings.max_question_chars:
        raise HTTPException(
            422, f"Question is longer than {flg.settings.max_question_chars} characters"
        )
    strategy_name = body.strategy or flg.strategies_config.default
    if strategy_name not in flg.strategies_config.enabled():
        raise HTTPException(422, f"Unknown or disabled strategy '{strategy_name}'")
    model_id = body.answer_model or flg.models_config.default_answer
    if not flg.models_config.is_answer_model(model_id):
        raise HTTPException(422, f"'{model_id}' is not an offered Answer Model")
    if body.answering_mode not in ANSWERING_MODES:
        raise HTTPException(422, f"Unknown answering mode '{body.answering_mode}'")

    history: list[BaseMessage] = [
        HumanMessage(m.content) if m.role == "user" else AIMessage(m.content) for m in body.history
    ]
    turn = Turn(
        question=body.question,
        history=history,
        strategy=flg.strategy(strategy_name),
        llm=flg.models.chat(model_id),
        filters=SearchFilters(
            jurisdictions=frozenset(body.jurisdictions) if body.jurisdictions else None
        ),
        retrieved=RetrievedSet(),
        max_searches=flg.settings.agentic_max_searches,
        tools=build_domain_tools(flg.tool_context, body.profile),
    )
    return turn, ANSWERING_MODES.get(body.answering_mode)()


async def _events(
    flg, turn: Turn, mode, mode_name: str, model_id: str, utility, profile
) -> AsyncIterator[dict]:
    started = time.monotonic()
    tiers: dict[int, int] = {}
    record = RequestRecord(
        question="", strategy=turn.strategy.name, mode=mode_name, model=model_id, seconds=0
    )
    try:
        async for event in stream_turn(turn, mode, mode_name, utility, profile):
            if event["type"] == "retrieval":
                tiers.update({h["n"]: h["tier"] for h in event["hits"]})
            elif event["type"] == "tool":
                record.tools.append(event["name"])
            elif event["type"] == "answer":
                usage = event["usage"]
                usage["cost_usd"] = estimate_cost(
                    model_id,
                    usage["input_tokens"],
                    usage["output_tokens"],
                    flg.settings.openrouter_base_url,
                )
                record.input_tokens, record.output_tokens = (
                    usage["input_tokens"],
                    usage["output_tokens"],
                )
                record.cost_usd = usage["cost_usd"]
                record.citations = len(event["citations"]["cited"])
                record.citations_ok = event["citations"]["ok"]
                record.cited_tiers = [tiers[n] for n in event["citations"]["cited"] if n in tiers]
                record.escalations = event["escalations"]
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
    except Exception as exc:
        log.exception("turn failed")
        record.error = type(exc).__name__
        error = {
            "type": "error",
            "message": "Something went wrong while answering. Please try again.",
        }
        yield {"event": "error", "data": json.dumps(error)}
    record.question = turn.question  # redacted by the question check
    record.seconds = round(time.monotonic() - started, 2)
    await asyncio.to_thread(flg.request_log.add, record)
    yield {"event": "done", "data": json.dumps({"type": "done", "disclaimer": DISCLAIMER})}
