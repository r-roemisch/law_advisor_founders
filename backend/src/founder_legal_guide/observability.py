"""Request logging, cost estimates, Gap Signals and coverage status for the dashboard.

Only the redacted question (personal data already removed by the question check) is stored.
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

import httpx
import psycopg

log = logging.getLogger(__name__)


@dataclass
class RequestRecord:
    question: str  # redacted
    strategy: str
    mode: str
    model: str
    seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    citations: int = 0
    citations_ok: bool = True
    cited_tiers: list[int] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    escalations: list[int] = field(default_factory=list)
    error: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def gap_signal(self) -> str | None:
        """Evidence that the Corpus lacked what the Founder needed (CONTEXT.md)."""
        if self.error:
            return None
        if self.citations == 0:
            return "no_citations"
        if self.cited_tiers and min(self.cited_tiers) == 3:
            return "tier3_only"
        return None


class RequestLog(Protocol):
    def add(self, record: RequestRecord) -> None: ...
    def recent(self, limit: int = 200) -> list[RequestRecord]: ...


class MemoryRequestLog:
    def __init__(self):
        self._rows: list[RequestRecord] = []

    def add(self, record: RequestRecord) -> None:
        self._rows.append(record)

    def recent(self, limit: int = 200) -> list[RequestRecord]:
        return list(reversed(self._rows))[:limit]


class PostgresRequestLog:
    def __init__(self, database_url: str):
        self._url = database_url
        self._ready = False

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._url, autocommit=True)
        if not self._ready:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS request_log (id serial PRIMARY KEY, at timestamptz NOT NULL, record jsonb NOT NULL)"
            )
            self._ready = True
        return conn

    def add(self, record: RequestRecord) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO request_log (at, record) VALUES (%s, %s)",
                    (record.at, json.dumps(asdict(record), default=str)),
                )
        except psycopg.Error as exc:  # logging must never break answering
            log.warning("request log unavailable: %s", exc)

    def recent(self, limit: int = 200) -> list[RequestRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record FROM request_log ORDER BY id DESC LIMIT %s", (limit,)
            ).fetchall()
        records = []
        for (data,) in rows:
            data["at"] = datetime.fromisoformat(data["at"])
            records.append(RequestRecord(**data))
        return records


@lru_cache(maxsize=1)
def _prices(base_url: str) -> dict[str, tuple[float, float]]:
    """Model id → (USD per input token, USD per output token), from OpenRouter's model list."""
    try:
        data = httpx.get(f"{base_url}/models", timeout=15).json()["data"]
        return {
            m["id"]: (float(m["pricing"]["prompt"]), float(m["pricing"]["completion"]))
            for m in data
        }
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        log.warning("could not load OpenRouter prices: %s", exc)
        return {}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, base_url: str) -> float | None:
    price = _prices(base_url).get(model)
    if price is None:
        return None
    return round(input_tokens * price[0] + output_tokens * price[1], 6)


def coverage_status(cells: list[dict], indexed: set[str]) -> list[dict]:
    """Per Coverage Map cell: which required Sources are in the Corpus."""
    result = []
    for cell in cells:
        missing = [s for s in cell["required"] if s not in indexed]
        result.append(
            {
                "legal_area": cell["legal_area"],
                "jurisdiction": cell["jurisdiction"],
                "depth": cell.get("depth"),
                "required": len(cell["required"]),
                "indexed": len(cell["required"]) - len(missing),
                "missing": missing,
            }
        )
    return result


def usage_summary(records: list[RequestRecord]) -> dict:
    by_model: dict[str, dict] = {}
    for r in records:
        m = by_model.setdefault(
            r.model, {"requests": 0, "cost_usd": 0.0, "tokens": 0, "seconds": []}
        )
        m["requests"] += 1
        m["cost_usd"] += r.cost_usd or 0.0
        m["tokens"] += r.input_tokens + r.output_tokens
        m["seconds"].append(r.seconds)
    for m in by_model.values():
        seconds = sorted(m.pop("seconds"))
        m["median_seconds"] = seconds[len(seconds) // 2] if seconds else None
        m["cost_usd"] = round(m["cost_usd"], 4)
    return {
        "requests": len(records),
        "errors": sum(r.error is not None for r in records),
        "cost_usd": round(sum(r.cost_usd or 0.0 for r in records), 4),
        "by_model": by_model,
        "escalations": sum(bool(r.escalations) for r in records),
        "gap_signals": sum(r.gap_signal is not None for r in records),
    }
