"""Commands for the Golden Set and evaluation runs.

founder-legal-guide-golden                         # draft config/golden_set.yaml for review
founder-legal-guide-eval retrieval                 # every enabled strategy, retrieval metrics
founder-legal-guide-eval answers --strategy S1 --mode single_pass agentic --model <id>
"""

import argparse
import asyncio
import logging
import sys

import yaml

from ..api import AppState
from ..config import load_models
from ..ingestion.registry import load_registry
from ..settings import get_settings
from .golden import GoldenSet, draft_escalations, draft_golden_set, load_golden_set, save_golden_set
from .run import evaluate_answers, evaluate_retrieval, save_results

HEADER = """# Golden Set: test questions with the passages each must retrieve (CONTEXT.md, ADR 0005).
#
# Not legal advice: the Founder Legal Guide provides general legal information only.
#
# Drafted by the judge model from real provisions sampled per Coverage Map cell. REVIEW EACH ITEM:
#   - Is the question realistic for a founder, and answerable from the expected passages?
#   - Is the reference answer correct and grounded in them?
#   - Would other passages also answer it correctly? ADD THEM to `expected` (source_id + label, anchor
#     if known, e.g. {source_id: eu-gdpr, label: "Art. 33 – ...", anchor: art_33}). A question counts as
#     found if ANY expected passage is retrieved; a too-narrow list scores correct retrieval as a miss.
#   Then set `status: reviewed` (or `rejected`, with a reason in `notes`). Headline results use reviewed
#   items only.
"""


def golden_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="founder-legal-guide-golden")
    parser.add_argument("--per-cell", type=int, default=2)
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing golden_set.yaml"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    path = settings.config_dir / "golden_set.yaml"
    if path.exists() and not args.force:
        print(f"{path} exists; reviewed work would be lost. Use --force to redraft.")
        return 2
    from ..models import ModelFactory

    judge = ModelFactory(settings).chat(
        load_models(settings.config_dir / "models.yaml").judge.id, temperature=0.3
    )
    cells = yaml.safe_load((settings.config_dir / "coverage.yaml").read_text(encoding="utf-8"))[
        "cells"
    ]
    sources = {e.id: e for e in load_registry(settings.config_dir / "sources.yaml")}
    golden = draft_golden_set(cells, sources, judge, per_cell=args.per_cell)
    golden.items += draft_escalations(judge)
    save_golden_set(golden, path, HEADER)
    print(f"Drafted {len(golden.items)} items → {path}. Review them before trusting results.")
    return 0


def eval_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="founder-legal-guide-eval")
    sub = parser.add_subparsers(dest="kind", required=True)
    retrieval = sub.add_parser("retrieval", help="Retrieval metrics for strategies (cheap)")
    retrieval.add_argument("--strategy", nargs="+", help="Default: every enabled strategy")
    answers = sub.add_parser(
        "answers", help="Full answers through the chat pipeline (costs model calls)"
    )
    answers.add_argument("--strategy", nargs="+", default=None)
    answers.add_argument("--mode", nargs="+", default=["single_pass"])
    answers.add_argument(
        "--model",
        nargs="+",
        default=None,
        help="Answer Model ids (default: the first in models.yaml)",
    )
    for p in (retrieval, answers):
        p.add_argument(
            "--reviewed-only", action="store_true", help="Use only reviewed Golden Set items"
        )
        p.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    golden: GoldenSet = load_golden_set(settings.config_dir / "golden_set.yaml")
    items = golden.usable(args.reviewed_only)[: args.limit]
    if not items:
        print("No usable Golden Set items (draft one with founder-legal-guide-golden).")
        return 2
    state = AppState(settings)
    names = args.strategy or list(state.strategies_config.enabled())

    if args.kind == "retrieval":
        runs = [evaluate_retrieval(state.strategy(n), items) for n in names]
        print(f"{'strategy':<14} {'hit@k':>6} {'recall':>7} {'MRR':>6}   ({len(items)} questions)")
        for r in runs:
            print(
                f"{r['strategy']:<14} {r['hit_rate'] or 0:>6.2f} {r['recall'] or 0:>7.2f} {r['mrr'] or 0:>6.2f}"
            )
        print(save_results("retrieval", {"runs": runs, "reviewed_only": args.reviewed_only}))
        return 0

    models = args.model or [state.models_config.default_answer]
    runs = []
    for name in names[:1] if not args.strategy else names:
        for mode in args.mode:
            for model in models:
                judge = (
                    state.models.chat(state.models_config.judge.id, temperature=0.0)
                    if args.judge
                    else None
                )
                runs.append(asyncio.run(evaluate_answers(state, items, name, mode, model, judge)))
                r = runs[-1]
                print(
                    f"{name:<10} {mode:<12} {model:<30} cited-expected {r['cited_expected']} · citations valid "
                    f"{r['citations_valid']} · escalations {r['escalation_accuracy']} · tax {r['tax_accuracy']} · "
                    f"median {r['median_seconds']}s · errors {r['errors']}"
                    + (
                        f" · faithfulness {r['faithfulness']} · relevancy {r['answer_relevancy']}"
                        f" · ctx precision {r['context_precision']} · ctx recall {r['context_recall']}"
                        if args.judge
                        else ""
                    )
                )
    print(save_results("answers", {"runs": runs, "reviewed_only": args.reviewed_only}))
    return 0


if __name__ == "__main__":
    sys.exit(eval_main())
