"""Fill the search indexes from the Source Registry.

founder-legal-guide-ingest --dry-run                      # parse + chunk only, no key needed
founder-legal-guide-ingest --jurisdiction EU DE --tier 1  # index into the default strategy
founder-legal-guide-ingest --strategy S1 S3 --source eu-gdpr de-ddg
founder-legal-guide-ingest --all-strategies
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from ..config import ConfigError, load_models, load_strategies
from ..models import ModelFactory
from ..retrieval.chunkers import StructureChunker
from ..retrieval.context import ComponentContext
from ..retrieval.strategy import RetrievalStrategy
from ..settings import Settings, get_settings
from .adapters import ADAPTERS
from .eurlex_parser import ParseError
from .gii_parser import GiiParseError
from .http import Fetcher, FetchError
from .registry import SourceEntry, load_registry
from .state import PostgresVersionStore
from .update import run_update, section_hashes

log = logging.getLogger("founder_legal_guide.ingest")


@dataclass
class IngestReport:
    indexed: list[tuple[str, str, int, int]] = field(
        default_factory=list
    )  # id, lang, sections, passages
    skipped: list[tuple[str, str]] = field(default_factory=list)  # id, reason
    failed: list[tuple[str, str]] = field(default_factory=list)  # id, error
    characters: int = 0  # text to embed, counted in dry runs for the cost estimate

    @property
    def passages(self) -> int:
        return sum(p for *_, p in self.indexed)


def select_entries(
    entries: list[SourceEntry],
    sources: list[str] | None = None,
    jurisdictions: list[str] | None = None,
    tiers: list[int] | None = None,
) -> tuple[list[SourceEntry], list[tuple[str, str]]]:
    """Entries to ingest, plus (id, reason) for matching entries no adapter can handle yet."""
    if sources:
        unknown = set(sources) - {e.id for e in entries}
        if unknown:
            raise ConfigError(f"Unknown source ids: {', '.join(sorted(unknown))}")
    chosen, unsupported = [], []
    for entry in entries:
        if sources and entry.id not in sources:
            continue
        if jurisdictions and entry.jurisdiction not in jurisdictions:
            continue
        if tiers and entry.tier not in tiers:
            continue
        if entry.adapter in ADAPTERS:
            chosen.append(entry)
        else:
            unsupported.append((entry.id, f"no '{entry.adapter}' adapter yet"))
    return chosen, unsupported


def ingest(
    entries: list[SourceEntry],
    fetcher,
    strategies: list[RetrievalStrategy] | None,
    dry_run_chunker: StructureChunker | None = None,
    version_store=None,
) -> IngestReport:
    """Fetch each entry and index it into every strategy (or only chunk it, for a dry run).
    A failing Source is reported and skipped; it never stops the run."""
    report = IngestReport()
    for entry in entries:
        started = time.monotonic()
        try:
            documents = ADAPTERS.get(entry.adapter)(fetcher).fetch(entry)
            if not documents:
                report.failed.append((entry.id, "no text in any language"))
                continue
            for doc in documents:
                if dry_run_chunker is not None:
                    passages = dry_run_chunker.chunk(doc)
                    report.characters += sum(len(p.embedding_text) for p in passages)
                    count = len(passages)
                else:
                    # Strategies index in parallel: each one is mostly waiting on embedding calls.
                    count, ok = 0, True
                    with ThreadPoolExecutor(max_workers=max(len(strategies or []), 1)) as pool:
                        futures = {pool.submit(s.index_document, doc): s for s in strategies or []}
                    for future, strategy in futures.items():
                        try:
                            count = max(count, future.result())
                        except Exception as exc:  # noqa: BLE001  (other strategies still get it)
                            ok = False
                            error = f"{type(exc).__name__}: {str(exc)[:200]}"
                            report.failed.append((f"{entry.id}@{strategy.name}", error))
                            log.warning(
                                "%s (%s) failed in %s: %s",
                                entry.id,
                                doc.language,
                                strategy.name,
                                exc,
                            )
                    # Record the version only when every strategy has it, so updates retry the rest.
                    if version_store is not None and ok:
                        version_store.record(
                            entry.id, doc.language, doc.version, section_hashes(doc)
                        )
                report.indexed.append((entry.id, doc.language, len(doc.sections), count))
            log.info("%s done in %.1fs", entry.id, time.monotonic() - started)
        except (FetchError, ParseError, GiiParseError) as exc:
            report.failed.append((entry.id, str(exc)))
            log.warning("%s failed: %s", entry.id, exc)
        except Exception as exc:
            report.failed.append((entry.id, f"{type(exc).__name__}: {exc}"))
            log.exception("%s failed", entry.id)
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="founder-legal-guide-ingest",
        description="Fill the search indexes from config/sources.yaml. "
        "General legal information, not legal advice.",
    )
    parser.add_argument("--source", nargs="+", help="Source ids (default: all)")
    parser.add_argument("--jurisdiction", nargs="+", choices=["EU", "DE", "US"])
    parser.add_argument("--tier", nargs="+", type=int, choices=[1, 2, 3])
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--strategy", nargs="+", help="Retrieval Strategies (default: the default one)"
    )
    group.add_argument("--all-strategies", action="store_true", help="Every enabled strategy")
    parser.add_argument("--refresh", action="store_true", help="Ignore the download cache")
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and chunk only; no embeddings"
    )
    return parser.parse_args(argv)


def _strategies(args: argparse.Namespace, settings: Settings) -> list[RetrievalStrategy]:
    config = load_strategies(settings.config_dir / "strategies.yaml")
    models = load_models(settings.config_dir / "models.yaml")
    if args.all_strategies:
        names = list(config.enabled())
    else:
        names = args.strategy or [config.default]
    unknown = [n for n in names if n not in config.enabled()]
    if unknown:
        raise ConfigError(f"Unknown or disabled strategies: {', '.join(unknown)}")
    ctx = ComponentContext(settings, ModelFactory(settings), models.utility.id)
    return [RetrievalStrategy(config.strategies[n], ctx) for n in names]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parse_args(argv)
    settings = get_settings()
    try:
        entries, unsupported = select_entries(
            load_registry(settings.config_dir / "sources.yaml"),
            args.source,
            args.jurisdiction,
            args.tier,
        )
        if args.dry_run:
            strategies, chunker = None, StructureChunker(None, "")
        else:
            if not settings.openrouter_api_key:
                print(
                    "OPENROUTER_API_KEY is not set (needed for embeddings). Use --dry-run to test parsing."
                )
                return 2
            strategies, chunker = _strategies(args, settings), None
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    fetcher = Fetcher(refresh=args.refresh)
    try:
        store = None if args.dry_run else PostgresVersionStore(settings.database_url)
        report = ingest(entries, fetcher, strategies, chunker, store)
    finally:
        fetcher.close()
    report.skipped.extend(unsupported)
    _print_report(report, strategies, args.dry_run)
    return 1 if report.failed else 0


def _print_report(report: IngestReport, strategies, dry_run: bool) -> None:
    print()
    for source_id, language, sections, passages in report.indexed:
        print(
            f"  ok      {source_id:<34} {language}  {sections:>5} sections  {passages:>5} passages"
        )
    for source_id, reason in report.skipped:
        print(f"  skipped {source_id:<34} {reason}")
    for source_id, error in report.failed:
        print(f"  FAILED  {source_id:<34} {error}")
    target = "dry run (nothing indexed)" if dry_run else ", ".join(s.name for s in strategies)
    print(f"\n{len(report.indexed)} documents, {report.passages} passages → {target}")
    if dry_run:
        print(
            f"About {report.characters // 4:,} tokens to embed per strategy (4 characters per token)."
        )
    print(f"{len(report.skipped)} skipped, {len(report.failed)} failed.")


def update_main(argv: list[str] | None = None) -> int:
    """Incremental update: only changed Sources are re-indexed or queued for review, and every
    change becomes a Change Record. Writes to all enabled strategies by default."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        prog="founder-legal-guide-update",
        description="Detect changed Sources and update the Corpus. Not legal advice.",
    )
    parser.add_argument("--source", nargs="+")
    parser.add_argument("--jurisdiction", nargs="+", choices=["EU", "DE", "US"])
    parser.add_argument("--tier", nargs="+", type=int, choices=[1, 2, 3])
    parser.add_argument("--strategy", nargs="+", help="Default: every enabled strategy")
    args = parser.parse_args(argv)
    args.all_strategies = not args.strategy
    settings = get_settings()
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY is not set (needed for embeddings).")
        return 2
    try:
        entries, unsupported = select_entries(
            load_registry(settings.config_dir / "sources.yaml"),
            args.source,
            args.jurisdiction,
            args.tier,
        )
        strategies = _strategies(args, settings)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2
    fetcher = Fetcher(refresh=True)
    try:
        report = run_update(
            entries, fetcher, strategies, PostgresVersionStore(settings.database_url)
        )
    finally:
        fetcher.close()
    for change in report.changes:
        counts = ", ".join(f"{len(v)} {k}" for k, v in change.summary.items() if v)
        print(f"  {change.status:<14} {change.source_id:<34} {change.language}  {counts}")
    for source_id, error in report.failed:
        print(f"  FAILED         {source_id:<34} {error}")
    print(f"\n{report.summary()} ; {len(unsupported)} Sources have no adapter yet.")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
