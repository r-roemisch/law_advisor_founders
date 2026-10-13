"""Live source check: is the version in the Corpus still the current official one?"""

import io
import re
import zipfile
from typing import Literal

from pydantic import BaseModel, Field

from ..ingestion.adapters.eurlex import EurLexAdapter
from ..ingestion.adapters.gii import ZIP_URL
from ..ingestion.http import FetchError
from .context import ToolContext


class CurrencyQuery(BaseModel):
    source_id: str = Field(
        description="A Source id from the registry, e.g. 'eu-ai-act' or 'de-bdsg'."
    )


class CurrencyResult(BaseModel):
    source_id: str
    status: Literal[
        "up_to_date", "newer_version_available", "not_indexed", "unknown", "unsupported"
    ]
    indexed: dict[str, str]
    official: str | None
    detail: str


def check_source_currency(query: CurrencyQuery, ctx: ToolContext) -> CurrencyResult:
    entry = ctx.sources.get(query.source_id)
    if entry is None:
        return CurrencyResult(
            source_id=query.source_id,
            status="unknown",
            indexed={},
            official=None,
            detail="No such Source in the registry.",
        )
    stored = ctx.version_store.versions(entry.id) if ctx.version_store else {}
    indexed = {lang: version for lang, (version, _) in stored.items()}
    if entry.adapter not in ("eurlex", "gii"):
        return CurrencyResult(
            source_id=entry.id,
            status="unsupported",
            indexed=indexed,
            official=None,
            detail=f"Live checks are not available for '{entry.adapter}' Sources yet.",
        )
    fetcher = ctx.fetcher_factory()
    try:
        if entry.adapter == "eurlex":
            official = (
                EurLexAdapter(fetcher).latest_consolidated(entry.ref["celex"]) or entry.ref["celex"]
            )
            current = lambda version: version == official
        else:
            official = _gii_build_date(fetcher, entry.ref["slug"])
            current = lambda version: version.startswith(official)
    except (FetchError, ValueError, KeyError) as exc:
        return CurrencyResult(
            source_id=entry.id,
            status="unknown",
            indexed=indexed,
            official=None,
            detail=f"Could not reach the official source: {exc}",
        )
    finally:
        fetcher.close()

    if not indexed:
        return CurrencyResult(
            source_id=entry.id,
            status="not_indexed",
            indexed={},
            official=official,
            detail="This Source has not been ingested yet.",
        )
    stale = {lang: v for lang, v in indexed.items() if not current(v)}
    if stale:
        return CurrencyResult(
            source_id=entry.id,
            status="newer_version_available",
            indexed=indexed,
            official=official,
            detail=f"Official version {official} differs from the indexed text ({', '.join(sorted(stale))}). Answers may be outdated until the next update run.",
        )
    return CurrencyResult(
        source_id=entry.id,
        status="up_to_date",
        indexed=indexed,
        official=official,
        detail="The indexed text matches the current official version.",
    )


def _gii_build_date(fetcher, slug: str) -> str:
    archive = fetcher.get(ZIP_URL.format(slug=slug), cache=False)
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".xml"))
        head = zf.read(name)[:2000].decode("utf-8", errors="replace")
    match = re.search(r'<dokumente[^>]*builddate="(\d+)"', head)
    if not match:
        raise ValueError("no build date in the gii XML")
    return match.group(1)
